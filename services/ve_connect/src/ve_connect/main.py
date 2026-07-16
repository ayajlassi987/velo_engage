from dotenv import load_dotenv; load_dotenv()
import logging
from fastapi import FastAPI, BackgroundTasks, Response
from ve_connect.auth import router as auth_router, _db, epic_configuration_status
from ve_connect.adapter import pull_patient_cohort
from ve_connect.epic_bulk import run_bulk_export
import os
from datetime import datetime

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
    return {"authorized": True, "token_valid": datetime.utcnow() < expires_at,
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
