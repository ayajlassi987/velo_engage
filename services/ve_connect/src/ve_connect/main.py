from dotenv import load_dotenv; load_dotenv()
import logging
from fastapi import FastAPI, BackgroundTasks, Response
from pydantic import BaseModel
from ve_connect.auth import router as auth_router, _db, epic_configuration_status
from ve_connect.adapter import pull_patient_cohort, _pull_clinical_notes, pull_raw_resources, upsert_clinical_extraction
from ve_connect.epic_bulk import run_bulk_export
import os
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="ve_connect")
app.include_router(auth_router)


@app.post("/pull-cohort")
async def pull_cohort(background_tasks: BackgroundTasks, max_patients: int = 100):
    background_tasks.add_task(pull_patient_cohort, max_patients)
    return {"status": "started", "pulling_up_to": max_patients}


@app.post("/pull-bulk")
async def pull_bulk(background_tasks: BackgroundTasks, group_id: str | None = None):
    background_tasks.add_task(run_bulk_export, group_id)
    return {"status": "started", "group_id": group_id or "default (EPIC_BULK_GROUP_ID)"}


@app.post("/pull-bulk-sync")
async def pull_bulk_sync(group_id: str | None = None):
    """Synchronous variant for the daily Temporal pipeline (ve_orchestrator's
    pull_epic_data activity) — it needs the real processed count and needs to
    know the pull actually finished before rule evaluation runs, which the
    fire-and-forget /pull-bulk can't provide."""
    try:
        processed = run_bulk_export(group_id)
        return {"status": "complete", "processed": processed}
    except Exception as exc:
        logging.getLogger(__name__).error(f"Synchronous bulk pull failed: {exc}", exc_info=True)
        return {"status": "failed", "error": str(exc)}


@app.get("/patients/{patient_id}/raw")
async def patient_raw(patient_id: str):
    """Diagnostic-only: the exact raw FHIR resources pulled for a patient,
    before map_patient_to_features() maps/derives anything from them — see
    adapter.py's pull_raw_resources() for why this exists and what it does
    and doesn't persist (nothing; same discipline as /clinical-notes below)."""
    try:
        return {"patient_id": patient_id, "resources": pull_raw_resources(patient_id)}
    except Exception as exc:
        logging.getLogger(__name__).warning(f"Raw resource pull failed for {patient_id}: {exc}")
        return {"patient_id": patient_id, "resources": None, "error": str(exc)}


@app.get("/patients/{patient_id}/clinical-notes")
async def clinical_notes(patient_id: str):
    """For Task 2's clinical-note-intelligence service (runs on the DGX,
    calls this over the network) — notes are returned here and never
    written to ve_connect's own database; this endpoint is the only place
    raw note text exists on this machine, and only transiently in the
    HTTP response body."""
    notes, search_error = _pull_clinical_notes(patient_id)
    return {"patient_id": patient_id, "notes": notes, "search_error": search_error}


class ClinicalExtractionIn(BaseModel):
    patient_id: str
    clinic_id: str
    document_reference_id: str
    note_date: str | None = None
    diagnoses: list = []
    medications: list = []
    procedures: list = []
    follow_up_recommendations: list = []
    clinical_risks: list = []
    safety_check_passed: bool
    validation_flags: list = []


@app.post("/clinical-extractions")
async def clinical_extractions(body: ClinicalExtractionIn):
    """Write path for Task 2's DGX-side extraction service — see the
    /patients/{id}/clinical-notes read path above. The DGX has no direct
    route to Postgres (no root there to set up a VPN network interface),
    so this HTTP call is how extraction results get persisted instead."""
    extraction_id = upsert_clinical_extraction(
        patient_id=body.patient_id, clinic_id=body.clinic_id,
        document_reference_id=body.document_reference_id, note_date=body.note_date,
        diagnoses=body.diagnoses, medications=body.medications, procedures=body.procedures,
        follow_up_recommendations=body.follow_up_recommendations, clinical_risks=body.clinical_risks,
        safety_check_passed=body.safety_check_passed, validation_flags=body.validation_flags,
    )
    return {"extraction_id": extraction_id}


@app.get("/auth/status")
async def auth_status():
    configuration = epic_configuration_status()
    if not configuration["configured"]:
        return {
            "authorized": False,
            "configured": False,
            "missing": configuration["missing"],
            "action": "Configure services/ve_connect/.env, then visit /auth/login",
        }
    conn = _db(); cur = conn.cursor()
    cur.execute("SELECT expires_at, scope FROM epic_tokens WHERE clinic_id=%s",
                (os.getenv("CLINIC_ID","clinic_alnoor_001"),))
    row = cur.fetchone(); cur.close(); conn.close()
    if not row:
        return {"authorized": False, "action": "Visit /auth/login"}
    expires_at, scope = row
    return {"authorized": True, "token_valid": datetime.now(timezone.utc) < expires_at,
            "expires_at": expires_at.isoformat(), "scope": scope}


@app.get("/health")
async def health():
    configuration = epic_configuration_status()
    return {
        "status": "ok" if configuration["configured"] else "degraded",
        "service": "ve_connect",
        "epic_configured": configuration["configured"],
        "missing": configuration["missing"],
    }


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)
