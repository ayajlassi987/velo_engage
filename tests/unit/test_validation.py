from ve_clinical_intel.validation import validate


def test_valid_extraction_passes_through_unchanged():
    extraction = {
        "diagnoses": ["E11 Type 2 diabetes"],
        "medications": ["Metformin 500mg"],
        "procedures": [],
        "follow_up_recommendations": ["Recheck A1C in 3 months"],
        "clinical_risks": [],
    }
    cleaned, flags = validate(extraction)
    assert cleaned["diagnoses"] == ["E11 Type 2 diabetes"]
    assert cleaned["medications"] == ["Metformin 500mg"]
    # No flag about the ICD-10 shape, since "E11" matches the pattern.
    assert not any("does not start with a recognizable ICD-10" in f for f in flags)


def test_missing_key_defaults_to_empty_list_and_flags():
    extraction = {"diagnoses": ["E11"]}  # everything else missing
    cleaned, flags = validate(extraction)
    assert cleaned["medications"] == []
    assert cleaned["procedures"] == []
    assert any("'medications' missing" in f for f in flags)


def test_wrong_type_defaults_to_empty_list_and_flags():
    extraction = {
        "diagnoses": "E11 diabetes",  # string instead of list — malformed
        "medications": [], "procedures": [], "follow_up_recommendations": [], "clinical_risks": [],
    }
    cleaned, flags = validate(extraction)
    assert cleaned["diagnoses"] == []
    assert any("'diagnoses' was not a list" in f for f in flags)


def test_unexpected_extra_key_is_flagged_not_dropped_silently():
    extraction = {
        "diagnoses": [], "medications": [], "procedures": [], "follow_up_recommendations": [],
        "clinical_risks": [], "unexpected_hallucinated_field": "something",
    }
    _, flags = validate(extraction)
    assert any("unexpected_hallucinated_field" in f for f in flags)


def test_empty_medication_names_removed_and_flagged():
    extraction = {
        "diagnoses": [], "medications": ["Metformin", "", "  "], "procedures": [],
        "follow_up_recommendations": [], "clinical_risks": [],
    }
    cleaned, flags = validate(extraction)
    assert cleaned["medications"] == ["Metformin"]
    assert any("empty medication name" in f for f in flags)


def test_non_icd10_shaped_diagnosis_is_flagged_not_dropped():
    extraction = {
        "diagnoses": ["diabetes mellitus"],  # no code prefix at all
        "medications": [], "procedures": [], "follow_up_recommendations": [], "clinical_risks": [],
    }
    cleaned, flags = validate(extraction)
    # Not dropped — a descriptive diagnosis without a code is still real data.
    assert cleaned["diagnoses"] == ["diabetes mellitus"]
    assert any("does not start with a recognizable ICD-10-shaped code" in f for f in flags)


def test_validate_never_raises_on_completely_empty_dict():
    cleaned, flags = validate({})
    assert cleaned == {
        "diagnoses": [], "medications": [], "procedures": [],
        "follow_up_recommendations": [], "clinical_risks": [],
    }
    assert len(flags) == 5  # all 5 required keys flagged as missing
