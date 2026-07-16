"""Integration tests run against the real docker-compose stack — no mocked/
lightweight profile exists (see PROJECT_STATUS.md's testing plan), and
building one from scratch isn't worth it for what these tests need to
prove. Requires `docker compose -f infra/docker-compose.dev.yml up -d`
already running; skips with a clear message rather than trying to
programmatically start the whole stack inside pytest.
"""

import os

import psycopg2
import pytest


def _pg_connect():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "velodb"),
        user=os.getenv("DB_USER", "velo"),
        password=os.getenv("DB_PASSWORD", "velo_secret"),
        connect_timeout=3,
    )


@pytest.fixture(scope="session")
def pg_conn():
    try:
        conn = _pg_connect()
    except psycopg2.OperationalError as exc:
        pytest.skip(
            f"Postgres not reachable at localhost:5432 ({exc}) — start the stack with "
            f"`docker compose -f infra/docker-compose.dev.yml up -d` before running integration tests."
        )
    yield conn
    conn.close()


@pytest.fixture
def pg_cursor(pg_conn):
    cur = pg_conn.cursor()
    yield cur
    pg_conn.rollback()  # never persist test fixtures into the real dev database
    cur.close()
