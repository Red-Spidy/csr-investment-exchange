"""Read routes against the seeded demo database. Expected values are the ones the
SQL tests in db/tests and the frontend's engine tests already pin."""

import pytest
from fastapi.testclient import TestClient


def get(client: TestClient, path: str):
    r = client.get(f"/api{path}")
    assert r.status_code == 200, r.text
    return r.json()


def test_health(seeded: TestClient):
    assert get(seeded, "/health") == {"status": "ok", "resetEnabled": False}


def test_companies_use_the_frontend_field_names(seeded: TestClient):
    meridian = get(seeded, "/companies")[0]
    assert meridian["name"] == "Meridian Industries Ltd"
    assert meridian["mandatedBudget"] == 9_000_000
    assert meridian["committedBudget"] == 2_400_000
    assert "mandated_csr_budget" not in meridian


def test_rulebooks(seeded: TestClient):
    books = get(seeded, "/rulebooks")
    assert [b["companyId"] for b in books] == [1, 2, 3]
    assert books[0]["focusAreas"] == ["education"]
    assert books[0]["preferredStates"] == ["Rajasthan", "Bihar"]
    assert books[0]["targetSdgs"] == [4]
    assert (books[0]["minBudget"], books[0]["maxBudget"]) == (500_000, 5_000_000)


def test_scorecard_splits_the_commitment(seeded: TestClient):
    rows = {r["projectId"]: r for r in get(seeded, "/scorecard")}
    barmer = rows[1]
    assert barmer["status"] == "active"
    assert (barmer["state"], barmer["ngoId"], barmer["grade"]) == ("Rajasthan", 1, "A")
    assert [barmer["committedAmount"], barmer["releasedAmount"], barmer["lockedAmount"], barmer["heldAmount"]] == [
        2_400_000, 800_000, 1_600_000, 0,
    ]
    assert rows[8]["isAnomaly"] is True and rows[8]["status"] == "flagged"
    assert rows[2]["commitmentId"] is None and rows[2]["committedAmount"] == 0


def test_project_detail(seeded: TestClient):
    d = get(seeded, "/projects/1")
    assert d["project"]["title"] == "Rural school attendance drive, Barmer"
    assert d["ngo"]["registrationNo"] == "NGO-EDU-0001"
    assert d["extraction"]["geography"] == {"state": "Rajasthan", "district": "Barmer", "ruralUrban": "rural"}
    assert d["extraction"]["targetMetric"]["target"] == 69
    assert d["prediction"]["ciLow"] < d["prediction"]["predictedValue"] < d["prediction"]["ciHigh"]
    assert d["risk"]["grade"] == "A"
    assert [h["fy"] for h in d["history"]] == ["FY22-23", "FY23-24"]
    cm = d["commitment"]
    assert [(p["phaseNo"], p["amount"], p["status"]) for p in cm["phases"]] == [
        (1, 800_000, "released"), (2, 800_000, "locked"), (3, 800_000, "locked"),
    ]
    assert [m["verification"] for m in cm["milestones"]] == ["verified", "pending", "pending"]
    assert cm["ngoName"] == "Vidya Foundation" and cm["companyName"] == "Meridian Industries Ltd"


def test_unfunded_project_has_no_commitment(seeded: TestClient):
    assert get(seeded, "/projects/8")["commitment"] is None


def test_unknown_ids_are_404(seeded: TestClient):
    assert seeded.get("/api/projects/999").status_code == 404
    assert seeded.get("/api/rulebooks/999/matches").status_code == 404


def test_commitments_list(seeded: TestClient):
    (cm,) = get(seeded, "/commitments")
    assert cm["commitment"]["amount"] == 2_400_000 and cm["commitment"]["status"] == "active"
    assert len(cm["phases"]) == len(cm["milestones"]) == 3


def test_ledger_and_audit_are_in_order(seeded: TestClient):
    ledger = get(seeded, "/ledger")
    assert [(e["type"], e["amount"]) for e in ledger] == [("lock", 2_400_000), ("release", 800_000)]
    assert ledger[1]["note"] == "phase 1 released on verified milestone 1"
    assert [a["action"] for a in get(seeded, "/audit")] == ["funds_locked", "phase_released"]


# ---------------------------------------------------------------- matching

def test_meridian_only_the_gaya_project_qualifies(seeded: TestClient):
    report = get(seeded, "/rulebooks/1/matches")
    assert [m["projectId"] for m in report["ranked"]] == [2]
    top = report["ranked"][0]
    assert top["similarity"] == pytest.approx(0.99679, abs=1e-5)
    assert top["matchScore"] == pytest.approx(0.88108, abs=1e-5)
    assert sum(top["contributions"].values()) == pytest.approx(top["matchScore"], abs=1e-4)
    assert top["sharedSdgs"] == [4]


def test_kalpataru_handpumps_squeak_in_on_an_sdg(seeded: TestClient):
    ranked = get(seeded, "/rulebooks/2/matches")["ranked"]
    assert [m["projectId"] for m in ranked] == [3, 4]
    assert ranked[0]["matchScore"] == pytest.approx(0.9638, abs=1e-4)
    assert ranked[1]["similarity"] == pytest.approx(-0.00067, abs=1e-5)
    assert ranked[1]["matchScore"] == pytest.approx(0.2991, abs=1e-4)
    assert ranked[1]["sharedSdgs"] == [3]


def test_sundar_excludes_the_flagged_over_budget_project_with_reasons(seeded: TestClient):
    report = get(seeded, "/rulebooks/3/matches")
    assert [m["projectId"] for m in report["ranked"]] == [4]
    assert report["ranked"][0]["matchScore"] == pytest.approx(0.8993, abs=1e-4)
    out = {e["projectId"]: e for e in report["excluded"]}
    assert 4 not in out and set(out) == {1, 2, 3, 5, 6, 7, 8}
    flagged = out[8]["reasons"]
    assert any("flagged" in r for r in flagged) and any("outside" in r for r in flagged)
    assert "₹42,00,000" in " ".join(flagged)
    assert any("Maharashtra is not one of Rajasthan" in r for r in out[3]["reasons"])


# ---------------------------------------------------------------- window-function views

def test_esg_timeline_matches_the_window_view(seeded: TestClient):
    rows = get(seeded, "/esg-timeline")
    assert [r["month"] for r in rows] == [f"2026-0{m}-01" for m in range(3, 9)]
    assert [r["monthImpact"] for r in rows] == [1.2, 0.85, 1.05, 1.3, 1.2, 1.3]
    assert [r["cumulativeImpact"] for r in rows] == [1.2, 2.05, 3.1, 4.4, 5.6, 6.9]
    assert [r["momDelta"] for r in rows] == [None, -0.35, 0.2, 0.25, -0.1, 0.1]
    assert [r["rolling3mo"] for r in rows] == [1.2, 1.025, 1.0333, 1.0667, 1.1833, 1.2667]
    assert rows[-1]["peersInMonth"] == 1 and rows[-1]["companyName"] == "Meridian Industries Ltd"


def test_impact_reports_are_each_months_gain_per_project(seeded: TestClient):
    rows = get(seeded, "/impact-reports")
    assert [(r["projectId"], r["periodMonth"], r["metricValue"]) for r in rows] == [
        (1, f"2026-0{m}-01", v) for m, v in zip(range(3, 9), [1.2, 0.85, 1.05, 1.3, 1.2, 1.3])]
    assert set(rows[0]) == {"id", "projectId", "periodMonth", "metricValue", "updateText", "rating",
                            "ratingReason", "ratingFlags", "ratedBy"}
    assert rows[0]["updateText"].startswith("Hot midday meals") and rows[0]["rating"] is None


def test_leaderboard_counts_funding_once_not_once_per_report(seeded: TestClient):
    rows = {r["ngoId"]: r for r in get(seeded, "/leaderboard")}
    vidya = rows[1]
    assert (vidya["totalImpact"], vidya["totalFunded"], vidya["impactPerMillion"]) == (6.9, 2_400_000, 2.875)
    assert (vidya["sectorRank"], vidya["overallPercentile"]) == (1, 1)
    assert rows[2]["sectorRank"] == 2 and rows[2]["impactPerMillion"] is None
    assert rows[3]["overallPercentile"] == 0
