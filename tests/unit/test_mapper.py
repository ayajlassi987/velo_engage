"""ve_connect/mapper.py — translates raw Epic FHIR resources into
PatientFeatures. Fixtures use realistic Epic-shaped FHIR dicts, including
the two real bugs found and fixed against live Epic data this project
(extract_last_visit no longer checks Encounter.class, since Epic's
proprietary coding system there never matched the old ambulatory/outpatient
filter — see mapper.py's own docstring)."""

from datetime import date, timedelta

from ve_connect.mapper import (
    extract_coverage_end,
    extract_icd10_codes,
    extract_last_procedure,
    extract_last_visit,
    extract_phone,
    map_patient_to_features,
)


def test_extract_icd10_codes_filters_by_active_status():
    conditions = [
        {
            "clinicalStatus": {"coding": [{"code": "active"}]},
            "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "E11"}]},
        },
        {
            "clinicalStatus": {"coding": [{"code": "resolved"}]},
            "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "I10"}]},
        },
    ]
    assert extract_icd10_codes(conditions) == ["E11"]


def test_extract_icd10_codes_ignores_non_icd10_systems():
    conditions = [{
        "clinicalStatus": {"coding": [{"code": "active"}]},
        "code": {"coding": [{"system": "http://snomed.info/sct", "code": "12345"}]},
    }]
    assert extract_icd10_codes(conditions) == []


def test_extract_icd10_codes_dedupes():
    conditions = [
        {"clinicalStatus": {"coding": [{"code": "active"}]},
         "code": {"coding": [{"system": "icd-10-cm", "code": "E11"}]}},
        {"clinicalStatus": {"coding": [{"code": "recurrence"}]},
         "code": {"coding": [{"system": "icd-10-cm", "code": "E11"}]}},
    ]
    assert extract_icd10_codes(conditions) == ["E11"]


def test_extract_last_visit_ignores_encounter_class_uses_only_status_and_date():
    # Epic populates Encounter.class with its own proprietary coding system
    # (not standard FHIR v3-ActCode) — this must NOT be used as a filter,
    # confirmed live against real Epic data (see mapper.py's docstring).
    encounters = [
        {
            "status": "finished",
            "class": {"system": "urn:oid:1.2.840.114350...", "code": "13", "display": "Support OP Encounter"},
            "period": {"end": "2023-03-15T10:00:00Z"},
        },
        {
            "status": "cancelled",
            "period": {"end": "2024-01-01T10:00:00Z"},
        },
    ]
    assert extract_last_visit(encounters) == date(2023, 3, 15)


def test_extract_last_visit_picks_most_recent():
    encounters = [
        {"status": "finished", "period": {"end": "2022-01-01T00:00:00Z"}},
        {"status": "completed", "period": {"end": "2024-06-15T00:00:00Z"}},
        {"status": "finished", "period": {"end": "2023-01-01T00:00:00Z"}},
    ]
    assert extract_last_visit(encounters) == date(2024, 6, 15)


def test_extract_last_visit_returns_none_when_no_completed_encounters():
    encounters = [{"status": "planned", "period": {"end": "2024-01-01T00:00:00Z"}}]
    assert extract_last_visit(encounters) is None


def test_extract_last_procedure_returns_type_and_date():
    procedures = [
        {"status": "completed", "performedDateTime": "2023-05-01T00:00:00Z",
         "code": {"text": "Dental cleaning"}},
        {"status": "completed", "performedDateTime": "2024-02-01T00:00:00Z",
         "code": {"text": "Root canal"}},
    ]
    proc_type, proc_date = extract_last_procedure(procedures)
    assert proc_type == "Root canal"
    assert proc_date == date(2024, 2, 1)


def test_extract_last_procedure_ignores_incomplete():
    procedures = [{"status": "in-progress", "performedDateTime": "2024-01-01T00:00:00Z",
                   "code": {"text": "Surgery"}}]
    assert extract_last_procedure(procedures) == (None, None)


def test_extract_coverage_end_only_active_coverage():
    coverages = [
        {"status": "active", "period": {"end": "2026-12-31"}},
        {"status": "cancelled", "period": {"end": "2030-01-01"}},
    ]
    assert extract_coverage_end(coverages) == date(2026, 12, 31)


def test_extract_phone_prefers_mobile():
    patient = {"telecom": [
        {"system": "phone", "use": "home", "value": "111"},
        {"system": "phone", "use": "mobile", "value": "222"},
    ]}
    assert extract_phone(patient) == "222"


def test_extract_phone_falls_back_to_any_phone():
    patient = {"telecom": [{"system": "phone", "value": "333"}]}
    assert extract_phone(patient) == "333"


def test_extract_phone_returns_none_when_no_phone():
    patient = {"telecom": [{"system": "email", "value": "a@b.com"}]}
    assert extract_phone(patient) is None


def test_map_patient_to_features_builds_full_row():
    dob = (date.today() - timedelta(days=365 * 40)).isoformat()
    patient = {
        "id": "erXuFYUfucBZaryVksYEcMg3",
        "birthDate": dob,
        "gender": "female",
        "name": [{"use": "official", "given": ["Camila"], "family": "Lopez"}],
        "telecom": [{"system": "phone", "use": "mobile", "value": "+971500000000"}],
        "communication": [{"language": {"coding": [{"code": "en"}]}, "preferred": True}],
    }
    conditions = [{"clinicalStatus": {"coding": [{"code": "active"}]},
                   "code": {"coding": [{"system": "icd-10-cm", "code": "E28.2"}]}}]
    encounters = [{"status": "finished", "period": {"end": "2023-01-01T00:00:00Z"}}]
    procedures = []
    careplans = [{"status": "active"}]
    coverages = []

    features = map_patient_to_features(
        patient, conditions, encounters, procedures, careplans, coverages,
        clinic_id="clinic_alnoor_001",
    )

    assert features["patient_id"] == "erXuFYUfucBZaryVksYEcMg3"
    assert features["clinic_id"] == "clinic_alnoor_001"
    assert features["condition_codes"] == ["E28.2"]
    assert features["open_treatment_plan_flag"] is True
    assert features["age"] == 40
    assert features["sex"] == "female"
    assert features["_first_name"] == "Camila"
    assert features["_last_name"] == "Lopez"
    assert features["_phone_e164"] == "+971500000000"
    assert features["_language"] == "en"
