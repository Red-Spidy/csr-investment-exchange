"""Read side. Every function maps to a table, view or function in db/migrations and
returns the camelCase shape web/src/data/api.ts declares. Ranking, rolling windows
and scoring stay in SQL; this module only reshapes rows."""

from typing import Any

from psycopg import Connection

from .util import inr, shape

# Weights are applied inside fn_match_projects. They are repeated here only to
# split a returned match_score into the three bars the UI draws.
MATCH_WEIGHTS = {"similarity": 0.60, "impact": 0.25, "trust": 0.15}
TOP_K = 5


class NotFound(Exception):
    pass


def companies(conn: Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT id, name, cin, fy, avg_net_profit,
                  mandated_csr_budget AS mandated_budget, committed_budget
             FROM companies ORDER BY id"""
    )
    return [shape(r) for r in rows]


def _rulebook(row: dict[str, Any]) -> dict[str, Any]:
    # topic/jitter parameterise the browser demo's synthetic vectors. The database
    # keeps the embedding itself, so they carry no meaning here.
    return {**shape(row), "topic": 0, "jitter": 0}


def rulebooks(conn: Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT id, company_id, fy, requirement_text, focus_areas, preferred_states,
                  target_sdgs, min_budget, max_budget
             FROM csr_rulebooks ORDER BY id"""
    )
    return [_rulebook(r) for r in rows]


def scorecard(conn: Connection) -> list[dict[str, Any]]:
    """View project_scorecard, plus the project's state and NGO id and the money on hold."""
    rows = conn.execute(
        """SELECT sc.project_id, sc.title, sc.status::text AS status, sc.sector, p.state,
                  sc.requested_amount, p.ngo_id, sc.ngo_name,
                  COALESCE(sc.sdgs, '{}') AS sdgs,
                  sc.predicted_value, sc.ci_low, sc.ci_high, sc.metric_unit,
                  sc.anomaly_score, sc.is_anomaly, sc.composite_score, sc.grade::text AS grade,
                  sc.commitment_id,
                  COALESCE(sc.committed_amount, 0) AS committed_amount,
                  sc.released_amount, sc.locked_amount,
                  COALESCE((SELECT SUM(fp.amount) FROM fund_phases fp
                             WHERE fp.commitment_id = sc.commitment_id AND fp.status = 'held'), 0)
                      AS held_amount
             FROM project_scorecard sc
             JOIN projects p ON p.id = sc.project_id
            ORDER BY sc.project_id"""
    )
    return [shape(r) for r in rows]


# ---------------------------------------------------------------- project detail

def _project(conn: Connection, project_id: int) -> dict[str, Any]:
    row = conn.execute(
        """SELECT id, ngo_id, title, proposal_text, sector, state, requested_amount,
                  duration_months, num_phases, status::text AS status
             FROM projects WHERE id = %s""",
        (project_id,),
    ).fetchone()
    if row is None:
        raise NotFound(f"project {project_id} not found")
    return shape(row)


def _one(conn: Connection, sql: str, project_id: int) -> dict[str, Any] | None:
    row = conn.execute(sql, (project_id,)).fetchone()
    return None if row is None else shape(row)


def _extraction(conn: Connection, project_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT project_id, goals, target_metric, beneficiaries, geography, sdgs,
                  sdg_confidence, red_flags, model_version, prompt_version
             FROM project_extractions WHERE project_id = %s""",
        (project_id,),
    ).fetchone()
    if row is None:
        return None
    geo = row.pop("geography")
    out = shape(row)
    out["geography"] = None if geo is None else {
        "state": geo.get("state"),
        "district": geo.get("district"),
        "ruralUrban": geo.get("rural_urban"),
    }
    out["topic"] = 0   # demo-store field, see _rulebook
    out["jitter"] = 0
    return out


def project_detail(conn: Connection, project_id: int) -> dict[str, Any]:
    project = _project(conn, project_id)
    ngo = conn.execute(
        """SELECT id, name, registration_no, sector, state, established_year
             FROM ngos WHERE id = %s""",
        (project["ngoId"],),
    ).fetchone()
    history = conn.execute(
        """SELECT ngo_id, fy, total_spend, admin_expense_ratio, burn_rate_vs_schedule,
                  category_mix_drift, round_number_freq, vendor_concentration,
                  report_latency_days, cost_per_beneficiary
             FROM ngo_spending_history WHERE ngo_id = %s ORDER BY fy""",
        (project["ngoId"],),
    )
    open_commitment = conn.execute(
        """SELECT id FROM commitments WHERE project_id = %s
            ORDER BY (status = 'active') DESC, (status <> 'cancelled') DESC, id LIMIT 1""",
        (project_id,),
    ).fetchone()
    views = commitment_views(conn, [open_commitment["id"]]) if open_commitment else []
    return {
        "project": project,
        "ngo": shape(ngo),
        "extraction": _extraction(conn, project_id),
        "prediction": _one(
            conn,
            """SELECT project_id, metric_name, metric_unit, predicted_value, ci_low, ci_high,
                      impact_norm, model_version
                 FROM impact_predictions WHERE project_id = %s""",
            project_id,
        ),
        "fraud": _one(
            conn,
            """SELECT project_id, ngo_id, anomaly_score, is_anomaly, model_version
                 FROM fraud_scores WHERE project_id = %s""",
            project_id,
        ),
        "risk": _one(
            conn,
            """SELECT project_id, impact_norm, fraud_score, sdg_confidence, ngo_track_record,
                      composite_score, grade::text AS grade, decision::text AS decision
                 FROM risk_grades WHERE project_id = %s""",
            project_id,
        ),
        "history": [shape(r) for r in history],
        "commitment": views[0] if views else None,
    }


# ---------------------------------------------------------------- commitments

def commitment_views(conn: Connection, ids: list[int] | None = None) -> list[dict[str, Any]]:
    """Each commitment with its project, phases and milestones. `ids=None` means all."""
    commitments = conn.execute(
        """SELECT c.id, c.match_id, c.company_id, c.project_id, c.amount, c.num_phases,
                  c.status::text AS status, c.locked_at,
                  n.name AS ngo_name, co.name AS company_name
             FROM commitments c
             JOIN projects  p  ON p.id  = c.project_id
             JOIN ngos      n  ON n.id  = p.ngo_id
             JOIN companies co ON co.id = c.company_id
            WHERE %(all)s OR c.id = ANY(%(ids)s::bigint[])
            ORDER BY c.id""",
        {"all": ids is None, "ids": ids or []},
    ).fetchall()
    if not commitments:
        return []
    cids = [c["id"] for c in commitments]
    pids = [c["project_id"] for c in commitments]

    projects = {
        r["id"]: shape(r)
        for r in conn.execute(
            """SELECT id, ngo_id, title, proposal_text, sector, state, requested_amount,
                      duration_months, num_phases, status::text AS status
                 FROM projects WHERE id = ANY(%s::bigint[])""",
            (pids,),
        )
    }
    phases = conn.execute(
        """SELECT id, commitment_id, phase_no, amount, status::text AS status, released_at
             FROM fund_phases WHERE commitment_id = ANY(%s::bigint[]) ORDER BY commitment_id, phase_no""",
        (cids,),
    ).fetchall()
    milestones = conn.execute(
        """SELECT id, project_id, commitment_id, phase_no, description, due_date, reported_at,
                  evidence_uri, reported_metric, verification_status::text AS verification,
                  verified_by, verified_at, update_text, rating, rating_reason, rating_flags, rated_by
             FROM milestones WHERE commitment_id = ANY(%s::bigint[]) ORDER BY commitment_id, phase_no""",
        (cids,),
    ).fetchall()

    return [
        {
            "commitment": shape(
                {k: v for k, v in c.items() if k not in ("ngo_name", "company_name")}
            ),
            "project": projects[c["project_id"]],
            "ngoName": c["ngo_name"],
            "companyName": c["company_name"],
            "phases": [shape(p) for p in phases if p["commitment_id"] == c["id"]],
            "milestones": [shape(m) for m in milestones if m["commitment_id"] == c["id"]],
        }
        for c in commitments
    ]


def ledger(conn: Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT id, commitment_id, phase_id, amount, txn_type AS type,
                  COALESCE(note, '') AS note, created_at
             FROM fund_transactions ORDER BY id"""
    )
    return [shape(r) for r in rows]


def audit(conn: Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, entity, entity_id, action, COALESCE(detail, '{}') AS detail, created_at "
        "FROM audit_log ORDER BY id"
    )
    return [shape(r) for r in rows]


# ---------------------------------------------------------------- window-function views

def impact_reports(conn: Connection) -> list[dict[str, Any]]:
    """Each project's monthly gains, as the NGO reported them."""
    rows = conn.execute(
        """SELECT id, project_id, period_month, metric_value, update_text, rating, rating_reason,
                  rating_flags, rated_by
             FROM impact_reports ORDER BY project_id, period_month"""
    )
    return [shape(r) for r in rows]


def esg_timeline(conn: Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT company_id, company_name, month, month_impact, active_projects,
                  cumulative_impact, mom_delta, prev_month_impact,
                  rolling_3mo_esg AS rolling_3mo, peer_percentile,
                  COUNT(*) OVER (PARTITION BY month) AS peers_in_month
             FROM company_esg_timeline
            ORDER BY month, company_id"""
    )
    return [shape(r, rolling_3mo="rolling3mo") for r in rows]


def leaderboard(conn: Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT ngo_id, ngo_name, sector, project_count, total_impact, total_funded,
                  impact_per_million, sector_rank, overall_percentile
             FROM ngo_leaderboard ORDER BY ngo_id"""
    )
    return [shape(r) for r in rows]


# ---------------------------------------------------------------- matching

def match_report(conn: Connection, rulebook_id: int) -> dict[str, Any]:
    """fn_match_projects for the ranking, plus the reason each other project is out."""
    rb = conn.execute(
        """SELECT id, company_id, fy, requirement_text, focus_areas, preferred_states,
                  target_sdgs, min_budget, max_budget, (embedding IS NOT NULL) AS has_embedding
             FROM csr_rulebooks WHERE id = %s""",
        (rulebook_id,),
    ).fetchone()
    if rb is None:
        raise NotFound(f"rulebook {rulebook_id} not found")
    has_embedding = rb.pop("has_embedding")

    ranked_rows = conn.execute(
        """SELECT m.project_id, m.title, m.ngo_name, p.state, e.sdgs,
                  ARRAY(SELECT g FROM unnest(e.sdgs) AS g WHERE g = ANY(r.target_sdgs) ORDER BY g)
                      AS shared_sdgs,
                  m.requested_amount, m.similarity, m.impact_norm, m.fraud_score, m.match_score
             FROM fn_match_projects(%(rb)s, %(k)s) m
             JOIN projects            p ON p.id = m.project_id
             JOIN project_extractions e ON e.project_id = m.project_id
             JOIN csr_rulebooks       r ON r.id = %(rb)s
            ORDER BY m.match_score DESC, m.project_id""",
        {"rb": rulebook_id, "k": TOP_K},
    ).fetchall()

    ranked = []
    for r in ranked_rows:
        contributions = {
            "similarity": round(MATCH_WEIGHTS["similarity"] * r["similarity"], 6),
            "impact": round(MATCH_WEIGHTS["impact"] * r["impact_norm"], 6),
            "trust": round(MATCH_WEIGHTS["trust"] * (1 - r["fraud_score"]), 6),
        }
        ranked.append({**shape(r), "contributions": contributions})
    ranked_ids = {r["projectId"] for r in ranked}

    # The same four filters fn_match_projects applies, evaluated per project so a
    # project that fell out can say which rule removed it.
    candidates = conn.execute(
        """SELECT p.id, p.title, n.name AS ngo_name, p.status::text AS status,
                  p.requested_amount, p.state,
                  (p.status = 'approved') AS status_ok,
                  (p.requested_amount BETWEEN r.min_budget AND r.max_budget) AS budget_ok,
                  COALESCE(cardinality(r.preferred_states) = 0
                           OR p.state = ANY(r.preferred_states), false) AS state_ok,
                  COALESCE(cardinality(r.target_sdgs) = 0
                           OR e.sdgs && r.target_sdgs, false) AS sdg_ok,
                  (e.embedding IS NOT NULL) AS project_embedded
             FROM csr_rulebooks r
            CROSS JOIN projects p
             JOIN ngos n ON n.id = p.ngo_id
             LEFT JOIN project_extractions e ON e.project_id = p.id
            WHERE r.id = %s
            ORDER BY p.id""",
        (rulebook_id,),
    ).fetchall()

    excluded = []
    for c in candidates:
        if c["id"] in ranked_ids:
            continue
        reasons: list[str] = []
        if not c["status_ok"]:
            reasons.append(f"Status is {c['status']}; only approved projects can be matched.")
        if not c["budget_ok"]:
            reasons.append(
                f"Asks for {inr(c['requested_amount'])}, outside the "
                f"{inr(rb['min_budget'])} to {inr(rb['max_budget'])} range."
            )
        if not c["state_ok"]:
            reasons.append(
                f"{c['state'] or 'Unknown state'} is not one of {' or '.join(rb['preferred_states'])}."
            )
        if not c["sdg_ok"]:
            plural = "s" if len(rb["target_sdgs"]) > 1 else ""
            reasons.append(
                f"No overlap with the target SDG{plural} ({', '.join(map(str, rb['target_sdgs']))})."
            )
        if not reasons and not c["project_embedded"]:
            reasons.append("No extraction embedding yet.")
        if not reasons and not has_embedding:
            reasons.append("This rulebook has no embedding yet, so nothing can be ranked.")
        if not reasons:
            reasons.append(f"Passed every filter but ranks below the top {TOP_K}.")
        excluded.append({
            "projectId": c["id"],
            "title": c["title"],
            "ngoName": c["ngo_name"],
            "status": c["status"],
            "requestedAmount": c["requested_amount"],
            "reasons": reasons,
        })

    return {"rulebook": _rulebook(rb), "ranked": ranked, "excluded": excluded}
