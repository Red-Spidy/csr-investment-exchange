"""The scoring pipeline end to end: real models, real Postgres, a database of
its own built from db/migrations and db/seed.sql. Skipped when Postgres or the
trained models are not available."""

import os
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ADMIN_URL = os.environ.get("TEST_ADMIN_URL", "postgresql://csr:csr@localhost:5433/postgres")


@pytest.fixture(scope="module")
def scored_db():
    psycopg = pytest.importorskip("psycopg")
    from psycopg.conninfo import make_conninfo

    artifacts = ROOT / "ml" / "artifacts"
    if not (artifacts / "bert" / "reader.json").exists() or not (artifacts / "impact_xgb.joblib").exists():
        pytest.skip("trained models not found: run make train and make train-bert")
    try:
        admin = psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=5)
    except psycopg.OperationalError as err:
        pytest.skip(f"no Postgres at TEST_ADMIN_URL ({err})")

    from pipeline.score import Models, embed_rulebooks, score_project

    name = f"csr_ml_{uuid.uuid4().hex[:10]}"
    admin.execute(f"CREATE DATABASE {name}")
    try:
        with psycopg.connect(make_conninfo(ADMIN_URL, dbname=name)) as conn:
            for f in sorted((ROOT / "db" / "migrations").glob("*.sql")):
                conn.execute(f.read_text())
            conn.execute((ROOT / "db" / "seed.sql").read_text())
            conn.commit()
            models = Models.load(artifacts)
            embed_rulebooks(conn, models)
            results = {pid: score_project(conn, models, pid) for pid in (1, 2, 8)}
            yield conn, results
    finally:
        admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        admin.close()


def _one(conn, sql, *params):
    return conn.execute(sql, params).fetchone()


def test_every_model_writes_its_evidence(scored_db):
    conn, _ = scored_db
    for pid in (1, 2, 8):
        assert _one(conn, "SELECT model_version, embedding IS NOT NULL FROM project_extractions WHERE project_id = %s", pid) == ("bert-v1", True)
        assert _one(conn, "SELECT model_version FROM fraud_scores WHERE project_id = %s", pid) == ("iforest-v1",)
        low, value, high = _one(conn, "SELECT ci_low, predicted_value, ci_high FROM impact_predictions WHERE project_id = %s", pid)
        assert low <= value <= high


def test_the_seeded_fraud_is_caught_and_sent_to_review(scored_db):
    # NGO 4's FY23-24 spending in db/seed.sql carries the planted anomaly.
    conn, results = scored_db
    assert results[8]["fraud_flag"] is True
    assert _one(conn, "SELECT status::text, decision::text FROM projects p JOIN risk_grades r ON r.project_id = p.id WHERE p.id = 8") == ("flagged", "flagged")


def test_an_unfunded_project_takes_the_grades_decision_and_a_funded_one_keeps_its_status(scored_db):
    conn, results = scored_db
    status, decision = _one(conn, "SELECT p.status::text, r.decision::text FROM projects p JOIN risk_grades r ON r.project_id = p.id WHERE p.id = 2")
    assert status == decision
    assert results[1]["status"] == "active"           # project 1 is funded in the seed


def test_rulebooks_and_projects_share_one_vector_space(scored_db):
    conn, _ = scored_db
    assert _one(conn, "SELECT count(*) FROM csr_rulebooks WHERE embedding IS NOT NULL") == (3,)
    # The education rulebook is semantically closest to an education project, not a sanitation one.
    sim = dict(conn.execute("""SELECT e.project_id, 1 - (e.embedding <=> r.embedding)
                                 FROM project_extractions e, csr_rulebooks r
                                WHERE r.id = 1 AND e.project_id IN (2, 8)""").fetchall())
    assert sim[2] > sim[8]
