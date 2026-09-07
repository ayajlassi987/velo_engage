"""Pure-function coverage for ve_connect_dental's mapper.py — no DB, no
OpenDental connection, mirrors ve_connect's own test_mapper.py in spirit."""

from datetime import date

from ve_connect_dental.mapper import completed_cdt_codes, map_procedure, map_procedures


def _raw_procedure(**overrides) -> dict:
    raw = {
        "procedure_id": "1001",
        "cdt_code": "D2391",
        "tooth": "14",
        "surface": "O",
        "procedure_date": date(2026, 3, 1),
        "status_code": 2,  # complete
    }
    raw.update(overrides)
    return raw


def test_map_procedure_produces_expected_shape():
    row = map_procedure(_raw_procedure(), patient_id="pat_1", clinic_id="clinic_alnoor_001")
    assert row == {
        "history_id": "dph_clinic_alnoor_001_opendental_1001",
        "patient_id": "pat_1",
        "clinic_id": "clinic_alnoor_001",
        "source": "opendental",
        "cdt_code": "D2391",
        "tooth": "14",
        "surface": "O",
        "procedure_date": "2026-03-01",
        "status": "complete",
        "raw_reference_id": "1001",
    }


def test_map_procedure_unknown_status_code_degrades_to_unknown_not_raise():
    row = map_procedure(_raw_procedure(status_code=999), patient_id="pat_1", clinic_id="clinic_alnoor_001")
    assert row["status"] == "unknown"


def test_map_procedure_treatment_planned_is_distinct_from_complete():
    row = map_procedure(_raw_procedure(status_code=1), patient_id="pat_1", clinic_id="clinic_alnoor_001")
    assert row["status"] == "treatment_planned"


def test_map_procedure_handles_missing_date():
    row = map_procedure(_raw_procedure(procedure_date=None), patient_id="pat_1", clinic_id="clinic_alnoor_001")
    assert row["procedure_date"] is None


def test_map_procedures_maps_every_row():
    raws = [_raw_procedure(procedure_id="1"), _raw_procedure(procedure_id="2", cdt_code="D3330")]
    rows = map_procedures(raws, patient_id="pat_1", clinic_id="clinic_alnoor_001")
    assert [r["cdt_code"] for r in rows] == ["D2391", "D3330"]


def test_completed_cdt_codes_filters_out_non_complete_statuses():
    mapped = [
        map_procedure(_raw_procedure(procedure_id="1", cdt_code="D2391", status_code=2), patient_id="p", clinic_id="c"),
        map_procedure(_raw_procedure(procedure_id="2", cdt_code="D3330", status_code=1), patient_id="p", clinic_id="c"),
    ]
    assert completed_cdt_codes(mapped) == ["D2391"]
