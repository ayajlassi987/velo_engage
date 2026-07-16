"""Regression guard for the crowding-out fix (see feature_store.py's own
comment): ~20,000 synthetic SYN*/P0xx patients were being evaluated by the
live daily pipeline alongside the 7 real Epic patients, drowning them out
of the WORKFLOW_BATCH_LIMIT entirely. This pins the exact SQL predicate
that excludes them, using a stub cursor (no real Postgres needed) — the
real-database version of this test lives in tests/integration (Phase 4)."""

from ve_orchestrator.feature_store import fetch_patient_features


class StubCursor:
    def __init__(self, rows):
        self._rows = rows
        self.last_query = None
        self.last_params = None

    def execute(self, query, params):
        self.last_query = query
        self.last_params = params

    def fetchall(self):
        return self._rows


class StubRedis:
    """Simulates a cache miss (no cached value) without needing real Redis."""

    def get(self, key):
        return None

    def set(self, key, value, ex=None):
        pass


def test_query_excludes_synthetic_and_seed_prefixes(monkeypatch):
    import ve_orchestrator.feature_store as feature_store

    monkeypatch.setattr(feature_store, "_client", lambda: StubRedis())
    cur = StubCursor(rows=[("erXuFYUfucBZaryVksYEcMg3", {"age": 45})])

    fetch_patient_features(cur, "clinic_alnoor_001")

    assert "NOT LIKE 'SYN%%'" in cur.last_query
    assert "NOT LIKE 'P0%%'" in cur.last_query
    assert cur.last_params == ("clinic_alnoor_001",)


def test_returns_rows_from_cursor(monkeypatch):
    import ve_orchestrator.feature_store as feature_store

    monkeypatch.setattr(feature_store, "_client", lambda: StubRedis())
    cur = StubCursor(rows=[("erXuFYUfucBZaryVksYEcMg3", {"age": 45})])

    rows = fetch_patient_features(cur, "clinic_alnoor_001")

    assert rows == [("erXuFYUfucBZaryVksYEcMg3", {"age": 45})]


def test_redis_cache_hit_skips_postgres_entirely(monkeypatch):
    import json
    import ve_orchestrator.feature_store as feature_store

    class HitRedis:
        def get(self, key):
            return json.dumps([{"patient_id": "erXuFYUfucBZaryVksYEcMg3", "features": {"age": 45}}])

    monkeypatch.setattr(feature_store, "_client", lambda: HitRedis())
    cur = StubCursor(rows=[])  # would fail the test if queried, since it has no matching rows

    rows = fetch_patient_features(cur, "clinic_alnoor_001")

    assert rows == [("erXuFYUfucBZaryVksYEcMg3", {"age": 45})]
    assert cur.last_query is None  # never fell through to Postgres
