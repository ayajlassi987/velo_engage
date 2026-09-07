"""Maps client.py's plain dicts (already normalized away from OpenDental's
raw column names) into the rows dental_procedure_history actually stores.
Pure functions, no I/O — mirrors ve_connect's mapper.py being separately
testable from fhir_client.py/adapter.py.

PROTOTYPE: the ProcStatus enum below reflects OpenDental's commonly
documented status codes at the time this was written. Confirm the real
values against your own instance (README.md Phase A, step 3) — an
unrecognized code degrades to "unknown" rather than raising, so one bad
mapping doesn't block ingestion of everything else, same fault-tolerance
philosophy as ve_connect's _careplans_or_empty().
"""

from datetime import date, datetime
from typing import Any

# OpenDental ProcStatus -> this platform's own status vocabulary. Only
# "complete" procedures should ever drive a treatment-pathway state
# transition (a treatment-planned-but-not-done procedure hasn't actually
# happened yet) — see pathway_engine.py's trigger matching, which filters
# on this field.
_PROC_STATUS = {
    1: "treatment_planned",
    2: "complete",
    3: "existing_current",
    4: "existing_other",
    5: "referred",
    6: "ordered_planned",
    7: "condition",
    8: "deleted",
}


def _coerce_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    return str(value)[:10]


def map_procedure(raw: dict[str, Any], *, patient_id: str, clinic_id: str) -> dict[str, Any]:
    """One client.py procedure dict -> one dental_procedure_history row."""
    return {
        "history_id": f"dph_{clinic_id}_opendental_{raw['procedure_id']}",
        "patient_id": patient_id,
        "clinic_id": clinic_id,
        "source": "opendental",
        "cdt_code": raw["cdt_code"],
        "tooth": raw.get("tooth"),
        "surface": raw.get("surface"),
        "procedure_date": _coerce_date(raw.get("procedure_date")),
        "status": _PROC_STATUS.get(raw.get("status_code"), "unknown"),
        "raw_reference_id": raw["procedure_id"],
    }


def map_procedures(raw_procedures: list[dict[str, Any]], *, patient_id: str, clinic_id: str) -> list[dict[str, Any]]:
    return [map_procedure(p, patient_id=patient_id, clinic_id=clinic_id) for p in raw_procedures]


def completed_cdt_codes(mapped_procedures: list[dict[str, Any]]) -> list[str]:
    """The subset pathway_engine.py's `procedure_performed` trigger actually
    cares about — only codes from procedures OpenDental itself marks
    complete, not treatment-planned/ordered ones that haven't happened."""
    return [p["cdt_code"] for p in mapped_procedures if p["status"] == "complete"]
