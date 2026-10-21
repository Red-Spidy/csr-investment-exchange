"""Write routes. Each test gets its own copy of the seeded database."""

import pytest
from fastapi.testclient import TestClient


def get(client: TestClient, path: str):
    r = client.get(f"/api{path}")
    assert r.status_code == 200, r.text
    return r.json()


def post(client: TestClient, path: str, body: dict | None = None):
    r = client.post(f"/api{path}", json=body or {})
    assert r.status_code == 200, r.text
    return r.json()


def commit(client: TestClient, company: int, project: int, amount: float | None = None):
    body = {"companyId": company, "projectId": project}
    if amount is not None:
        body["amount"] = amount
    return post(client, "/commitments", body)


def milestone(client: TestClient, commitment_id: int, phase_no: int) -> dict:
    (cm,) = [c for c in get(client, "/commitments") if c["commitment"]["id"] == commitment_id]
    return next(m for m in cm["milestones"] if m["phaseNo"] == phase_no)


def phase_status(client: TestClient, commitment_id: int, phase_no: int) -> str:
    (cm,) = [c for c in get(client, "/commitments") if c["commitment"]["id"] == commitment_id]
    return next(p for p in cm["phases"] if p["phaseNo"] == phase_no)["status"]


def project_status(client: TestClient, project_id: int) -> str:
    return next(r for r in get(client, "/scorecard") if r["projectId"] == project_id)["status"]


# ---------------------------------------------------------------- fn_commit_funds

def test_commit_locks_funds_and_generates_the_schedule(client: TestClient):
    res = commit(client, 2, 3)
    assert res["ok"] is True and res["commitmentId"] == 2
    assert [e["by"] for e in res["effects"]] == [
        "fn_commit_funds", "trg_generate_phase_schedule", "fund_transactions", "fn_commit_funds",
    ]
    assert "₹32,00,000" in res["effects"][0]["text"] and "4 phases" in res["effects"][1]["text"]

    kalpataru = get(client, "/companies")[1]
    assert kalpataru["committedBudget"] == 3_200_000
    assert project_status(client, 3) == "matched"
    assert get(client, "/ledger")[-1]["type"] == "lock"
    (cm,) = [c for c in get(client, "/commitments") if c["commitment"]["id"] == 2]
    assert [p["amount"] for p in cm["phases"]] == [800_000] * 4
    assert [m["verification"] for m in cm["milestones"]] == ["pending"] * 4


def test_the_rounding_remainder_lands_on_the_last_phase(client: TestClient):
    commit(client, 2, 2, 1_000_000)
    (cm,) = [c for c in get(client, "/commitments") if c["commitment"]["id"] == 2]
    amounts = [p["amount"] for p in cm["phases"]]
    assert amounts == [333_333.33, 333_333.33, 333_333.34]


@pytest.mark.parametrize(
    ("company", "project", "message"),
    [
        (1, 1, "project 1 is active, only approved projects can be funded"),
        (2, 7, "project 7 is flagged, only approved projects can be funded"),
        (3, 3, "company 3 has 2400000.00 remaining, cannot commit 3200000.00"),
        (99, 2, "company 99 not found"),
        (1, 99, "project 99 not found"),
    ],
)
def test_the_database_refuses_and_nothing_changes(client: TestClient, company, project, message):
    before = (get(client, "/companies"), get(client, "/ledger"), get(client, "/commitments"))
    res = commit(client, company, project)
    assert res == {"ok": False, "kind": "sql", "error": message, "code": "P0001"}
    assert (get(client, "/companies"), get(client, "/ledger"), get(client, "/commitments")) == before


def test_bad_requests_are_422(client: TestClient):
    assert client.post("/api/commitments", json={"companyId": 0, "projectId": 1}).status_code == 422
    assert client.post("/api/commitments", json={"companyId": 1, "projectId": 2, "amount": -5}).status_code == 422
    assert client.post("/api/commitments", json={"companyId": 1}).status_code == 422


# ---------------------------------------------------------------- milestones and triggers

def test_evidence_alone_moves_no_money(client: TestClient):
    res = post(client, "/milestones/2/evidence", {"metric": 4.2})
    assert res["ok"] is True and res["effects"][1]["by"] == "trg_release_next_phase"
    assert "no money moved" in res["effects"][1]["text"]

    m = milestone(client, 1, 2)
    assert (m["verification"], m["reportedMetric"]) == ("submitted", 4.2)
    assert m["evidenceUri"] == "evidence/commitment-1-phase-2.pdf"
    assert phase_status(client, 1, 2) == "locked"
    assert len(get(client, "/ledger")) == 2


def test_evidence_can_only_be_submitted_once(client: TestClient):
    post(client, "/milestones/2/evidence", {"metric": 4.2})
    res = post(client, "/milestones/2/evidence", {"metric": 9})
    assert res == {"ok": False, "kind": "rule",
                   "error": "Milestone 2 is already submitted; evidence can only be submitted once."}


def test_verifying_releases_the_phase_through_the_trigger(client: TestClient):
    post(client, "/milestones/2/evidence", {"metric": 4.2})
    res = post(client, "/milestones/2/verify")
    assert res["ok"] is True
    assert [e["by"] for e in res["effects"]] == ["milestones", "trg_release_next_phase"]
    assert "Released phase 2, ₹8,00,000." in res["effects"][1]["text"]

    assert phase_status(client, 1, 2) == "released"
    last = get(client, "/ledger")[-1]
    assert (last["type"], last["amount"]) == ("release", 800_000)
    assert milestone(client, 1, 2)["verifiedBy"] == "Reviewer"
    assert [a["action"] for a in get(client, "/audit")][-1] == "phase_released"


def test_no_evidence_no_release(client: TestClient):
    res = post(client, "/milestones/3/verify")
    assert res == {"ok": False, "kind": "rule", "error": "Milestone 3 has no submitted evidence to verify."}
    assert phase_status(client, 1, 3) == "locked"
    assert milestone(client, 1, 3)["verification"] == "pending"
    assert len(get(client, "/ledger")) == 2


def test_a_verified_milestone_cannot_be_verified_again(client: TestClient):
    res = post(client, "/milestones/1/verify")      # phase 1 was verified by the seed
    assert res["ok"] is False and res["kind"] == "rule"


def test_the_last_release_completes_the_commitment_and_closes_the_project(client: TestClient):
    for ms in (2, 3):
        post(client, f"/milestones/{ms}/evidence", {"metric": 5})
        res = post(client, f"/milestones/{ms}/verify")
    assert res["effects"][-1]["text"] == "No locked phases left. Commitment completed and project closed."
    (cm,) = get(client, "/commitments")
    assert cm["commitment"]["status"] == "completed"
    assert project_status(client, 1) == "closed"


def test_a_failed_verification_holds_the_phase_and_flags_the_project(client: TestClient):
    post(client, "/milestones/2/evidence", {"metric": 0.5})
    res = post(client, "/milestones/2/fail")
    assert res["ok"] is True
    assert "Held phase 2, ₹8,00,000." in res["effects"][1]["text"]

    assert phase_status(client, 1, 2) == "held"
    assert project_status(client, 1) == "flagged"
    last = get(client, "/ledger")[-1]
    assert (last["type"], last["amount"]) == ("hold", 800_000)
    assert post(client, "/milestones/2/verify")["ok"] is False
    assert post(client, "/milestones/2/fail")["ok"] is False


def test_unknown_milestone_is_404(client: TestClient):
    assert client.post("/api/milestones/999/verify").status_code == 404
    assert client.post("/api/milestones/999/evidence", json={"metric": 1}).status_code == 404


# ---------------------------------------------------------------- fn_terminate_commitment

def hold_phase_2(client: TestClient):
    post(client, "/milestones/2/evidence", {"metric": 0.5})
    assert post(client, "/milestones/2/fail")["ok"] is True


def test_terminating_a_held_commitment_refunds_what_was_not_released(client: TestClient):
    hold_phase_2(client)
    res = post(client, "/commitments/1/terminate", {"reason": "Phase 2 failed verification"})
    assert res["ok"] is True and res["commitmentId"] == 1
    assert [e["by"] for e in res["effects"]] == [
        "fn_terminate_commitment", "fund_transactions", "fn_terminate_commitment",
    ]
    assert res["effects"][0]["text"] == (
        "Terminated 2 unreleased phases, ₹16,00,000. The ₹8,00,000 already released stays paid.")
    assert res["effects"][1]["text"] == (
        "Ledger rows appended: terminate for each of the 2 phases, then refund ₹16,00,000.")
    assert res["effects"][2]["text"] == (
        "Company budget used is now ₹8,00,000 of ₹90,00,000. Commitment cancelled, project terminated.")

    (cm,) = get(client, "/commitments")
    assert cm["commitment"]["status"] == "cancelled"
    assert [p["status"] for p in cm["phases"]] == ["released", "terminated", "terminated"]
    assert project_status(client, 1) == "terminated"
    assert get(client, "/companies")[0]["committedBudget"] == 800_000

    tail = get(client, "/ledger")[-3:]
    assert [(t["type"], t["amount"]) for t in tail] == [
        ("terminate", 800_000), ("terminate", 800_000), ("refund", 1_600_000)]
    assert tail[0]["note"] == "phase 2 terminated: Phase 2 failed verification"
    assert tail[2]["phaseId"] is None

    audit = get(client, "/audit")[-1]
    assert (audit["entity"], audit["entityId"], audit["action"]) == ("commitment", 1, "commitment_terminated")
    assert audit["detail"] == {"reason": "Phase 2 failed verification", "by": "Reviewer",
                               "released": 800_000, "refunded": 1_600_000}


def test_the_refund_is_spendable_and_the_terminated_project_is_not_fundable(client: TestClient):
    post(client, "/commitments/1/terminate", {"reason": "NGO withdrew"})     # nothing released was phase 1
    assert get(client, "/companies")[0]["committedBudget"] == 800_000
    assert commit(client, 1, 2)["ok"] is True                              # project 2 is approved
    res = commit(client, 1, 1)
    assert res["ok"] is False and res["error"] == "project 1 is terminated, only approved projects can be funded"


def test_a_terminated_projects_leaderboard_funding_is_only_what_was_released(client: TestClient):
    post(client, "/commitments/1/terminate", {"reason": "NGO withdrew"})
    ngo1 = next(r for r in get(client, "/leaderboard") if r["ngoId"] == 1)
    assert ngo1["totalFunded"] == 800_000
    assert ngo1["impactPerMillion"] == pytest.approx(23.25 / 800_000 * 1e6, abs=1e-3)


def test_a_commitment_can_only_be_terminated_once(client: TestClient):
    post(client, "/commitments/1/terminate", {"reason": "first"})
    res = post(client, "/commitments/1/terminate", {"reason": "second"})
    assert res == {"ok": False, "kind": "sql", "code": "P0001",
                   "error": "commitment 1 is cancelled, only active commitments can be terminated"}
    assert len([a for a in get(client, "/audit") if a["action"] == "commitment_terminated"]) == 1


def test_a_completed_commitment_cannot_be_terminated(client: TestClient):
    for ms in (2, 3):
        post(client, f"/milestones/{ms}/evidence", {"metric": 5})
        post(client, f"/milestones/{ms}/verify")
    res = post(client, "/commitments/1/terminate", {"reason": "too late"})
    assert res["ok"] is False and res["error"].endswith("is completed, only active commitments can be terminated")


def test_a_reason_is_required_and_an_unknown_commitment_is_404(client: TestClient):
    for body in ({}, {"reason": ""}):
        assert client.post("/api/commitments/1/terminate", json=body).status_code == 422
    blank = post(client, "/commitments/1/terminate", {"reason": "   "})
    assert blank == {"ok": False, "kind": "sql", "code": "P0001",
                     "error": "a reason is required to terminate a commitment"}
    assert get(client, "/commitments")[0]["commitment"]["status"] == "active"
    assert client.post("/api/commitments/999/terminate", json={"reason": "x"}).status_code == 404


def test_the_milestones_of_a_terminated_commitment_are_frozen(client: TestClient):
    post(client, "/commitments/1/terminate", {"reason": "NGO withdrew"})
    before = get(client, "/commitments")
    res = post(client, "/milestones/2/evidence", {"metric": 5})
    assert res == {"ok": False, "kind": "sql", "code": "P0001",
                   "error": "commitment 1 is cancelled, its milestones can no longer change"}
    assert get(client, "/commitments") == before
    assert project_status(client, 1) == "terminated"


def test_a_terminated_project_cannot_report_progress_but_still_shows_its_funding(client: TestClient):
    post(client, "/commitments/1/terminate", {"reason": "NGO withdrew"})
    res = post(client, "/projects/1/impact-reports", {"value": 3})
    assert res == {"ok": False, "kind": "rule",
                   "error": "Project 1 was terminated, so it has no funded work left to report on."}
    detail = get(client, "/projects/1")
    assert detail["commitment"]["commitment"]["status"] == "cancelled"
    assert [p["status"] for p in detail["commitment"]["phases"]] == ["released", "terminated", "terminated"]


def test_a_later_release_does_not_complete_a_commitment_while_a_phase_is_held(client: TestClient):
    hold_phase_2(client)
    post(client, "/milestones/3/evidence", {"metric": 5})
    res = post(client, "/milestones/3/verify")
    assert res["ok"] is True
    assert not any("completed" in e["text"] for e in res["effects"])
    (cm,) = get(client, "/commitments")
    assert cm["commitment"]["status"] == "active"
    assert [p["status"] for p in cm["phases"]] == ["released", "held", "released"]
    assert project_status(client, 1) == "flagged"

    res = post(client, "/commitments/1/terminate", {"reason": "Phase 2 failed verification"})
    assert res["effects"][0]["text"] == (
        "Terminated 1 unreleased phase, ₹8,00,000. The ₹16,00,000 already released stays paid.")


# ---------------------------------------------------------------- monthly progress

def test_reporting_progress_appends_the_next_month_and_the_windows_recompute(client: TestClient):
    res = post(client, "/projects/1/impact-reports", {"value": 8.2})
    assert res["ok"] is True
    assert res["effects"][0]["text"] == "Recorded 8.2 for 2026-09."
    assert "3-month average is now 6.90 and the running total 31.45" in res["effects"][1]["text"]

    last = get(client, "/esg-timeline")[-1]
    assert last["month"] == "2026-09-01"
    assert (last["monthImpact"], last["momDelta"], last["cumulativeImpact"]) == (8.2, 1.3, 31.45)
    assert last["rolling3mo"] == pytest.approx((5.6 + 6.9 + 8.2) / 3, abs=1e-4)


def test_progress_needs_a_funded_project(client: TestClient):
    res = post(client, "/projects/2/impact-reports", {"value": 1})
    assert res == {"ok": False, "kind": "rule",
                   "error": "Project 2 has no commitment, so there is no funded work to report on."}
    assert client.post("/api/projects/999/impact-reports", json={"value": 1}).status_code == 404


# ---------------------------------------------------------------- the append-only ledger

@pytest.mark.parametrize("op", ["UPDATE", "DELETE"])
def test_the_ledger_refuses_to_be_rewritten(client: TestClient, op):
    before = get(client, "/ledger")
    res = post(client, "/ledger/1/attempts", {"op": op})
    assert res == {"ok": False, "kind": "sql", "code": "P0001",
                   "error": f"fund_transactions is append-only (attempted {op} on id 1)"}
    assert get(client, "/ledger") == before


def test_a_ledger_row_that_does_not_exist_never_fires_the_trigger(client: TestClient):
    res = post(client, "/ledger/999/attempts", {"op": "DELETE"})
    assert res == {"ok": False, "kind": "rule",
                   "error": "DELETE 0: no ledger row with id 999, so the trigger never fires."}


def test_only_update_and_delete_are_accepted(client: TestClient):
    assert client.post("/api/ledger/1/attempts", json={"op": "TRUNCATE"}).status_code == 422


# ---------------------------------------------------------------- reset

def test_reset_is_off_unless_enabled(client: TestClient):
    assert client.post("/api/reset").status_code == 403


def test_reset_rebuilds_the_demo_scenario(resettable_client: TestClient):
    c = resettable_client
    assert get(c, "/health")["resetEnabled"] is True
    commit(c, 2, 3)
    assert len(get(c, "/commitments")) == 2

    assert post(c, "/reset") == {"ok": True}

    assert len(get(c, "/commitments")) == 1
    assert get(c, "/companies")[1]["committedBudget"] == 0
    assert [e["type"] for e in get(c, "/ledger")] == ["lock", "release"]
    assert get(c, "/leaderboard")[0]["totalFunded"] == 2_400_000     # migration 006 is applied too
