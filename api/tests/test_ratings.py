"""Progress ratings: the NGO's words are saved, rated 1-5 against the bar, and never move money."""
from fastapi.testclient import TestClient

from app.main import create_app

from test_writes import get, post

UPDATE = ("Daily registers in all 40 schools show attendance up again this term; "
          "the block office spot-checked 8 schools on 14 September.")


def milestone(client: TestClient, commitment: int, phase: int) -> dict:
    view = next(v for v in get(client, "/commitments") if v["commitment"]["id"] == commitment)
    return next(m for m in view["milestones"] if m["phaseNo"] == phase)


def test_evidence_with_an_update_is_rated_against_the_bar_and_releases_nothing(client: TestClient):
    ms = milestone(client, 1, 2)       # project 1 promised +8; the bar at phase 2 of 3 is +5.33
    res = post(client, f"/milestones/{ms['id']}/evidence", {"metric": 5, "update": UPDATE})
    assert res["ok"] is True
    assert any(e["text"].startswith("Rated 4 of 5") for e in res["effects"]), res["effects"]

    after = milestone(client, 1, 2)
    assert (after["rating"], after["ratedBy"], after["updateText"]) == (4, "rules-v1", UPDATE)
    assert "On the bar" in after["ratingReason"]
    view = next(v for v in get(client, "/commitments") if v["commitment"]["id"] == 1)
    assert [p["status"] for p in view["phases"]][1] == "locked"


def test_evidence_without_an_update_is_saved_unrated(client: TestClient):
    ms = milestone(client, 1, 2)
    res = post(client, f"/milestones/{ms['id']}/evidence", {"metric": 5})
    assert res["ok"] is True and not any(e["text"].startswith("Rated") for e in res["effects"])
    after = milestone(client, 1, 2)
    assert (after["rating"], after["updateText"], after["ratingFlags"]) == (None, None, [])


def test_a_monthly_update_is_rated_and_read_back(client: TestClient):
    res = post(client, "/projects/1/impact-reports", {"value": 1.4, "update": UPDATE})
    assert res["ok"] is True       # +8.3 so far against a bar of +4.67 after 7 of 12 months
    assert any(e["text"].startswith("Rated 5 of 5") for e in res["effects"]), res["effects"]
    last = get(client, "/impact-reports")[-1]
    assert (last["metricValue"], last["rating"], last["updateText"]) == (1.4, 5, UPDATE)


def test_a_short_update_is_capped_whatever_the_numbers(client: TestClient):
    post(client, "/projects/1/impact-reports", {"value": 1.4, "update": "All good."})
    last = get(client, "/impact-reports")[-1]
    assert last["rating"] == 2 and "update too short to judge" in last["ratingFlags"]


class Down:
    def rate(self, ctx):
        raise RuntimeError("Gemini is not answering")


def test_when_the_rater_fails_the_update_is_kept_and_rated_later(fresh_db: str):
    with TestClient(create_app(fresh_db, allow_reset=False, rater=Down())) as client:
        res = post(client, "/projects/1/impact-reports", {"value": 1.4, "update": UPDATE})
        assert res["ok"] is True
        assert any("Not rated yet: Gemini is not answering" in e["text"] for e in res["effects"])
        last = get(client, "/impact-reports")[-1]
        assert (last["updateText"], last["rating"]) == (UPDATE, None)
