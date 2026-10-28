"""API tests run against real Postgres, in databases of their own.

Set TEST_ADMIN_URL to a role that can CREATE DATABASE (default: the compose database
server). A template database is migrated and seeded once; every test that writes gets
a fresh copy of it, so tests never touch csr_exchange and never see each other.
"""

import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo

from app.admin import apply_schema, seed
from app.main import create_app
from app.rating import rule_rater

# Progress updates are rated by the deterministic rules in tests, never by Gemini.
RULES = rule_rater()

ADMIN_URL = os.environ.get("TEST_ADMIN_URL", "postgresql://csr:csr@localhost:5433/postgres")
TEMPLATE = "csr_api_template"


def _url(dbname: str) -> str:
    return make_conninfo(ADMIN_URL, dbname=dbname)


@pytest.fixture(scope="session")
def template_db() -> Iterator[str]:
    try:
        admin = psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=5)
    except psycopg.OperationalError as err:
        pytest.skip(f"no Postgres at TEST_ADMIN_URL ({err})")
    with admin:
        admin.execute(f"DROP DATABASE IF EXISTS {TEMPLATE} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {TEMPLATE}")
        with psycopg.connect(_url(TEMPLATE), autocommit=True) as conn:
            apply_schema(conn)
            seed(conn)
        yield TEMPLATE
        admin.execute(f"DROP DATABASE IF EXISTS {TEMPLATE} WITH (FORCE)")


@pytest.fixture
def fresh_db(template_db: str) -> Iterator[str]:
    """A private, freshly seeded copy of the demo database."""
    name = f"csr_api_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f"CREATE DATABASE {name} TEMPLATE {template_db}")
        try:
            yield _url(name)
        finally:
            admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


@pytest.fixture
def client(fresh_db: str) -> Iterator[TestClient]:
    with TestClient(create_app(fresh_db, allow_reset=False, rater=RULES)) as c:
        yield c


@pytest.fixture
def resettable_client(fresh_db: str) -> Iterator[TestClient]:
    with TestClient(create_app(fresh_db, allow_reset=True, rater=RULES)) as c:
        yield c


@pytest.fixture(scope="module")
def seeded(template_db: str) -> Iterator[TestClient]:
    """For read-only tests: one client on its own copy, shared across a module."""
    name = f"csr_api_ro_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f"CREATE DATABASE {name} TEMPLATE {template_db}")
        try:
            with TestClient(create_app(_url(name), allow_reset=False, rater=RULES)) as c:
                yield c
        finally:
            admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
