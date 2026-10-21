"""FastAPI layer over the exchange database.

It implements web/src/data/api.ts (`ExchangeApi`) over HTTP. The database does the
work; these routes reshape rows and report what the database did or refused.

A write the database refuses is an expected outcome, not a server fault, so write
routes answer 200 with `{"ok": false, "kind": "sql", "error": ...}` carrying the
database's own error text. HTTP errors are kept for bad requests (422), unknown
ids (404) and an unreachable database (503).

There is no authentication: whoever can reach this service can verify milestones
and move money. Run it on localhost or behind something that does authenticate.
"""

import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from psycopg_pool import ConnectionPool

from . import reads, writes
from .admin import reset_database
from .db import database_url, make_pool
from .race import Guards, run_race

PositiveId = Annotated[int, Field(gt=0)]


class CommitBody(BaseModel):
    companyId: PositiveId
    projectId: PositiveId
    matchId: PositiveId | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)


class EvidenceBody(BaseModel):
    metric: float = Field(allow_inf_nan=False)


class TerminateBody(BaseModel):
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class ImpactBody(BaseModel):
    value: float = Field(allow_inf_nan=False)


class LedgerAttemptBody(BaseModel):
    op: Literal["UPDATE", "DELETE"]


class RaceBody(BaseModel):
    statusCheck: bool = True
    guardTrigger: bool = True
    uniqueIndex: bool = True


def create_app(
    url: str | None = None, allow_reset: bool | None = None, pool_timeout: float = 10,
) -> FastAPI:
    db_url = url or database_url()
    reviewer = os.environ.get("CSR_REVIEWER", "Reviewer")
    reset_enabled = (
        os.environ.get("CSR_ALLOW_RESET") == "1" if allow_reset is None else allow_reset
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # wait=False: the API starts even if Postgres is not up yet, and /api/health
        # reports the database as unavailable until it is.
        app.state.pool = make_pool(db_url, pool_timeout)
        app.state.pool.open(wait=False)
        try:
            yield
        finally:
            app.state.pool.close()

    app = FastAPI(title="CSR Investment Exchange API", lifespan=lifespan)
    api = APIRouter(prefix="/api")

    def pool_of(request: Request) -> ConnectionPool:
        return request.app.state.pool

    Pool = Annotated[ConnectionPool, Depends(pool_of)]

    def unavailable(err: psycopg.Error) -> bool:
        """True for a failure to reach the database, as opposed to the database saying no."""
        return err.sqlstate is None or err.sqlstate.startswith("08")

    def read(pool: ConnectionPool, fn: Callable[[psycopg.Connection], Any]) -> Any:
        try:
            with pool.connection() as conn:
                return fn(conn)
        except reads.NotFound as err:
            raise HTTPException(404, str(err)) from err
        except psycopg.Error as err:
            if unavailable(err):
                raise HTTPException(503, "database unavailable") from err
            raise

    def write(pool: ConnectionPool, fn: Callable[[psycopg.Connection], writes.Written]) -> dict[str, Any]:
        try:
            with pool.connection() as conn:     # commits on success, rolls back on any exception
                done = fn(conn)
        except reads.NotFound as err:
            raise HTTPException(404, str(err)) from err
        except writes.RuleError as err:
            return {"ok": False, "kind": "rule", "error": str(err)}
        except psycopg.Error as err:
            if unavailable(err):
                raise HTTPException(503, "database unavailable") from err
            return {
                "ok": False,
                "kind": "sql",
                "error": err.diag.message_primary or str(err),
                "code": err.sqlstate,
            }
        result: dict[str, Any] = {"ok": True, "effects": done.effects}
        if done.commitment_id is not None:
            result["commitmentId"] = done.commitment_id
        return result

    # ------------------------------------------------------------ health

    @api.get("/health")
    def health(pool: Pool) -> dict[str, Any]:
        try:
            with pool.connection() as conn:
                ready = conn.execute("SELECT to_regclass('public.companies') IS NOT NULL AS ok").fetchone()
        except psycopg.Error as err:
            raise HTTPException(503, "database unavailable") from err
        if not ready or not ready["ok"]:
            raise HTTPException(503, "database is reachable but the schema is not loaded (run make migrate seed)")
        return {"status": "ok", "resetEnabled": reset_enabled}

    # ------------------------------------------------------------ reads

    @api.get("/companies")
    def companies(pool: Pool):
        return read(pool, reads.companies)

    @api.get("/rulebooks")
    def rulebooks(pool: Pool):
        return read(pool, reads.rulebooks)

    @api.get("/scorecard")
    def scorecard(pool: Pool):
        return read(pool, reads.scorecard)

    @api.get("/projects/{project_id}")
    def project(project_id: PositiveId, pool: Pool):
        return read(pool, lambda c: reads.project_detail(c, project_id))

    @api.get("/rulebooks/{rulebook_id}/matches")
    def matches(rulebook_id: PositiveId, pool: Pool):
        return read(pool, lambda c: reads.match_report(c, rulebook_id))

    @api.get("/commitments")
    def commitments(pool: Pool):
        return read(pool, reads.commitment_views)

    @api.get("/ledger")
    def ledger(pool: Pool):
        return read(pool, reads.ledger)

    @api.get("/audit")
    def audit(pool: Pool):
        return read(pool, reads.audit)

    @api.get("/esg-timeline")
    def esg_timeline(pool: Pool):
        return read(pool, reads.esg_timeline)

    @api.get("/leaderboard")
    def leaderboard(pool: Pool):
        return read(pool, reads.leaderboard)

    # ------------------------------------------------------------ writes

    @api.post("/commitments")
    def commit(body: CommitBody, pool: Pool):
        return write(pool, lambda c: writes.commit_funds(c, body.companyId, body.projectId, body.matchId, body.amount))

    @api.post("/milestones/{milestone_id}/evidence")
    def submit_evidence(milestone_id: PositiveId, body: EvidenceBody, pool: Pool):
        return write(pool, lambda c: writes.submit_evidence(c, milestone_id, body.metric))

    @api.post("/milestones/{milestone_id}/verify")
    def verify(milestone_id: PositiveId, pool: Pool):
        return write(pool, lambda c: writes.verify_milestone(c, milestone_id, reviewer))

    @api.post("/milestones/{milestone_id}/fail")
    def fail(milestone_id: PositiveId, pool: Pool):
        return write(pool, lambda c: writes.fail_milestone(c, milestone_id, reviewer))

    @api.post("/commitments/{commitment_id}/terminate")
    def terminate(commitment_id: PositiveId, body: TerminateBody, pool: Pool):
        return write(pool, lambda c: writes.terminate_commitment(c, commitment_id, body.reason, reviewer))

    @api.post("/projects/{project_id}/impact-reports")
    def report_impact(project_id: PositiveId, body: ImpactBody, pool: Pool):
        return write(pool, lambda c: writes.report_impact(c, project_id, body.value))

    @api.post("/ledger/{ledger_id}/attempts")
    def ledger_attempt(ledger_id: PositiveId, body: LedgerAttemptBody, pool: Pool):
        return write(pool, lambda c: writes.attempt_ledger_mutation(c, body.op, ledger_id))

    # ------------------------------------------------------------ safeguards and reset

    @api.post("/safeguards/race")
    def race(body: RaceBody):
        guards = Guards(body.statusCheck, body.guardTrigger, body.uniqueIndex)
        try:
            return run_race(db_url, guards)
        except psycopg.Error as err:
            if unavailable(err):
                raise HTTPException(503, "database unavailable") from err
            raise HTTPException(500, f"could not run the race: {err.diag.message_primary or err}") from err

    @api.post("/reset")
    def reset():
        if not reset_enabled:
            raise HTTPException(403, "reset is disabled; start the API with CSR_ALLOW_RESET=1")
        reset_database(db_url)
        return {"ok": True}

    app.include_router(api)
    return app


app = create_app()
