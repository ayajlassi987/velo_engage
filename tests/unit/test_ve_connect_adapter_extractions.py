"""Covers the deterministic extraction-ID helper moved into ve_connect
(the DGX-side ve_clinical_intel service upserts through ve_connect's HTTP
API rather than a direct DB connection — see ve_clinical_intel/main.py's
module docstring)."""

import ve_connect.adapter as adapter


def test_deterministic_extraction_id_is_stable():
    a = adapter._deterministic_extraction_id("doc123", "clinic_alnoor_001")
    b = adapter._deterministic_extraction_id("doc123", "clinic_alnoor_001")
    assert a == b
    assert len(a) == 32


def test_deterministic_extraction_id_differs_by_document():
    a = adapter._deterministic_extraction_id("doc1", "clinic_alnoor_001")
    b = adapter._deterministic_extraction_id("doc2", "clinic_alnoor_001")
    assert a != b
