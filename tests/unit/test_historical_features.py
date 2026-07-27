"""refresh_historical_features issues one bulk UPDATE scoped to a single
clinic and reports back how many patient_features rows it touched. The SQL
itself (bookings/outcomes aggregation) is verified against the real dev
Postgres — a stub cursor can't meaningfully exercise CTE correctness — this
pins the query is clinic-scoped and the row-count contract holds."""

from ve_orchestrator.historical_features import refresh_historical_features


class StubCursor:
    def __init__(self, rowcount):
        self.rowcount = rowcount
        self.last_query = None
        self.last_params = None

    def execute(self, query, params):
        self.last_query = query
        self.last_params = params


def test_scopes_update_to_the_given_clinic():
    cur = StubCursor(rowcount=7)

    refresh_historical_features(cur, "clinic_alnoor_001")

    assert cur.last_params == {"clinic_id": "clinic_alnoor_001"}
    assert "clinic_id = %(clinic_id)s" in cur.last_query


def test_returns_cursor_rowcount():
    cur = StubCursor(rowcount=7)

    updated = refresh_historical_features(cur, "clinic_demo_002")

    assert updated == 7
