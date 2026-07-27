"""
Pulls a full patient cohort from Epic → maps to features → writes to Postgres.
Replaces seed_dummy_patients.py entirely once authorized.
"""

import base64, csv, hashlib, json, logging, os, sys
from datetime import date, timedelta
from pathlib import Path
import psycopg2
from ve_connect.fhir_client import get_resource, search_resources
from ve_connect.mapper import map_patient_to_features

for _candidate in (
    Path(__file__).resolve().parents[4] if len(Path(__file__).resolve().parents) > 4 else None,
    Path("/app"),
):
    if _candidate and (_candidate / "libs").is_dir():
        sys.path.insert(0, str(_candidate))
        break
from libs.ve_clients.vault_client import get_secret

logger = logging.getLogger(__name__)
CLINIC_ID = os.getenv("CLINIC_ID","clinic_alnoor_001")
CADENCE = int(os.getenv("CADENCE_BASELINE_DAYS",120))

# Every consent_class referenced by policies/opportunities/*.yml (mirrors
# scripts/seed_synthetic_phase1.py's CONSENT_CLASSES derivation — that
# script computes this set from POLICY_FAMILY_FLAGS, which is itself a
# hardcoded mirror of the same YAMLs, not a runtime YAML read; kept
# consistent with that existing precedent rather than adding a YAML
# dependency to this service). Previously only 'care_recall' was granted
# here, so every real Epic patient silently failed consent gating for any
# family using a different class (B, I, and others) — not because they
# lacked real consent, but because this placeholder never granted it.
REAL_PATIENT_CONSENT_CLASSES = [
    "care_recall", "care_coordination", "clinical_recall", "contextual_outreach",
    "digital_followup", "engagement", "household_outreach", "operational_offer",
    "preference_outreach", "promotional_outreach", "quality_followup",
]


def _db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST","localhost"), port=int(os.getenv("DB_PORT",5432)),
        dbname=os.getenv("DB_NAME","velodb"), user=get_secret("postgres", "user", "DB_USER") or "velo",
        password=get_secret("postgres", "password", "DB_PASSWORD") or "velo_secret",
    )


def _extract_patient_id(encounter: dict) -> str | None:
    reference = encounter.get("subject", {}).get("reference", "")
    if reference.startswith("Patient/"):
        return reference.split("/", 1)[1]
    return None


def _discover_patient_ids(lookback_days: int, max_patients: int) -> list[str]:
    """Epic's Patient search rejects an unrestricted query — confirmed live
    (real Epic sandbox error: "This resource requires demographics or _id
    parameter for searching."). Real EHR integrations discover an active
    cohort a different way: search a resource that Epic *does* allow broad
    date-range queries on (Encounter), then resolve each referenced patient
    by _id, which Epic's error message itself confirms is allowed."""
    since = (date.today() - timedelta(days=lookback_days)).isoformat()
    encounters = search_resources("Encounter", {"date": f"ge{since}", "_count": "100"})
    logger.info(f"Found {len(encounters)} encounters since {since}")

    patient_ids: list[str] = []
    seen: set[str] = set()
    for encounter in encounters:
        pid = _extract_patient_id(encounter)
        if pid and pid not in seen:
            seen.add(pid)
            patient_ids.append(pid)
        if len(patient_ids) >= max_patients:
            break
    return patient_ids


def _careplans_or_empty(pid: str) -> list[dict]:
    """CarePlan search has proven to be the least stable of the 5 resource
    types against this app's specific Epic authorization — it first
    rejected the query without a `category` param (error usefully listed
    valid codes), then rejected the specific category+status combination
    that seemed like the right general match ("Combination of parameters is
    not valid for any authorized sub-resource"), with no further detail to
    guess a correct combination from. Rather than keep trying category
    codes against live Epic requests, this degrades gracefully — one
    resource type being unavailable for this app's scope shouldn't block
    the other 4 resource types (which do work) from being pulled for a
    real patient. open_treatment_plan_flag just falls back to False."""
    try:
        return search_resources("CarePlan", {"patient": pid, "status": "active", "category": "38717003"})
    except Exception as exc:
        logger.warning(f"CarePlan search unavailable for {pid} ({exc}) — treating as no active care plan")
        return []


_HTML_TAG_RE = None  # compiled lazily, see _strip_html


def _strip_html(html: str) -> str:
    """Minimal, dependency-free tag stripping for text/html clinical note
    attachments — confirmed live against real Epic sandbox data that this
    is the dominant format (not text/plain as originally assumed; see
    PROJECT_STATUS.md). Not a full HTML parser, just enough to give
    MedGemma clean prose instead of markup noise."""
    global _HTML_TAG_RE
    if _HTML_TAG_RE is None:
        import re
        _HTML_TAG_RE = re.compile(r"<[^>]+>")
    import html as html_module
    text = _HTML_TAG_RE.sub(" ", html)
    return html_module.unescape(" ".join(text.split()))


def _is_clinical_note(ref: dict) -> bool:
    """Epic's DocumentReference search for a patient returns far more than
    actual clinical notes — confirmed live: HIPAA privacy notices, advance
    directives, and other administrative documents (with no real
    attachment content — data-absent-reason: not-applicable) are mixed in
    alongside real progress notes. Filters to the US Core
    'clinical-note' category so MedGemma only ever sees real notes."""
    for category in ref.get("category", []):
        for coding in category.get("coding", []):
            if coding.get("code") == "clinical-note":
                return True
    return False


def _pull_clinical_notes(pid: str) -> tuple[list[dict], str | None]:
    """Returns (notes, search_error) for a patient, for Task 2 (clinical
    note intelligence) — never persisted here or anywhere else in
    ve_connect, only returned over HTTP for the DGX-side extraction
    service to consume and discard after processing (see PROJECT_STATUS.md).

    Defensive in the same style as _careplans_or_empty: DocumentReference
    is a newly-scoped resource type for this app (see EPIC_SCOPES), not
    yet proven stable against this app's specific Epic authorization the
    way Condition/Encounter/Procedure/Coverage are — one unavailable
    resource type shouldn't block the rest of a patient pull. But unlike
    _careplans_or_empty (whose only consumer is a boolean flag, where
    "unavailable" and "false" are equally fine to conflate), a caller here
    genuinely needs to tell "confirmed zero notes" apart from "couldn't
    check" — an empty list for both silently masqueraded an Epic auth
    failure (expired interactive OAuth token, invalid_grant on refresh) as
    "this patient has no clinical notes" for every patient in a run. Hence
    search_error: None on a genuine (even if empty) search, a message
    otherwise.

    v1 scope, confirmed against real Epic sandbox data (not assumed):
    text/plain, XML (e.g. CCDA), and text/html (the dominant real-world
    format — Epic's actual notes came back as text/html, not text/plain)
    are decoded, with HTML tags stripped for cleaner LLM input. text/rtf
    and PDF/scanned-image notes are out of scope for v1 — both need a
    real parser (RTF, OCR) this pipeline doesn't have.
    """
    try:
        refs = search_resources("DocumentReference", {"patient": pid, "status": "current"})
    except Exception as exc:
        error = f"DocumentReference search unavailable for {pid}: {exc}"
        logger.warning(f"{error} — no notes pulled")
        return [], error

    notes = []
    for ref in refs:
        if not _is_clinical_note(ref):
            continue
        for attachment in ref.get("content", []):
            att = attachment.get("attachment", {})
            content_type = att.get("contentType", "")
            if content_type not in ("text/plain", "text/xml", "application/xml", "text/html"):
                continue
            binary_id = att.get("url", "").split("/")[-1]
            if not binary_id:
                continue
            try:
                binary = get_resource("Binary", binary_id)
            except Exception as exc:
                logger.warning(f"Binary fetch failed for {binary_id} ({exc})")
                continue
            try:
                raw = base64.b64decode(binary.get("data", ""))
            except Exception as exc:
                logger.warning(f"Binary {binary_id} data did not decode as base64 ({exc})")
                continue
            text = raw.decode("utf-8", errors="replace")
            if content_type == "text/html":
                text = _strip_html(text)
            notes.append({
                "document_reference_id": ref.get("id"),
                "content_type": content_type,
                "note_date": ref.get("date"),
                "text": text,
            })
    return notes, None


def _deterministic_extraction_id(document_reference_id: str, clinic_id: str) -> str:
    """Same deterministic-ID rationale as ve_orchestrator/ids.py — re-running
    the same note through the DGX pipeline (e.g. after a bug fix) upserts the
    same row instead of creating a duplicate."""
    raw = f"extraction:{document_reference_id}:{clinic_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def upsert_clinical_extraction(
    patient_id: str, clinic_id: str, document_reference_id: str, note_date,
    diagnoses: list, medications: list, procedures: list,
    follow_up_recommendations: list, clinical_risks: list,
    safety_check_passed: bool, validation_flags: list,
) -> str:
    """Writes Task 2's structured extraction to Postgres on ve_connect's
    behalf. Exists so the DGX-side ve_clinical_intel service never needs a
    direct database connection — only HTTP calls to ve_connect (see
    PROJECT_STATUS.md Part A: the DGX has no route to raw Postgres, and no
    root access there to set up one via a VPN's real network interface;
    routing this write through ve_connect's existing HTTP surface, same as
    the clinical-notes read, sidesteps that entirely)."""
    extraction_id = _deterministic_extraction_id(document_reference_id, clinic_id)
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO clinical_extractions
              (extraction_id, patient_id, clinic_id, document_reference_id, note_date,
               diagnoses, medications, procedures, follow_up_recommendations, clinical_risks,
               safety_check_passed, validation_flags)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (extraction_id) DO UPDATE SET
              diagnoses=EXCLUDED.diagnoses, medications=EXCLUDED.medications,
              procedures=EXCLUDED.procedures,
              follow_up_recommendations=EXCLUDED.follow_up_recommendations,
              clinical_risks=EXCLUDED.clinical_risks,
              safety_check_passed=EXCLUDED.safety_check_passed,
              validation_flags=EXCLUDED.validation_flags,
              extracted_at=now()
        """, (
            extraction_id, patient_id, clinic_id, document_reference_id, note_date,
            json.dumps(diagnoses), json.dumps(medications), json.dumps(procedures),
            json.dumps(follow_up_recommendations), json.dumps(clinical_risks),
            safety_check_passed, json.dumps(validation_flags),
        ))
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return extraction_id


def _resolve_and_upsert(conn, pid: str, patient: dict | None = None) -> None:
    """Fetch one patient's clinical resources, map to features, and upsert.
    Shared by pull_patient_cohort (Encounter-discovered IDs) and
    pull_patient_roster (externally-supplied IDs) so there's one place that
    defines what "resolve a patient" means, not two copies that can drift."""
    if patient is None:
        patient = get_resource("Patient", pid)
    features = map_patient_to_features(
        patient,
        conditions  = search_resources("Condition",   {"patient": pid, "clinical-status": "active"}),
        encounters  = search_resources("Encounter",   {"patient": pid, "status": "finished", "_count": "50"}),
        procedures  = search_resources("Procedure",   {"patient": pid, "status": "completed", "_count": "20"}),
        careplans   = _careplans_or_empty(pid),
        coverages   = search_resources("Coverage",    {"patient": pid, "status": "active"}),
        clinic_id=CLINIC_ID, cadence_baseline_days=CADENCE,
    )
    _upsert(conn, features)


def pull_patient_cohort(max_patients: int = 500, lookback_days: int | None = None) -> int:
    lookback_days = lookback_days or int(os.getenv("COHORT_LOOKBACK_DAYS", 365))
    logger.info(f"Starting Epic cohort pull for {CLINIC_ID} (lookback={lookback_days}d)")

    patient_ids = _discover_patient_ids(lookback_days, max_patients)
    logger.info(f"Discovered {len(patient_ids)} distinct patients via Encounter search")

    conn = _db(); processed = 0
    for pid in patient_ids:
        try:
            _resolve_and_upsert(conn, pid)
            processed += 1
            logger.info(f"  ✓ {pid}")
        except Exception as e:
            logger.error(f"  ✗ {pid}: {e}", exc_info=True)
            continue   # one bad patient shouldn't abort the whole cohort

    conn.commit(); conn.close()
    logger.info(f"Complete: {processed}/{len(patient_ids)} patients written")
    return processed


def _load_roster_ids(patient_ids: list[str] | None, roster_csv: str | Path | None) -> list[str]:
    if patient_ids:
        return list(dict.fromkeys(patient_ids))  # dedupe, preserve order
    if roster_csv:
        path = Path(roster_csv)
        if not path.exists():
            raise FileNotFoundError(f"Roster CSV not found: {path}")
        with open(path) as f:
            reader = csv.DictReader(f)
            col = next(
                (c for c in (reader.fieldnames or [])
                 if c.lower() in ("patient_id", "fhir_id", "id", "epic_id")),
                None,
            )
            if not col:
                raise ValueError(
                    f"No patient ID column found in {path}. "
                    f"Expected one of: patient_id, fhir_id, id, epic_id"
                )
            return list(dict.fromkeys(row[col] for row in reader if row[col]))
    return []


def pull_patient_roster(
    patient_ids: list[str] | None = None,
    roster_csv: str | Path | None = None,
    batch_size: int = 50,
) -> int:
    """Resolves a pre-supplied list of patient IDs — from any source: a
    sandbox test-patient list, a clinic-provided CSV export, or eventually
    Bulk Data Export output — via the confirmed-working `_id` batch search
    (see PROJECT_STATUS.md §3.19), rather than trying to discover patients
    automatically (which Epic's current authorization for this app doesn't
    permit — confirmed live against Patient, Encounter, and Appointment
    search, all three rejected without a specific patient/_id parameter).

    This is the real unblock while Epic Bulk Data Export registration is
    pending: everything downstream (feature store, detectors, guard,
    ranking, WhatsApp) is unchanged regardless of where the ID list came
    from — only the ID source changes.
    """
    ids = _load_roster_ids(patient_ids, roster_csv)
    if not ids:
        logger.error("pull_patient_roster: no patient IDs provided — nothing to pull")
        return 0

    logger.info(f"Starting Epic roster pull for {CLINIC_ID}: {len(ids)} patient(s)")

    conn = _db(); processed = 0
    for i in range(0, len(ids), batch_size):
        batch = ids[i:i + batch_size]
        try:
            bundle_entries = search_resources("Patient", {"_id": ",".join(batch)})
        except Exception as e:
            logger.error(f"Batch fetch failed for {len(batch)} ids: {e}", exc_info=True)
            continue
        patients = [e for e in bundle_entries if e.get("resourceType") == "Patient"]
        not_found = len(batch) - len(patients)
        if not_found:
            logger.warning(f"{not_found}/{len(batch)} ids in this batch were not found by Epic")

        for patient in patients:
            pid = patient.get("id")
            try:
                _resolve_and_upsert(conn, pid, patient=patient)
                processed += 1
                logger.info(f"  ✓ {pid}")
            except Exception as e:
                logger.error(f"  ✗ {pid}: {e}", exc_info=True)
                continue

    conn.commit(); conn.close()
    logger.info(f"Complete: {processed}/{len(ids)} patients written")
    return processed


def _upsert(conn, f: dict):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO staging_patients
          (patient_id,clinic_id,first_name,last_name,date_of_birth,sex,phone_e164,
           language,condition_codes,last_visit_date,last_procedure_type,
           open_treatment_plan,coverage_period_end_date)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (patient_id,clinic_id) DO UPDATE SET
          last_visit_date=EXCLUDED.last_visit_date,
          condition_codes=EXCLUDED.condition_codes,
          open_treatment_plan=EXCLUDED.open_treatment_plan,
          coverage_period_end_date=EXCLUDED.coverage_period_end_date,
          ingested_at=now()
    """, (f["patient_id"],f["clinic_id"],f["_first_name"],f["_last_name"],
          f["_date_of_birth"],f["sex"],f["_phone_e164"],f["_language"],
          f["condition_codes"],f["_last_visit_date"],f["last_procedure_type"],
          f["open_treatment_plan_flag"],f["coverage_period_end_date"]))

    cur.execute("""
        INSERT INTO patient_features
          (patient_id,clinic_id,days_since_last_visit,visit_cadence_baseline,
           last_procedure_type,last_procedure_date,open_treatment_plan_flag,
           coverage_period_end_date,condition_codes,age,sex,as_of_timestamp)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
        ON CONFLICT (patient_id,clinic_id) DO UPDATE SET
          days_since_last_visit=EXCLUDED.days_since_last_visit,
          last_procedure_type=EXCLUDED.last_procedure_type,
          open_treatment_plan_flag=EXCLUDED.open_treatment_plan_flag,
          coverage_period_end_date=EXCLUDED.coverage_period_end_date,
          condition_codes=EXCLUDED.condition_codes,
          as_of_timestamp=now()
    """, (f["patient_id"],f["clinic_id"],f["days_since_last_visit"],f["visit_cadence_baseline"],
          f["last_procedure_type"],f["last_procedure_date"],f["open_treatment_plan_flag"],
          f["coverage_period_end_date"],f["condition_codes"],f["age"],f["sex"]))

    # Consent — placeholder: in production only grant the specific
    # consent_class a patient actually signed in Epic, per class, not this
    # blanket grant. Every class is granted here (matching synthetic
    # seeding's behavior) so a real patient isn't arbitrarily blocked from
    # families that check a different consent_class than 'care_recall'.
    for consent_class in REAL_PATIENT_CONSENT_CLASSES:
        cur.execute("""
            INSERT INTO consent (patient_id,clinic_id,consent_class,channel)
            VALUES (%s,%s,%s,'whatsapp') ON CONFLICT DO NOTHING
        """, (f["patient_id"],f["clinic_id"],consent_class))
    cur.close()