"""Two real database sessions race to fund the same project.

This is db/tests/06_concurrency.sh as an endpoint. It runs in a throwaway schema
built from the real migrations (002 and 004), so the exchange's own tables are
never touched and nothing it writes can be left behind. The three double-funding
layers can be switched off one at a time to show what each one catches:

  1. the status check inside fn_commit_funds   (source patched out of the scratch copy)
  2. trg_guard_double_funding                  (trigger disabled)
  3. uniq_active_commitment_per_project        (index dropped)
"""

import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

import psycopg

from .admin import MIGRATIONS

ADVISORY_KEY = 727_001          # one race at a time, across every API worker
BUDGET, PRICE = 500_000, 100_000
HOLD_AFTER_QUEUED = 0.3          # seconds A keeps the lock once B is seen waiting
STATUS_CHECK = re.compile(r"IF pr\.status <> 'approved' THEN.*?END IF;", re.S)


@dataclass
class Guards:
    status_check: bool = True
    guard_trigger: bool = True
    unique_index: bool = True


def _layer(err: psycopg.Error) -> int | None:
    message = err.diag.message_primary or ""
    if err.diag.constraint_name == "uniq_active_commitment_per_project":
        return 3
    if "already has active commitment" in message:
        return 2
    if "only approved projects can be funded" in message:
        return 1
    return None


def _build_scratch_schema(admin: psycopg.Connection, schema: str, guards: Guards) -> None:
    admin.execute(f"CREATE SCHEMA {schema}")
    admin.execute(f"SET search_path = {schema}, public")
    admin.execute((MIGRATIONS / "002_core_tables.sql").read_text())

    functions = (MIGRATIONS / "004_functions_triggers.sql").read_text()
    if not guards.status_check:
        functions, removed = STATUS_CHECK.subn("", functions)
        if removed != 1:
            raise RuntimeError("could not find the status check in 004_functions_triggers.sql")
    admin.execute(functions)

    if not guards.guard_trigger:
        admin.execute("ALTER TABLE commitments DISABLE TRIGGER trg_guard_double_funding")
    if not guards.unique_index:
        admin.execute(f"DROP INDEX {schema}.uniq_active_commitment_per_project")

    # Same fixture as 06_concurrency.sh: room for exactly one commitment.
    admin.execute("INSERT INTO ngos (name, registration_no, sector) VALUES ('Race NGO', 'T-RACE-NGO', 'education')")
    admin.execute(
        "INSERT INTO companies (name, cin, fy, avg_net_profit, mandated_csr_budget) "
        f"VALUES ('Race Co', 'T-RACE-CIN', 'FY24-25', 5000000, {BUDGET})"
    )
    admin.execute(
        "INSERT INTO projects (ngo_id, title, proposal_text, sector, requested_amount, "
        f"duration_months, num_phases, status) VALUES (1, 'Race project', 'text', 'education', {PRICE}, 6, 2, 'approved')"
    )


def run_race(url: str, guards: Guards) -> dict[str, Any]:
    schema = f"race_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute("SELECT pg_advisory_lock(%s)", (ADVISORY_KEY,))
        try:
            # A crashed earlier run may have left its schema behind.
            for (stale,) in admin.execute(
                "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'race\\_%'"
            ).fetchall():
                admin.execute(f"DROP SCHEMA {stale} CASCADE")
            _build_scratch_schema(admin, schema, guards)
            return _race(url, admin, schema)
        finally:
            admin.execute("RESET search_path")
            admin.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            admin.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_KEY,))


def _race(url: str, admin: psycopg.Connection, schema: str) -> dict[str, Any]:
    call = f"SELECT fn_commit_funds(1, 1, NULL, {PRICE})"
    options = f"-c search_path={schema},public"
    a_has_lock, b_asked = threading.Event(), threading.Event()
    outcome: dict[str, Any] = {}

    def session_a() -> None:
        try:
            with psycopg.connect(url, options=options) as conn:
                conn.execute(call)                      # takes the company row lock
                a_has_lock.set()
                b_asked.wait(5)
                # Hold the lock until Postgres reports B queued behind it, so the
                # overlap is observed rather than assumed from a sleep.
                deadline = time.monotonic() + 3
                waiting = None
                while time.monotonic() < deadline:
                    waiting = conn.execute(
                        """SELECT count(*) FROM pg_stat_activity
                            WHERE datname = current_database() AND wait_event_type = 'Lock'
                              AND pid <> pg_backend_pid() AND query = %s""",
                        (call,),
                    ).fetchone()
                    if waiting and waiting[0] > 0:
                        break
                    time.sleep(0.02)
                outcome["b_was_blocked"] = bool(waiting and waiting[0] > 0)
                time.sleep(HOLD_AFTER_QUEUED)   # real work would take time here; makes the overlap visible
                conn.commit()
            outcome["A"] = None
        except psycopg.Error as err:
            outcome["A"] = err
        finally:
            a_has_lock.set()

    def session_b() -> None:
        a_has_lock.wait(5)
        try:
            with psycopg.connect(url, options=options) as conn:
                b_asked.set()
                started = time.perf_counter()
                try:
                    conn.execute(call)
                    conn.commit()
                    outcome["B"] = None
                except psycopg.Error as err:
                    conn.rollback()
                    outcome["B"] = err
                outcome["b_waited_ms"] = round((time.perf_counter() - started) * 1000)
        finally:
            b_asked.set()

    threads = [threading.Thread(target=session_a), threading.Thread(target=session_b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)

    if outcome.get("A") is not None or "A" not in outcome:
        raise RuntimeError(f"session A failed: {outcome.get('A')}")

    totals = admin.execute(
        """SELECT (SELECT count(*) FROM commitments WHERE status = 'active') AS active,
                  (SELECT committed_budget FROM companies WHERE id = 1)       AS committed,
                  (SELECT mandated_csr_budget FROM companies WHERE id = 1)    AS mandated"""
    ).fetchone()
    err_b: psycopg.Error | None = outcome.get("B")
    layer = _layer(err_b) if err_b is not None else None
    waited = outcome.get("b_waited_ms", 0)

    where = {
        1: "Layer 1, the status check in fn_commit_funds",
        2: "Layer 2, the BEFORE INSERT guard trigger",
        3: "Layer 3, the partial unique index",
    }.get(layer, "The budget check")

    steps = [
        {"who": "A", "tone": "ok", "text": "Takes the row lock on Race Co (SELECT ... FOR UPDATE)."},
        {"who": "B", "tone": "wait", "text": "Asks for the same row lock. Postgres makes B wait."
            if outcome.get("b_was_blocked") else "Asks for the same row lock."},
        {"who": "A", "tone": "ok", "text": "Checks the project is approved and the budget has room."},
        {"who": "A", "tone": "ok", "text": "Inserts the commitment. No active one exists, so every guard passes."},
        {"who": "A", "tone": "ok", "text": "Commits. Phases, milestones and the lock ledger row land with it."},
        {"who": "B", "tone": "ok", "text": f"Gets the lock after waiting {waited} ms and reads A’s committed rows."},
    ]
    if err_b is None:
        steps.append({"who": "B", "tone": "bad",
                      "text": "Inserts a second commitment for the same project. Nothing stopped it."})
    else:
        steps.append({"who": "B", "tone": "stop", "text": f"{where}, rejects it and rolls back."})

    return {
        "steps": steps,
        "winner": "A" if err_b is not None else None,
        "stoppedBy": layer,
        "message": None if err_b is None else (err_b.diag.message_primary or str(err_b)),
        "activeCommitments": totals[0],
        "committed": float(totals[1]),
        "mandated": float(totals[2]),
    }
