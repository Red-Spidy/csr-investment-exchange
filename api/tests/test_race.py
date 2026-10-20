"""The double-funding race. Two real sessions contend for one project in a scratch
schema; each case switches off the layers before it, as the Safeguards page does."""

import psycopg
import pytest
from fastapi.testclient import TestClient

LAYERS_ON = {"statusCheck": True, "guardTrigger": True, "uniqueIndex": True}


def race(client: TestClient, **off: bool) -> dict:
    r = client.post("/api/safeguards/race", json={**LAYERS_ON, **{k: False for k in off}})
    assert r.status_code == 200, r.text
    return r.json()


def test_with_every_layer_on_exactly_one_session_wins(client: TestClient):
    r = race(client)
    assert (r["winner"], r["stoppedBy"], r["activeCommitments"], r["committed"], r["mandated"]) == (
        "A", 1, 1, 100_000, 500_000,
    )
    assert r["message"] == "project 1 is matched, only approved projects can be funded"
    assert r["steps"][-1]["tone"] == "stop" and "Layer 1" in r["steps"][-1]["text"]


def test_the_second_session_really_waited_on_the_row_lock(client: TestClient):
    r = race(client)
    assert r["steps"][1]["text"] == "Asks for the same row lock. Postgres makes B wait."
    waited = next(s["text"] for s in r["steps"] if s["text"].startswith("Gets the lock after waiting"))
    assert int(waited.split("waiting ")[1].split(" ms")[0]) >= 250   # A holds the lock ~300 ms once B is queued


@pytest.mark.parametrize(
    ("off", "layer", "message"),
    [
        ({"statusCheck": 1}, 2, "project 1 already has active commitment 1"),
        ({"statusCheck": 1, "guardTrigger": 1}, 3,
         'duplicate key value violates unique constraint "uniq_active_commitment_per_project"'),
    ],
)
def test_each_layer_catches_it_when_the_one_before_is_removed(client: TestClient, off, layer, message):
    r = race(client, **off)
    assert (r["winner"], r["stoppedBy"], r["message"]) == ("A", layer, message)
    assert (r["activeCommitments"], r["committed"]) == (1, 100_000)


def test_with_every_layer_off_the_project_is_funded_twice(client: TestClient):
    r = race(client, statusCheck=1, guardTrigger=1, uniqueIndex=1)
    assert (r["winner"], r["stoppedBy"], r["message"]) == (None, None, None)
    assert (r["activeCommitments"], r["committed"]) == (2, 200_000)
    assert r["steps"][-1]["tone"] == "bad"


def test_the_exchange_tables_are_untouched_and_no_scratch_schema_is_left(client: TestClient, fresh_db: str):
    before = (client.get("/api/commitments").json(), client.get("/api/ledger").json(), client.get("/api/audit").json())
    race(client)
    race(client, statusCheck=1, guardTrigger=1, uniqueIndex=1)
    assert (client.get("/api/commitments").json(), client.get("/api/ledger").json(), client.get("/api/audit").json()) == before
    with psycopg.connect(fresh_db) as conn:
        assert conn.execute("SELECT count(*) FROM pg_namespace WHERE nspname LIKE 'race\\_%'").fetchone()[0] == 0
