"""ve_treatment_planner — PROTOTYPE. Thin FastAPI front door onto Temporal:
starts a case's workflow, relays signals, and relays the current-state
query. All actual logic lives in workflows.py/activities.py/pathway_engine.py
— this module is pure plumbing, deliberately, so the one part of this
service worth trusting (the state machine) isn't tangled up with HTTP
concerns."""

from dotenv import load_dotenv; load_dotenv()
import logging
import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from temporalio.client import Client

from ve_treatment_planner.workflows import TreatmentPathwayWorkflow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = FastAPI(title="ve_treatment_planner (prototype)")

TASK_QUEUE = "velo-dental-task-queue"
_client: Client | None = None


async def _temporal_client() -> Client:
    global _client
    if _client is None:
        _client = await Client.connect(os.getenv("TEMPORAL_ADDRESS", "localhost:7233"), namespace="default")
    return _client


class StartCaseRequest(BaseModel):
    pathway_id: str
    patient_id: str
    clinic_id: str
    tooth: str | None = None


class DecisionRequest(BaseModel):
    chosen_state: str
    accepted: bool
    override_reason: str | None = None


def _case_id(pathway_id: str, patient_id: str, clinic_id: str, tooth: str | None) -> str:
    # Deterministic, not random — one workflow per (pathway, patient, tooth)
    # so re-POSTing /cases for the same case is a no-op start rather than a
    # duplicate, matching this project's general idempotent-ID discipline.
    suffix = tooth or "case"
    return f"dental_{clinic_id}_{pathway_id}_{patient_id}_{suffix}"


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ve_treatment_planner", "prototype": True}


@app.post("/cases")
async def start_case(req: StartCaseRequest):
    case_id = _case_id(req.pathway_id, req.patient_id, req.clinic_id, req.tooth)
    client = await _temporal_client()
    await client.start_workflow(
        TreatmentPathwayWorkflow.run,
        args=[case_id, req.pathway_id, req.patient_id, req.clinic_id, req.tooth],
        id=case_id,
        task_queue=TASK_QUEUE,
    )
    return {"case_id": case_id, "status": "started"}


@app.post("/cases/{case_id}/events")
async def record_event(case_id: str):
    client = await _temporal_client()
    handle = client.get_workflow_handle(case_id)
    try:
        await handle.signal(TreatmentPathwayWorkflow.record_event)
    except Exception as exc:
        logger.error(f"Failed to signal case {case_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=404, detail=f"No active case workflow for {case_id}")
    return {"status": "signaled"}


@app.post("/cases/{case_id}/decision")
async def record_decision(case_id: str, req: DecisionRequest):
    if not req.accepted and not req.override_reason:
        raise HTTPException(status_code=400, detail="override_reason is required when overriding a suggestion")
    client = await _temporal_client()
    handle = client.get_workflow_handle(case_id)
    try:
        await handle.signal(TreatmentPathwayWorkflow.record_decision, args=[req.chosen_state, req.accepted, req.override_reason])
    except Exception as exc:
        logger.error(f"Failed to signal decision for case {case_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=404, detail=f"No active case workflow for {case_id}")
    return {"status": "signaled"}


@app.get("/cases/{case_id}")
async def get_case(case_id: str):
    client = await _temporal_client()
    handle = client.get_workflow_handle(case_id)
    try:
        return await handle.query(TreatmentPathwayWorkflow.get_current_state)
    except Exception as exc:
        logger.error(f"Failed to query case {case_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=404, detail=f"No active case workflow for {case_id}")
