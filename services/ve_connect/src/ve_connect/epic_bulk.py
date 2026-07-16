"""
Epic Bulk Data Export ($export) — SMART Backend Services flow.

Pulls a full patient population (a Group) in one export job instead of the
per-patient API calls pull_patient_roster() makes in adapter.py. That path
still exists and keeps working unchanged — this is an additional ingestion
path onto the same patient_features/staging_patients tables, selected
explicitly (via /pull-bulk or run_bulk_export.py), not a replacement.
"""

import json, logging, time
from collections import defaultdict

import httpx
from ve_connect.adapter import CADENCE, CLINIC_ID, _db, _upsert
from ve_connect.bulk_auth import bulk_settings, get_bulk_token
from ve_connect.mapper import map_patient_to_features

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 10
POLL_TIMEOUT_SECONDS = 3600
RESOURCE_TYPES = "Patient,Condition,Encounter,Procedure,CarePlan,Coverage"


def _kickoff(group_id: str) -> str:
    settings = bulk_settings()
    url = f"{settings.fhir_base.rstrip('/')}/Group/{group_id}/$export"
    headers = {
        "Authorization": f"Bearer {get_bulk_token()}",
        "Accept": "application/fhir+json",
        "Prefer": "respond-async",
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, headers=headers, params={"_type": RESOURCE_TYPES})
        if resp.status_code >= 400:
            logger.error("Epic bulk kickoff rejected: url=%s status=%s body=%s", url, resp.status_code, resp.text)
        resp.raise_for_status()
        location = resp.headers.get("Content-Location")
        if not location:
            raise RuntimeError("Epic accepted the kickoff but returned no Content-Location polling URL")
        logger.info(f"Bulk export kicked off for Group/{group_id}: {location}")
        return location


def _poll_until_complete(status_url: str) -> dict:
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    with httpx.Client(timeout=30.0) as client:
        while time.monotonic() < deadline:
            resp = client.get(status_url, headers={
                "Authorization": f"Bearer {get_bulk_token()}",
                "Accept": "application/json",
            })
            if resp.status_code == 202:
                logger.info(f"Bulk export in progress: {resp.headers.get('X-Progress', '...')}")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue
            if resp.status_code == 200:
                return resp.json()
            logger.error("Epic bulk status check failed: status=%s body=%s", resp.status_code, resp.text)
            resp.raise_for_status()
    raise TimeoutError(f"Bulk export did not complete within {POLL_TIMEOUT_SECONDS}s")


def _download_ndjson(url: str) -> list[dict]:
    with httpx.Client(timeout=120.0) as client:
        resp = client.get(url, headers={
            "Authorization": f"Bearer {get_bulk_token()}",
            "Accept": "application/fhir+ndjson",
        })
        resp.raise_for_status()
        return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def _delete_export(status_url: str) -> None:
    """Epic asks clients to delete completed export jobs to free server-side
    storage — best-effort, never blocks the actual data already downloaded."""
    try:
        with httpx.Client(timeout=15.0) as client:
            client.delete(status_url, headers={"Authorization": f"Bearer {get_bulk_token()}"})
    except Exception as exc:
        logger.warning(f"Could not delete completed export job {status_url}: {exc}")


def _log_errors(manifest: dict) -> None:
    for issue in manifest.get("error", []):
        logger.warning(f"Bulk export reported an error/deleted file: {issue}")


def _patient_ref_id(resource: dict) -> str | None:
    ref = resource.get("subject", {}).get("reference", "") or resource.get("patient", {}).get("reference", "")
    return ref.split("/", 1)[1] if ref.startswith("Patient/") else None


def run_bulk_export(group_id: str | None = None) -> int:
    """Kicks off, polls, downloads, normalizes, and upserts a full Group
    $export. Returns the number of patients written."""
    group_id = group_id or bulk_settings().group_id
    status_url = _kickoff(group_id)
    manifest = _poll_until_complete(status_url)
    _log_errors(manifest)

    by_type: dict[str, list[dict]] = defaultdict(list)
    for f in manifest.get("output", []):
        by_type[f["type"]].extend(_download_ndjson(f["url"]))
    logger.info("Downloaded: " + ", ".join(f"{k}={len(v)}" for k, v in by_type.items()))

    patients = {p["id"]: p for p in by_type.get("Patient", [])}
    by_patient: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for rtype in ("Condition", "Encounter", "Procedure", "CarePlan", "Coverage"):
        for resource in by_type.get(rtype, []):
            pid = _patient_ref_id(resource)
            if pid:
                by_patient[pid][rtype].append(resource)

    conn = _db(); processed = 0
    for pid, patient in patients.items():
        try:
            features = map_patient_to_features(
                patient,
                conditions=by_patient[pid]["Condition"],
                encounters=by_patient[pid]["Encounter"],
                procedures=by_patient[pid]["Procedure"],
                careplans=by_patient[pid]["CarePlan"],
                coverages=by_patient[pid]["Coverage"],
                clinic_id=CLINIC_ID, cadence_baseline_days=CADENCE,
            )
            _upsert(conn, features)
            processed += 1
            logger.info(f"  ✓ {pid}")
        except Exception as e:
            logger.error(f"  ✗ {pid}: {e}", exc_info=True)
            continue

    conn.commit(); conn.close()
    _delete_export(status_url)
    logger.info(f"Bulk export complete: {processed}/{len(patients)} patients written")
    return processed
