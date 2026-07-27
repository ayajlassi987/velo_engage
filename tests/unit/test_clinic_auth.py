"""Tests _resolve_clinic() (ve_console/auth.py) — the username -> clinic_id
mapping added for multi-clinic support. Mocks psycopg2.connect directly,
same boundary-mocking approach used elsewhere in this suite for external
dependencies (e.g. nemoguard_client's httpx.Client mocking)."""

import ve_console.auth as auth


class FakeCursor:
    def __init__(self, row):
        self._row = row

    def execute(self, sql, params=None):
        pass

    def fetchone(self):
        return self._row

    def close(self):
        pass


class FakeConn:
    def __init__(self, row):
        self._row = row

    def cursor(self):
        return FakeCursor(self._row)

    def close(self):
        pass


def test_resolve_clinic_returns_mapped_clinic(monkeypatch):
    monkeypatch.setattr(auth.psycopg2, "connect", lambda **kwargs: FakeConn(("clinic_demo_002", "Riverside Dental Group")))
    assert auth._resolve_clinic("riverside_owner") == ("clinic_demo_002", "Riverside Dental Group")


def test_resolve_clinic_falls_back_when_username_unmapped(monkeypatch):
    monkeypatch.setattr(auth.psycopg2, "connect", lambda **kwargs: FakeConn(None))
    assert auth._resolve_clinic("nonexistent_user") == (auth._DEFAULT_CLINIC_ID, "Al Noor Clinic")


def test_resolve_clinic_falls_back_on_db_error(monkeypatch):
    def raise_connect(**kwargs):
        raise ConnectionError("db unreachable")
    monkeypatch.setattr(auth.psycopg2, "connect", raise_connect)
    assert auth._resolve_clinic("owner") == (auth._DEFAULT_CLINIC_ID, "Al Noor Clinic")
