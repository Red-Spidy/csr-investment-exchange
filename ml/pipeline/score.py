"""Score projects in the database with the trained models, then let SQL grade them.

    make score    # every project, plus the company rulebooks' embeddings

For each project:
  1. BERT reads the proposal          -> project_extractions (+ MiniLM embedding)
  2. Isolation Forest reads the NGO's spending history -> fraud_scores
  3. XGBoost forecasts the impact     -> impact_predictions
  4. fn_grade_project() decides       -> risk_grades, and the project's status

The models only write evidence. The grade, the approval and every later money
movement happen in SQL. Rulebooks are embedded with the same MiniLM model as
projects: cosine similarity is only meaningful inside one vector space.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from fraud.model import MODEL_VERSION as FRAUD_VERSION
from fraud.model import FraudModel
from impact.model import ImpactModel
from nlp.reader import MODEL_VERSION as READER_VERSION
from nlp.reader import ProposalReader, Reading
from synth.catalog import SECTOR_PROFILE

ARTIFACTS = Path("ml/artifacts")
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"   # 384-dim, matches VECTOR(384)
NEUTRAL_ANOMALY = 0.5
NO_SPENDING_FLAG = "no spending history to check for anomalies"

# Metrics that start from nothing ("add 250 hectares"): the target IS the claim.
ZERO_BASELINE_METRICS = {m.name for p in SECTOR_PROFILE.values() for m in p.metrics if m.baseline_range == (0, 0)}

SDG_NAMES = {
    1: "No Poverty", 2: "Zero Hunger", 3: "Good Health and Well-being", 4: "Quality Education",
    5: "Gender Equality", 6: "Clean Water and Sanitation", 7: "Affordable and Clean Energy",
    8: "Decent Work and Economic Growth", 9: "Industry, Innovation and Infrastructure",
    10: "Reduced Inequalities", 11: "Sustainable Cities and Communities",
    12: "Responsible Consumption and Production", 13: "Climate Action", 14: "Life Below Water",
    15: "Life on Land", 16: "Peace, Justice and Strong Institutions", 17: "Partnerships for the Goals",
}

_SPENDING_COLUMNS = ["ngo_id", "fy", "total_spend", "admin_expense_ratio", "burn_rate_vs_schedule",
                     "category_mix_drift", "round_number_freq", "vendor_concentration",
                     "report_latency_days", "cost_per_beneficiary"]


# --------------------------------------------------------------------- mapping

def _value(reading: Reading, name: str):
    return reading.fields[name].value if name in reading.fields else None


def project_canonical_text(title: str, sector: str, reading: Reading, state: str | None) -> str:
    """What gets embedded for matching: the extracted structure, not the raw
    proposal, described in the same vocabulary as a company rulebook."""
    district = _value(reading, "district")
    parts = [title, sector.replace("_", " "), reading.goal,
             ", ".join(p for p in (district, state) if p),
             *(SDG_NAMES[g] for g in reading.sdgs if g in SDG_NAMES)]
    return " | ".join(p for p in parts if p)


def rulebook_canonical_text(requirement_text: str, focus_areas, preferred_states, target_sdgs) -> str:
    parts = [requirement_text, *(a.replace("_", " ") for a in focus_areas or []), *(preferred_states or []),
             *(SDG_NAMES[g] for g in sorted(target_sdgs or []) if g in SDG_NAMES)]
    return " | ".join(p for p in parts if p)


def to_pgvector(vector) -> str:
    return "[" + ",".join(f"{float(x):.6f}" for x in vector) + "]"


def extraction_row(project_id: int, reading: Reading, canonical: str, embedding) -> dict:
    beneficiaries = _value(reading, "beneficiaries")
    district = _value(reading, "district")
    return {
        "project_id": project_id,
        "goals": json.dumps([reading.goal] if reading.goal else []),
        "target_metric": json.dumps({"name": reading.metric_name, "unit": reading.metric_unit,
                                     "baseline": _value(reading, "baseline"), "target": _value(reading, "target")}),
        "beneficiaries": json.dumps({"count": beneficiaries, "group": None}) if beneficiaries is not None else None,
        "geography": json.dumps({"district": district}) if district else None,
        "budget_lines": "[]",
        "duration_months": _value(reading, "duration"),
        "sdgs": list(reading.sdgs),
        "sdg_confidence": json.dumps(reading.sdg_confidence),
        "red_flags": json.dumps(reading.red_flags),
        "canonical_text": canonical,
        "embedding": to_pgvector(embedding),
        "raw_response": json.dumps({
            "metric_confidence": reading.metric_confidence,
            "fields": {k: {"value": f.value, "text": f.text, "start": f.start, "end": f.end,
                           "confidence": f.confidence} for k, f in reading.fields.items()},
        }),
        "model_version": READER_VERSION,
        "prompt_version": "none",
    }


def impact_frame(project: dict, ngo: dict, reading: Reading, fraud_score: float) -> pd.DataFrame:
    """One row in the impact model's input shape, built only from what BERT
    read and what the database knows. A claim exists only when both ends of it
    were read -- or the metric starts from zero and the target alone is the claim."""
    baseline, target = _value(reading, "baseline"), _value(reading, "target")
    if reading.metric_name in ZERO_BASELINE_METRICS and target is not None:
        baseline = 0.0
    beneficiaries = _value(reading, "beneficiaries")
    nan = float("nan")
    return pd.DataFrame([{
        "project_id": project["id"],
        "sector": project["sector"],
        "metric_name": reading.metric_name,
        "metric_unit": reading.metric_unit,
        "baseline": nan if baseline is None else baseline,
        "target": nan if target is None else target,
        "states_baseline": baseline is not None and target is not None,
        "beneficiaries": nan if beneficiaries is None else beneficiaries,
        "states_beneficiaries": beneficiaries is not None,
        "requested_amount": float(project["requested_amount"]),
        "duration_months": int(project["duration_months"]),
        "num_phases": int(project["num_phases"]),
        "budget_lines": [],
        "states_budget_breakdown": False,
        "established_year": nan if ngo["established_year"] is None else float(ngo["established_year"]),
        "past_projects": float(ngo["past_projects"]),
        "past_delivery_rate": nan if ngo["past_delivery_rate"] is None else float(ngo["past_delivery_rate"]),
        "ngo_fraud_score": fraud_score,
    }])


def fraud_evidence(model: FraudModel | None, spending: pd.DataFrame, sector: str, ngo_id: int):
    """(anomaly_score, is_anomaly, red flag or None) for one NGO."""
    if spending.empty:
        return NEUTRAL_ANOMALY, False, NO_SPENDING_FLAG
    s = spending.assign(sector=sector)
    median = model.features.sector_cpb_median.get(sector, model.features.global_cpb_median)
    s["cost_per_beneficiary"] = s["cost_per_beneficiary"].fillna(median)
    row = model.score_ngos(s).set_index("ngo_id").loc[ngo_id]
    return float(row["anomaly_score"]), bool(row["is_anomaly"]), None


# --------------------------------------------------------------------- database

@dataclass
class Models:
    reader: ProposalReader
    fraud: FraudModel
    impact: ImpactModel
    embedder: object

    @classmethod
    def load(cls, artifacts: Path = ARTIFACTS) -> Models:
        from sentence_transformers import SentenceTransformer
        return cls(
            reader=ProposalReader.load(artifacts / "bert"),
            fraud=FraudModel.load(artifacts / "fraud_iforest.joblib"),
            impact=ImpactModel.load(artifacts / "impact_xgb.joblib"),
            embedder=SentenceTransformer(EMBEDDING_MODEL),
        )

    def embed(self, text: str) -> list[float]:
        return self.embedder.encode([text], normalize_embeddings=True, show_progress_bar=False)[0].tolist()


_UPSERT_EXTRACTION = """
INSERT INTO project_extractions
    (project_id, goals, target_metric, beneficiaries, geography, budget_lines, duration_months, sdgs,
     sdg_confidence, red_flags, canonical_text, embedding, raw_response, model_version, prompt_version)
VALUES (%(project_id)s, %(goals)s, %(target_metric)s, %(beneficiaries)s, %(geography)s, %(budget_lines)s,
        %(duration_months)s, %(sdgs)s, %(sdg_confidence)s, %(red_flags)s, %(canonical_text)s,
        %(embedding)s::vector, %(raw_response)s, %(model_version)s, %(prompt_version)s)
ON CONFLICT (project_id) DO UPDATE SET
    goals = EXCLUDED.goals, target_metric = EXCLUDED.target_metric, beneficiaries = EXCLUDED.beneficiaries,
    geography = EXCLUDED.geography, budget_lines = EXCLUDED.budget_lines,
    duration_months = EXCLUDED.duration_months, sdgs = EXCLUDED.sdgs, sdg_confidence = EXCLUDED.sdg_confidence,
    red_flags = EXCLUDED.red_flags, canonical_text = EXCLUDED.canonical_text, embedding = EXCLUDED.embedding,
    raw_response = EXCLUDED.raw_response, model_version = EXCLUDED.model_version,
    prompt_version = EXCLUDED.prompt_version, extracted_at = now()
"""

_UPSERT_FRAUD = """
INSERT INTO fraud_scores (project_id, ngo_id, anomaly_score, is_anomaly, model_version)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (project_id) DO UPDATE SET anomaly_score = EXCLUDED.anomaly_score, is_anomaly = EXCLUDED.is_anomaly,
    ngo_id = EXCLUDED.ngo_id, model_version = EXCLUDED.model_version, scored_at = now()
"""

_UPSERT_IMPACT = """
INSERT INTO impact_predictions (project_id, metric_name, metric_unit, predicted_value, ci_low, ci_high,
                                impact_norm, model_version)
VALUES (%(project_id)s, %(metric_name)s, %(metric_unit)s, %(predicted_value)s, %(ci_low)s, %(ci_high)s,
        %(impact_norm)s, %(model_version)s)
ON CONFLICT (project_id) DO UPDATE SET metric_name = EXCLUDED.metric_name, metric_unit = EXCLUDED.metric_unit,
    predicted_value = EXCLUDED.predicted_value, ci_low = EXCLUDED.ci_low, ci_high = EXCLUDED.ci_high,
    impact_norm = EXCLUDED.impact_norm, model_version = EXCLUDED.model_version, predicted_at = now()
"""


def _rows(cur, sql: str, params=()) -> list[dict]:
    cur.execute(sql, params)
    names = [d.name for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def _plain(v):
    """psycopg returns NUMERIC as Decimal; the models want floats."""
    return float(v) if hasattr(v, "as_tuple") else v


def score_project(conn, models: Models, project_id: int) -> dict:
    """Score one project and grade it, in one transaction."""
    with conn.cursor() as cur:
        [project] = _rows(cur, """SELECT id, ngo_id, title, proposal_text, sector, state, requested_amount,
                                         duration_months, num_phases FROM projects WHERE id = %s""", (project_id,))
        [ngo] = _rows(cur, """SELECT n.id, n.established_year,
                                     (SELECT count(*) FROM commitments c JOIN projects p ON p.id = c.project_id
                                       WHERE p.ngo_id = n.id AND c.status = 'completed') AS past_projects,
                                     fn_ngo_track_record(n.id) AS track_record
                                FROM ngos n WHERE n.id = %s""", (project["ngo_id"],))
        ngo["past_delivery_rate"] = _plain(ngo["track_record"]) if ngo["past_projects"] else None
        spending = pd.DataFrame(_rows(cur, f"SELECT {', '.join(_SPENDING_COLUMNS)} FROM ngo_spending_history "
                                           "WHERE ngo_id = %s ORDER BY fy", (project["ngo_id"],)),
                                columns=_SPENDING_COLUMNS)
        spending = spending.apply(lambda col: col.map(_plain))

        reading = models.reader.read(project["proposal_text"])
        anomaly, flagged, note = fraud_evidence(models.fraud, spending, project["sector"], project["ngo_id"])
        if note:
            reading = Reading(**{**reading.__dict__, "red_flags": [*reading.red_flags, note]})
        canonical = project_canonical_text(project["title"], project["sector"], reading, project["state"])
        cur.execute(_UPSERT_EXTRACTION, extraction_row(project_id, reading, canonical, models.embed(canonical)))
        cur.execute(_UPSERT_FRAUD, (project_id, project["ngo_id"], anomaly, flagged, FRAUD_VERSION))

        forecast = models.impact.forecast(impact_frame(project, ngo, reading, anomaly)).iloc[0].to_dict()
        cur.execute(_UPSERT_IMPACT, forecast)

        cur.execute("SELECT fn_grade_project(%s)::text", (project_id,))
        grade = cur.fetchone()[0]
        [after] = _rows(cur, """SELECT p.status::text AS status, rg.composite_score, rg.decision::text AS decision
                                  FROM projects p JOIN risk_grades rg ON rg.project_id = p.id
                                 WHERE p.id = %s""", (project_id,))
    conn.commit()
    return {"project_id": project_id, "title": project["title"], "grade": grade, **after,
            "composite": _plain(after["composite_score"]), "sdgs": reading.sdgs, "anomaly": anomaly,
            "fraud_flag": flagged, "forecast": forecast, "red_flags": reading.red_flags}


def embed_rulebooks(conn, models: Models) -> int:
    with conn.cursor() as cur:
        rulebooks = _rows(cur, "SELECT id, requirement_text, focus_areas, preferred_states, target_sdgs FROM csr_rulebooks")
        for r in rulebooks:
            text = rulebook_canonical_text(r["requirement_text"], r["focus_areas"], r["preferred_states"],
                                           r["target_sdgs"])
            cur.execute("UPDATE csr_rulebooks SET embedding = %s::vector WHERE id = %s",
                        (to_pgvector(models.embed(text)), r["id"]))
    conn.commit()
    return len(rulebooks)


def main() -> None:
    import psycopg

    from textgen.generate import read_env_file

    env = {**(read_env_file(Path(".env")) if Path(".env").exists() else {}), **os.environ}
    dsn = env.get("DATABASE_URL", "postgresql://csr:csr@localhost:5433/csr_exchange")
    models = Models.load()
    with psycopg.connect(dsn) as conn:
        print(f"embedded {embed_rulebooks(conn, models)} rulebooks")
        with conn.cursor() as cur:
            ids = [r[0] for r in cur.execute("SELECT id FROM projects ORDER BY id").fetchall()]
        print(f"{'id':>3}  {'grade':5} {'composite':>9}  {'status':9} {'fraud':>6}  forecast")
        for pid in ids:
            r = score_project(conn, models, pid)
            f = r["forecast"]
            flag = " (flagged)" if r["fraud_flag"] else ""
            print(f"{pid:>3}  {r['grade']:5} {r['composite']:>9.4f}  {r['status']:9} {r['anomaly']:>6.2f}  "
                  f"{f['predicted_value']:+.2f} [{f['ci_low']:+.2f}, {f['ci_high']:+.2f}] {f['metric_unit']}{flag}"
                  f"  | {r['title'][:40]}")


if __name__ == "__main__":
    main()
