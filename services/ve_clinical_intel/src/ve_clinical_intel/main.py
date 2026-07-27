"""Clinical note intelligence service (Task 2) — runs on the DGX Spark,
alongside the team's model_server (MedGemma) and the NemoGuard NIM.

Deliberately NOT part of the main docker-compose.dev.yml stack: this
service needs GPU-local calls to MedGemma/NemoGuard, which only exist on
the DGX. It reaches back to the main machine's ve_connect over the network
(see PROJECT_STATUS.md's Part A connectivity requirement) — inference is
local, the data isn't. No direct Postgres connection: the DGX has no root
access to set up a VPN network interface for raw TCP, only a rootless
Tailscale userspace proxy for HTTP, so both reads (clinical notes) and
writes (extractions) go through ve_connect's HTTP API instead.
"""

from dotenv import load_dotenv; load_dotenv()

import logging
import os

import httpx
from fastapi import FastAPI

from ve_clinical_intel import medgemma_client, nemoguard_client
from ve_clinical_intel.validation import validate

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="ve_clinical_intel")

CLINIC_ID = os.getenv("CLINIC_ID", "clinic_alnoor_001")
# Must be set to the main machine's reachable address (its Tailscale IP) —
# no working default, since "http://ve_connect:8000" (the docker-internal
# DNS name used by services on the *main* machine) doesn't resolve from the
# DGX. Traffic to it may need HTTP_PROXY/HTTPS_PROXY set to Tailscale's
# local userspace proxy if the DGX has no root to run a real TUN interface.
VE_CONNECT_URL = os.getenv("VE_CONNECT_URL")


def _fetch_clinical_notes(patient_id: str) -> tuple[list[dict], str | None]:
    if not VE_CONNECT_URL:
        raise RuntimeError(
            "VE_CONNECT_URL is not set — see PROJECT_STATUS.md Part A for the "
            "main machine's reachable address."
        )
    # ve_connect fetches each DocumentReference's Binary sequentially against
    # the real Epic sandbox API, over the network (Tailscale) — patients with
    # more history can take a while. 30s proved too tight for a 74-year-old
    # patient with a longer record than the one this was first tested against.
    with httpx.Client(timeout=90.0) as client:
        response = client.get(f"{VE_CONNECT_URL}/patients/{patient_id}/clinical-notes")
        response.raise_for_status()
        body = response.json()
        return body["notes"], body.get("search_error")


def _upsert_extraction(patient_id: str, note: dict, cleaned: dict, flags: list[str], safety_passed: bool) -> str:
    payload = {
        "patient_id": patient_id,
        "clinic_id": CLINIC_ID,
        "document_reference_id": note["document_reference_id"],
        "note_date": note.get("note_date"),
        "diagnoses": cleaned.get("diagnoses", []),
        "medications": cleaned.get("medications", []),
        "procedures": cleaned.get("procedures", []),
        "follow_up_recommendations": cleaned.get("follow_up_recommendations", []),
        "clinical_risks": cleaned.get("clinical_risks", []),
        "safety_check_passed": safety_passed,
        "validation_flags": flags,
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.post(f"{VE_CONNECT_URL}/clinical-extractions", json=payload)
        response.raise_for_status()
        return response.json()["extraction_id"]


def process_patient(patient_id: str) -> dict:
    """Orchestrates the full pipeline for one patient's notes: fetch ->
    safety-gate -> extract -> validate -> upsert. Note text and MedGemma's
    raw response are never written to disk or returned from this
    function — only counts and extraction IDs, per the retention decision
    in PROJECT_STATUS.md. Upsert goes through ve_connect's HTTP API, not a
    direct DB connection — see this module's docstring."""
    notes, search_error = _fetch_clinical_notes(patient_id)
    results = {
        "patient_id": patient_id, "notes_found": len(notes), "processed": 0,
        "blocked": 0, "errors": 0, "extraction_ids": [], "search_error": search_error,
    }

    for note in notes:
        # note_text/raw_extraction are scoped entirely to one loop
        # iteration and never returned or written to disk — the
        # retention decision in PROJECT_STATUS.md. The whole per-note
        # pipeline is inside one try/except so a malformed note (e.g.
        # missing "text") is counted as an error and skipped, not left to
        # crash processing for the rest of this patient's notes.
        try:
            note_text = note["text"]
            if not nemoguard_client.check_safety(note_text):
                logger.warning(f"Note {note.get('document_reference_id')} blocked by safety check — skipped, not sent to MedGemma")
                results["blocked"] += 1
                continue

            raw_extraction = medgemma_client.extract_structured_data(note_text)
            cleaned, flags = validate(raw_extraction)
            extraction_id = _upsert_extraction(patient_id, note, cleaned, flags, safety_passed=True)
            results["extraction_ids"].append(extraction_id)
            results["processed"] += 1
        except Exception as exc:
            logger.error(f"Failed to process note {note.get('document_reference_id')} for {patient_id}: {exc}", exc_info=True)
            results["errors"] += 1

    return results


@app.post("/process-patient/{patient_id}")
async def process_patient_endpoint(patient_id: str):
    return process_patient(patient_id)


@app.get("/health")
async def health():
    checks = {"service": "ok"}
    try:
        checks["medgemma"] = medgemma_client.health_check()
    except Exception as exc:
        checks["medgemma"] = f"unreachable: {exc}"
    try:
        checks["nemoguard"] = nemoguard_client.health_check()
    except Exception as exc:
        checks["nemoguard"] = f"unreachable: {exc}"
    checks["ve_connect_configured"] = bool(VE_CONNECT_URL)
    return checks
