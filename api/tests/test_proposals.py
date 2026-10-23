"""Submitting a proposal, adding a CSR rulebook, and reviewing a flagged project.

Scoring and embedding are injected, so these tests check the routes and the
database without loading the trained models; ml/tests/test_pipeline_db.py runs
the real models against a real database."""

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import create_app

PROPOSAL = {
    "ngoId": 1, "title": "Reading rooms, Barmer", "sector": "education", "state": "Rajasthan",
    "requestedAmount": 900000, "durationMonths": 12, "numPhases": 2,
    "proposalText": "Vidya Foundation will add reading rooms to 12 schools in Barmer district, Rajasthan, "
                    "and raise average reading scores from 40% to 52% over 12 months. We request Rs 9 lakh.",
}
RULEBOOK = {"companyId": 1, "requirementText": "Fund girls' secondary education in rural Bihar.",
            "focusAreas": ["education"], "preferredStates": ["Bihar"], "targetSdgs": [4, 5],
            "minBudget": 500000, "maxBudget": 3000000}


class FakeScorer:
    def __init__(self, fail: str | None = None):
        self.fail, self.calls = fail, []

    def score(self, conn, project_id):
        if self.fail:
            raise RuntimeError(self.fail)
        self.calls.append(project_id)
        return {"project_id": project_id, "grade": "B", "composite": 0.8, "decision": "approved",
                "status": "approved", "sdgs": [4], "metric_name": "attendance_rate",
                "fields": {"baseline": 40, "target": 52, "district": "Barmer"},
                "red_flags": ["no beneficiary count stated"], "anomaly": 0.2, "fraud_flag": False,
                "forecast": {"metric_name": "attendance_rate", "metric_unit": "percentage_points",
                             "predicted_value": 4.2, "ci_low": 2.6, "ci_high": 6.9}}

    def embed_rulebook(self, requirement_text, focus_areas, preferred_states, target_sdgs):
        if self.fail:
            raise RuntimeError(self.fail)
        return [1.0] + [0.0] * 383


@pytest.fixture
def make_client(fresh_db):
    opened = []

    def make(scorer):
        client = TestClient(create_app(fresh_db, allow_reset=False, scorer=scorer))
        client.__enter__()
        opened.append(client)
        return client

    yield make
    for client in opened:
        client.__exit__(None, None, None)


def get(client, path):
    r = client.get(f"/api{path}")
    assert r.status_code == 200, r.text
    return r.json()


def post(client, path, body):
    r = client.post(f"/api{path}", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_submitted_proposal_is_saved_pending_then_scored(make_client):
    scorer = FakeScorer()
    client = make_client(scorer)
    r = post(client, "/projects", PROPOSAL)
    assert r["ok"] and scorer.calls == [r["projectId"]]
    project = get(client, f"/projects/{r['projectId']}")["project"]
    assert project["title"] == PROPOSAL["title"] and project["status"] == "pending"   # the fake writes nothing
    by = [e["by"] for e in r["effects"]]
    assert by == ["projects", "BERT", "Isolation Forest", "XGBoost", "fn_grade_project"]
    text = " ".join(e["text"] for e in r["effects"])
    assert "Grade B" in text and "+4.2" in text and "no beneficiary count stated" in text


def test_a_proposal_that_cannot_be_scored_is_still_saved_and_says_why(make_client):
    client = make_client(FakeScorer(fail="models not trained"))
    r = post(client, "/projects", PROPOSAL)
    assert r["ok"]
    assert get(client, f"/projects/{r['projectId']}")["project"]["status"] == "pending"
    assert any("Not scored" in e["text"] and "models not trained" in e["text"] for e in r["effects"])


def test_a_proposal_for_an_unknown_ngo_is_refused_by_the_database(make_client):
    scorer = FakeScorer()
    r = post(make_client(scorer), "/projects", {**PROPOSAL, "ngoId": 9999})
    assert r["ok"] is False and r["kind"] == "sql" and scorer.calls == []


@pytest.mark.parametrize("change", [{"sector": "space"}, {"proposalText": "too short"},
                                    {"requestedAmount": 0}, {"durationMonths": 0}])
def test_malformed_proposals_are_rejected_before_the_database(make_client, change):
    assert make_client(FakeScorer()).post("/api/projects", json={**PROPOSAL, **change}).status_code == 422


def test_a_new_rulebook_is_saved_with_its_embedding(make_client, fresh_db):
    r = post(make_client(FakeScorer()), "/rulebooks", RULEBOOK)
    assert r["ok"] and r["rulebookId"]
    with psycopg.connect(fresh_db) as conn:
        fy, embedded, sdgs = conn.execute(
            "SELECT r.fy, r.embedding IS NOT NULL, r.target_sdgs FROM csr_rulebooks r WHERE r.id = %s",
            (r["rulebookId"],)).fetchone()
        company_fy, = conn.execute("SELECT fy FROM companies WHERE id = 1").fetchone()
    assert (fy, embedded, sdgs) == (company_fy, True, [4, 5])


def test_a_rulebook_that_cannot_be_embedded_is_saved_and_says_matching_will_skip_it(make_client):
    r = post(make_client(FakeScorer(fail="no embedding model")), "/rulebooks", RULEBOOK)
    assert r["ok"] and any("no embedding model" in e["text"] for e in r["effects"])


def test_the_database_refuses_a_budget_range_that_is_upside_down(make_client):
    r = post(make_client(FakeScorer()), "/rulebooks", {**RULEBOOK, "minBudget": 5000000, "maxBudget": 1000000})
    assert r["ok"] is False and r["kind"] == "sql"


def test_a_reviewer_approves_a_flagged_project(make_client):
    client = make_client(FakeScorer())
    assert get(client, "/projects/7")["project"]["status"] == "flagged"      # flagged in the seed
    r = post(client, "/projects/7/review", {"approve": True, "note": "budget breakdown received"})
    assert r["ok"] and get(client, "/projects/7")["project"]["status"] == "approved"
    assert any(e["by"] == "fn_review_project" and "approved" in e["text"] for e in r["effects"])


def test_a_reviewer_rejects_a_flagged_project(make_client):
    client = make_client(FakeScorer())
    r = post(client, "/projects/8/review", {"approve": False, "note": "single supplier, round invoices"})
    assert r["ok"] and get(client, "/projects/8")["project"]["status"] == "rejected"


def test_only_a_flagged_project_can_be_reviewed(make_client):
    r = post(make_client(FakeScorer()), "/projects/2/review", {"approve": True})
    assert r["ok"] is False and r["kind"] == "sql" and "only a flagged project" in r["error"]


def test_the_real_models_score_a_submission_end_to_end(fresh_db):
    from app.scoring import ML
    if not (ML / "artifacts" / "bert" / "reader.json").exists():
        pytest.skip("trained models not found: run make train and make train-bert")
    with TestClient(create_app(fresh_db, allow_reset=False)) as client:
        r = post(client, "/projects", PROPOSAL)
        assert r["ok"], r
        detail = get(client, f"/projects/{r['projectId']}")
    assert detail["risk"] is not None and detail["extraction"]["modelVersion"] == "bert-v1"
    assert detail["project"]["status"] == detail["risk"]["decision"]
    assert [e["by"] for e in r["effects"]][-1] == "fn_grade_project"


def test_the_receipt_says_what_a_forecast_without_units_means(make_client):
    class NoBaseline(FakeScorer):
        def score(self, conn, project_id):
            out = super().score(conn, project_id)
            out["fields"] = {"target": 52, "amount": 900000, "duration": 12}
            out["forecast"] = {"metric_name": "outcome_score", "metric_unit": "normalised_0_1",
                               "predicted_value": 0.68, "ci_low": 0.38, "ci_high": 0.94}
            return out
    r = post(make_client(NoBaseline()), "/projects", PROPOSAL)
    text = " ".join(e["text"] for e in r["effects"])
    assert "0.68 of the claimed improvement" in text and "₹9,00,000" in text and "12 months" in text
    assert "normalised" not in text


class CountingScorer(FakeScorer):
    def __init__(self):
        super().__init__()
        self.database_scored = 0

    def score_database(self, conn):
        self.database_scored += 1
        return {"projects": 8, "rulebooks": 3}


def test_reset_can_rescore_so_the_demo_keeps_real_model_output(fresh_db):
    scorer = CountingScorer()
    with TestClient(create_app(fresh_db, allow_reset=True, scorer=scorer)) as client:
        assert post(client, "/reset", {"score": True}) == {"ok": True, "scored": {"projects": 8, "rulebooks": 3}}
        assert scorer.database_scored == 1
        # A plain reset, as the parity check uses, leaves the seed exactly as written.
        assert post(client, "/reset", {}) == {"ok": True}
        assert scorer.database_scored == 1
