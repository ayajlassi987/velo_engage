"""ve_connect_dental — PROTOTYPE. See README.md before treating anything
this service produces as real-clinic data. FastAPI app mirrors ve_connect's
main.py shape (background-task pull endpoint + a raw diagnostic endpoint),
but for OpenDental instead of Epic, and entirely independent of it."""

from dotenv import load_dotenv; load_dotenv()
import logging

from fastapi import BackgroundTasks, FastAPI, HTTPException

from ve_connect_dental.adapter import pull_patient_dental_history
from ve_connect_dental.config import build_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = FastAPI(title="ve_connect_dental (prototype)")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ve_connect_dental", "prototype": True}


@app.post("/pull-dental-history/{patient_id}")
async def pull_dental_history(patient_id: str, background_tasks: BackgroundTasks):
    """Fire-and-forget, mirrors ve_connect's /pull-cohort — the daily
    pipeline shouldn't block on this any more than it blocks on Epic."""
    client = build_client()
    background_tasks.add_task(pull_patient_dental_history, client, patient_id)
    return {"status": "started", "patient_id": patient_id}


@app.get("/patients/{patient_id}/dental-history/raw")
async def raw_dental_history(patient_id: str):
    """Diagnostic only, same purpose as ve_connect's GET /patients/{id}/raw:
    see exactly what the configured PMS transport returns before anything
    is mapped, without writing anything to Postgres or disk. Useful for
    confirming Phase A's schema assumptions (README.md, step 3) against a
    real local instance."""
    client = build_client()
    try:
        return {
            "patient": client.get_patient(patient_id),
            "procedures": client.get_procedures(patient_id),
            "appointments": client.get_appointments(patient_id),
        }
    except Exception as exc:
        logger.error(f"Raw dental pull failed for {patient_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=502, detail=str(exc))
