"""Tests the per-session clinic_id helper added for multi-clinic support
(ve_console/main.py's _clinic_id) — pure logic, no DB needed, matching this
suite's precedent of unit-testing what doesn't require live infra."""

import ve_console.main as main


class FakeRequest:
    def __init__(self, session: dict):
        self.session = session


def test_clinic_id_reads_from_session():
    request = FakeRequest({"clinic_id": "clinic_demo_002"})
    assert main._clinic_id(request) == "clinic_demo_002"


def test_clinic_id_falls_back_to_default_when_session_missing_key():
    request = FakeRequest({})
    assert main._clinic_id(request) == main.CLINIC_ID


def test_clinic_id_different_sessions_get_different_clinics():
    """The actual isolation guarantee: two requests with different session
    clinic_ids must resolve to different values — this is what every route
    handler relies on to keep one clinic's data from leaking into another's
    page render."""
    alnoor_request = FakeRequest({"clinic_id": "clinic_alnoor_001"})
    demo_request = FakeRequest({"clinic_id": "clinic_demo_002"})
    assert main._clinic_id(alnoor_request) != main._clinic_id(demo_request)
