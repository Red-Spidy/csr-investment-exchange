"""Rebuild the database from db/migrations and db/seed.sql (what `make demo` does)."""

from pathlib import Path

import psycopg

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "db" / "migrations"
SEED = REPO / "db" / "seed.sql"


def apply_schema(conn: psycopg.Connection) -> None:
    """Run every migration in filename order. No parameters are passed, so the
    `%` in the plpgsql format() strings is left alone."""
    for path in sorted(MIGRATIONS.glob("*.sql")):
        conn.execute(path.read_text())


def seed(conn: psycopg.Connection) -> None:
    conn.execute(SEED.read_text())


def reset_database(url: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        apply_schema(conn)
        seed(conn)
