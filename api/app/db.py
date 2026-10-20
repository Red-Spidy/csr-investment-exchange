"""Connection pool. Money is NUMERIC in Postgres and a plain float in the JSON the
UI reads, matching the frontend's `number` money type."""

import os

import psycopg
from psycopg.rows import dict_row
from psycopg.types.numeric import FloatLoader
from psycopg_pool import ConnectionPool

DEFAULT_URL = "postgresql://csr:csr@localhost:5433/csr_exchange"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


def _configure(conn: psycopg.Connection) -> None:
    conn.adapters.register_loader("numeric", FloatLoader)


def make_pool(url: str, timeout: float = 10) -> ConnectionPool:
    # prepare_threshold=None: no server-side prepared statements, so a schema
    # rebuild (POST /api/reset) can never leave a stale plan on a pooled connection.
    return ConnectionPool(
        url,
        min_size=1,
        max_size=8,
        timeout=timeout,
        open=False,
        configure=_configure,
        kwargs={"row_factory": dict_row, "prepare_threshold": None},
        name="csr-api",
    )
