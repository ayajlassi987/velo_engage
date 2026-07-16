"""deterministic_opportunity_id/deterministic_campaign_id are ON CONFLICT
keys (see ve_orchestrator/ids.py's own docstring) — a silent change to the
hash input format or truncation length would duplicate rows instead of
deduplicating them, so their exact output for fixed input is pinned here."""

from datetime import date

from ve_orchestrator.ids import deterministic_campaign_id, deterministic_opportunity_id


def test_deterministic_opportunity_id_is_pinned():
    opp_id = deterministic_opportunity_id("P001", "clinic_alnoor_001", "dormancy", date(2026, 7, 16))
    assert opp_id == "aff603173175b3b52856ddbc1ffb8599"
    assert len(opp_id) == 32


def test_deterministic_opportunity_id_is_stable_across_calls():
    args = ("P001", "clinic_alnoor_001", "dormancy", date(2026, 7, 16))
    assert deterministic_opportunity_id(*args) == deterministic_opportunity_id(*args)


def test_deterministic_opportunity_id_differs_by_patient():
    a = deterministic_opportunity_id("P001", "clinic_alnoor_001", "dormancy", date(2026, 7, 16))
    b = deterministic_opportunity_id("P002", "clinic_alnoor_001", "dormancy", date(2026, 7, 16))
    assert a != b


def test_deterministic_opportunity_id_differs_by_day():
    a = deterministic_opportunity_id("P001", "clinic_alnoor_001", "dormancy", date(2026, 7, 16))
    b = deterministic_opportunity_id("P001", "clinic_alnoor_001", "dormancy", date(2026, 7, 17))
    assert a != b


def test_deterministic_campaign_id_is_pinned():
    campaign_id = deterministic_campaign_id("aff603173175b3b52856ddbc1ffb8599", date(2026, 7, 16))
    assert campaign_id == "c6c06a741b5a71850ae9a0c958ca8395"
    assert len(campaign_id) == 32
