"""Write side. Money moves only through fn_commit_funds, fn_terminate_commitment and
the milestone triggers; this module calls them and then reads back what they did, so
the "receipt" the UI shows is the database's own record and not a guess.

Every function runs inside the caller's transaction. A raised SQL error rolls the
whole call back, which is the ROLLBACK the receipt describes."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

import psycopg
from psycopg import Connection

from .reads import NotFound
from .util import inr, num


class RuleError(Exception):
    """A rule this layer enforces before the database is asked to do anything."""


@dataclass
class Written:
    effects: list[dict[str, str]] = field(default_factory=list)
    commitment_id: int | None = None
    project_id: int | None = None
    rulebook_id: int | None = None

    def add(self, by: str, text: str) -> None:
        self.effects.append({"by": by, "text": text})


def _row(conn: Connection, sql: str, params: tuple[Any, ...]) -> dict[str, Any]:
    row = conn.execute(sql, params).fetchone()
    assert row is not None, sql
    return row


# ---------------------------------------------------------------- fn_commit_funds

def commit_funds(
    conn: Connection, company_id: int, project_id: int, match_id: int | None, amount: Decimal | None,
) -> Written:
    new_id = _row(
        conn,
        "SELECT fn_commit_funds(%s::bigint, %s::bigint, %s::bigint, %s::numeric) AS id",
        (company_id, project_id, match_id, amount),
    )["id"]
    cm = _row(conn, "SELECT amount, num_phases FROM commitments WHERE id = %s", (new_id,))
    co = _row(
        conn,
        "SELECT committed_budget, mandated_csr_budget FROM companies WHERE id = %s",
        (company_id,),
    )

    out = Written(commitment_id=new_id)
    out.add("fn_commit_funds", f"Inserted commitment {new_id} for {inr(cm['amount'])}.")
    out.add(
        "trg_generate_phase_schedule",
        f"Split the money into {cm['num_phases']} phases and created {cm['num_phases']} "
        "milestones, one gating each phase.",
    )
    out.add("fund_transactions", f"Ledger row appended: lock {inr(cm['amount'])}.")
    out.add(
        "fn_commit_funds",
        f"Company budget used is now {inr(co['committed_budget'])} of "
        f"{inr(co['mandated_csr_budget'])}. Project moved to matched.",
    )
    return out


# ---------------------------------------------------------------- milestones

def _milestone(conn: Connection, milestone_id: int) -> dict[str, Any]:
    row = conn.execute(
        """SELECT id, project_id, commitment_id, phase_no, verification_status::text AS status
             FROM milestones WHERE id = %s FOR UPDATE""",
        (milestone_id,),
    ).fetchone()
    if row is None:
        raise NotFound(f"milestone {milestone_id} not found")
    return row


def submit_evidence(conn: Connection, milestone_id: int, metric: float) -> Written:
    ms = _milestone(conn, milestone_id)
    if ms["status"] != "pending":
        raise RuleError(
            f"Milestone {ms['id']} is already {ms['status']}; evidence can only be submitted once."
        )
    conn.execute(
        """UPDATE milestones
              SET verification_status = 'submitted', reported_at = now(), reported_metric = %s,
                  evidence_uri = %s
            WHERE id = %s""",
        (Decimal(str(metric)), f"evidence/commitment-{ms['commitment_id']}-phase-{ms['phase_no']}.pdf",
         ms["id"]),
    )
    out = Written()
    out.add("milestones", f"Phase {ms['phase_no']} evidence recorded, reported metric {num(metric)}.")
    out.add(
        "trg_release_next_phase",
        "Did not fire. It only fires when a reviewer marks a milestone verified, so no money moved.",
    )
    return out


def _state_of(conn: Connection, ms: dict[str, Any]) -> dict[str, Any]:
    return _row(
        conn,
        """SELECT fp.status::text AS phase, fp.amount AS phase_amount,
                  c.status::text AS commitment, p.status::text AS project
             FROM fund_phases fp
             JOIN commitments c ON c.id = fp.commitment_id
             JOIN projects    p ON p.id = c.project_id
            WHERE fp.commitment_id = %s AND fp.phase_no = %s""",
        (ms["commitment_id"], ms["phase_no"]),
    )


def verify_milestone(conn: Connection, milestone_id: int, reviewer: str) -> Written:
    ms = _milestone(conn, milestone_id)
    if ms["status"] != "submitted":
        raise RuleError(f"Milestone {ms['id']} has no submitted evidence to verify.")
    before = _state_of(conn, ms)

    # The trigger trg_release_next_phase fires on this UPDATE; nothing else moves money.
    conn.execute(
        """UPDATE milestones
              SET verification_status = 'verified', verified_by = %s, verified_at = now()
            WHERE id = %s""",
        (reviewer, ms["id"]),
    )
    after = _state_of(conn, ms)

    out = Written()
    out.add("milestones", f"Phase {ms['phase_no']} marked verified by {reviewer}.")
    if before["phase"] != "locked":
        out.add(
            "trg_release_next_phase",
            f"Phase {ms['phase_no']} is already {before['phase']}. Nothing paid twice.",
        )
        return out

    out.add(
        "trg_release_next_phase",
        f"Released phase {ms['phase_no']}, {inr(after['phase_amount'])}. Ledger row appended.",
    )
    if after["commitment"] == "completed":
        out.add("trg_release_next_phase", "No locked phases left. Commitment completed and project closed.")
    elif before["project"] != "active" and after["project"] == "active":
        out.add("trg_release_next_phase", "First release made. Project is now active.")
    return out


def fail_milestone(conn: Connection, milestone_id: int, reviewer: str) -> Written:
    ms = _milestone(conn, milestone_id)
    if ms["status"] != "submitted":
        raise RuleError(f"Milestone {ms['id']} has no submitted evidence to fail.")
    before = _state_of(conn, ms)

    conn.execute(
        """UPDATE milestones
              SET verification_status = 'failed', verified_by = %s, verified_at = now()
            WHERE id = %s""",
        (reviewer, ms["id"]),
    )

    out = Written()
    out.add("milestones", f"Phase {ms['phase_no']} marked failed by {reviewer}.")
    if before["phase"] == "locked":
        out.add(
            "trg_hold_on_failed_verification",
            f"Held phase {ms['phase_no']}, {inr(before['phase_amount'])}. "
            "The money stays locked, it is not released.",
        )
    out.add("trg_hold_on_failed_verification", "Project flagged for review.")
    return out


# ---------------------------------------------------------------- fn_terminate_commitment

def terminate_commitment(conn: Connection, commitment_id: int, reason: str, reviewer: str) -> Written:
    """End an active commitment: unreleased phases are terminated and refunded."""
    if conn.execute("SELECT 1 FROM commitments WHERE id = %s", (commitment_id,)).fetchone() is None:
        raise NotFound(f"commitment {commitment_id} not found")
    refunded = _row(
        conn,
        "SELECT fn_terminate_commitment(%s::bigint, %s::text, %s::text) AS refunded",
        (commitment_id, reason, reviewer),
    )["refunded"]
    cm = _row(
        conn,
        """SELECT c.amount, co.committed_budget, co.mandated_csr_budget,
                  (SELECT count(*) FROM fund_phases fp
                    WHERE fp.commitment_id = c.id AND fp.status = 'terminated') AS terminated
             FROM commitments c JOIN companies co ON co.id = c.company_id
            WHERE c.id = %s""",
        (commitment_id,),
    )

    released = cm["amount"] - refunded
    n = cm["terminated"]
    out = Written(commitment_id=commitment_id)
    text = f"Terminated {n} unreleased phase{'' if n == 1 else 's'}, {inr(refunded)}."
    if released > 0:
        text += f" The {inr(released)} already released stays paid."
    out.add("fn_terminate_commitment", text)
    out.add(
        "fund_transactions",
        f"Ledger rows appended: terminate for {'the phase' if n == 1 else f'each of the {n} phases'}, "
        f"then refund {inr(refunded)}.",
    )
    out.add(
        "fn_terminate_commitment",
        f"Company budget used is now {inr(cm['committed_budget'])} of {inr(cm['mandated_csr_budget'])}. "
        "Commitment cancelled, project terminated.",
    )
    return out


# ---------------------------------------------------------------- monthly progress

def report_impact(conn: Connection, project_id: int, value: float) -> Written:
    # Serialise reporters on the project row so two of them cannot pick the same month.
    if conn.execute("SELECT 1 FROM projects WHERE id = %s FOR UPDATE", (project_id,)).fetchone() is None:
        raise NotFound(f"project {project_id} not found")
    cm = conn.execute(
        """SELECT company_id, status::text AS status FROM commitments WHERE project_id = %s
            ORDER BY (status = 'active') DESC, (status <> 'cancelled') DESC, id LIMIT 1""",
        (project_id,),
    ).fetchone()
    if cm is None:
        raise RuleError(
            f"Project {project_id} has no commitment, so there is no funded work to report on."
        )
    if cm["status"] == "cancelled":
        raise RuleError(
            f"Project {project_id} was terminated, so it has no funded work left to report on."
        )

    # The month after the latest report, or the current month for a first report.
    month = _row(
        conn,
        """SELECT COALESCE(
                    (SELECT date_trunc('month', max(period_month)) + interval '1 month'
                       FROM impact_reports WHERE project_id = %s),
                    date_trunc('month', now())
                  )::date AS month""",
        (project_id,),
    )["month"]
    conn.execute(
        "INSERT INTO impact_reports (project_id, period_month, metric_value) VALUES (%s, %s, %s)",
        (project_id, month, Decimal(str(value))),
    )

    out = Written()
    out.add("impact_reports", f"Recorded {num(value)} for {month:%Y-%m}.")
    row = conn.execute(
        """SELECT rolling_3mo_esg, cumulative_impact FROM company_esg_timeline
            WHERE company_id = %s AND month = %s""",
        (cm["company_id"], month),
    ).fetchone()
    if row:
        out.add(
            "company_esg_timeline",
            "The view recomputes on read. For that month the 3-month average is now "
            f"{row['rolling_3mo_esg']:.2f} and the running total {row['cumulative_impact']:.2f}.",
        )
    return out


# ---------------------------------------------------------------- the append-only ledger

def attempt_ledger_mutation(conn: Connection, op: Literal["UPDATE", "DELETE"], ledger_id: int) -> Written:
    """Try to rewrite a ledger row. Always rolled back: the point is to watch it refuse.

    A SQL error from trg_ledger_immutable propagates to the caller, which reports it.
    """
    try:
        if op == "UPDATE":
            cur = conn.execute("UPDATE fund_transactions SET note = note WHERE id = %s", (ledger_id,))
        else:
            cur = conn.execute("DELETE FROM fund_transactions WHERE id = %s", (ledger_id,))
        touched = cur.rowcount
    except psycopg.Error:
        conn.rollback()
        raise
    conn.rollback()
    if touched == 0:
        raise RuleError(f"{op} 0: no ledger row with id {ledger_id}, so the trigger never fires.")
    # The trigger should make this unreachable. If it is ever reached the change
    # has been rolled back above, and the response says so rather than pretending.
    out = Written()
    out.add("fund_transactions", f"{op} succeeded on row {ledger_id} and was rolled back by the API.")
    return out


# ---------------------------------------------------------------- proposals, rulebooks, review

def submit_proposal(conn: Connection, ngo_id: int, title: str, proposal_text: str, sector: str,
                    state: str | None, amount: Decimal, duration_months: int, num_phases: int) -> Written:
    """A new project starts pending; nothing about it is decided here."""
    row = _row(
        conn,
        """INSERT INTO projects (ngo_id, title, proposal_text, sector, state, requested_amount,
                                 duration_months, num_phases)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (ngo_id, title, proposal_text, sector, state, amount, duration_months, num_phases),
    )
    out = Written(project_id=row["id"])
    out.add("projects", f"Saved project {row['id']} as pending: {title}, {inr(float(amount))} "
                        f"over {duration_months} months.")
    return out


_UNITS = {"percentage_points": "points", "percent": "%", "percent_increase": "% higher",
          "hectares": "hectares", "tonnes_per_month": "tonnes a month"}


def _field_text(name: str, value: Any) -> str:
    if name == "amount":
        return f"amount {inr(float(value))}"
    if name == "duration":
        return f"duration {num(value)} months"
    return f"{name} {num(value) if isinstance(value, (int, float)) else value}"


def scoring_effects(r: dict[str, Any]) -> Written:
    """What each model found and what the grade decided, from ml/pipeline/score.py."""
    out = Written()
    fields = ", ".join(_field_text(k, v) for k, v in sorted(r["fields"].items()))
    flags = "; ".join(r["red_flags"]) or "none"
    out.add("BERT", f"SDGs {', '.join(map(str, r['sdgs']))}; outcome metric {r['metric_name'].replace('_', ' ')}; "
                    f"read {fields or 'no stated facts'}. Red flags: {flags}.")
    flag = "flagged for review" if r["fraud_flag"] else "not flagged"
    out.add("Isolation Forest", f"NGO spending anomaly {r['anomaly']:.2f} (percentile against training NGOs), {flag}.")
    f = r["forecast"]
    if f["metric_unit"] == "normalised_0_1":
        forecast = (f"Expects {f['predicted_value']:.2f} of the claimed improvement to be delivered, 80% interval "
                    f"[{f['ci_low']:.2f}, {f['ci_high']:.2f}]. No baseline and target were both read, so it "
                    "cannot be put in the proposal's own units.")
    else:
        unit = _UNITS.get(f["metric_unit"], f["metric_unit"].replace("_", " "))
        forecast = (f"Forecast {f['predicted_value']:+.2f} {unit} of {f['metric_name'].replace('_', ' ')}, "
                    f"80% interval [{f['ci_low']:+.2f}, {f['ci_high']:+.2f}].")
    out.add("XGBoost", forecast)
    verdict = "approved into the matching pool" if r["decision"] == "approved" else "sent to manual review"
    out.add("fn_grade_project", f"Grade {r['grade']} (composite {r['composite']:.4f}): {verdict}. "
                                f"Project status is now {r['status']}.")
    return out


def review_project(conn: Connection, project_id: int, approve: bool, reviewer: str, note: str | None) -> Written:
    """fn_review_project: a person settles what the grade routed to them."""
    decision = _row(conn, "SELECT fn_review_project(%s, %s, %s, %s)::text AS decision",
                    (project_id, approve, reviewer, note))["decision"]
    out = Written(project_id=project_id)
    reason = f": {note}" if note else ""
    out.add("fn_review_project", f"Project {project_id} {decision} by {reviewer}{reason}. Kept in "
                                 "project_reviews, so a later regrade will not overturn it.")
    if decision == "approved":
        out.add("projects", f"Project {project_id} is now in the matching pool.")
    return out


def create_rulebook(conn: Connection, company_id: int, requirement_text: str, focus_areas: list[str],
                    preferred_states: list[str], target_sdgs: list[int], min_budget: Decimal,
                    max_budget: Decimal) -> Written:
    company = conn.execute("SELECT name, fy FROM companies WHERE id = %s", (company_id,)).fetchone()
    if company is None:
        raise NotFound(f"company {company_id} not found")
    row = _row(
        conn,
        """INSERT INTO csr_rulebooks (company_id, fy, requirement_text, focus_areas, preferred_states,
                                      target_sdgs, min_budget, max_budget)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (company_id, company["fy"], requirement_text, focus_areas, preferred_states, target_sdgs,
         min_budget, max_budget),
    )
    out = Written(rulebook_id=row["id"])
    out.add("csr_rulebooks", f"Saved rulebook {row['id']} for {company['name']} ({company['fy']}), "
                             f"budget {inr(float(min_budget))} to {inr(float(max_budget))}.")
    return out


def store_rulebook_embedding(conn: Connection, rulebook_id: int, vector: list[float]) -> Written:
    text = "[" + ",".join(f"{x:.6f}" for x in vector) + "]"
    conn.execute("UPDATE csr_rulebooks SET embedding = %s::vector WHERE id = %s", (text, rulebook_id))
    out = Written(rulebook_id=rulebook_id)
    out.add("csr_rulebooks", f"Embedded rulebook {rulebook_id} with MiniLM, the same model as the projects, "
                             "so fn_match_projects can rank it now.")
    return out

