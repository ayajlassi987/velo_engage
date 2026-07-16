"""
Pulls a full patient cohort from Epic → maps to features → writes to Postgres.
Replaces seed_dummy_patients.py entirely once authorized.
"""

import csv, json, logging, os, sys
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

    # Consent — placeholder: in production only grant consent for patients
    # who have signed a digital consent form in Epic
    cur.execute("""
        INSERT INTO consent (patient_id,clinic_id,consent_class,channel)
        VALUES (%s,%s,'care_recall','whatsapp') ON CONFLICT DO NOTHING
    """, (f["patient_id"],f["clinic_id"]))
    cur.close()