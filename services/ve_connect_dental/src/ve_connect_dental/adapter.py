"""Write path into Postgres — the dental-side equivalent of ve_connect's
adapter.py. Reads from a DentalPMSClient (client.py), maps via mapper.py,
and upserts into dental_procedure_history (infra/migrations/019_dental_
treatment_pathway.sql). Never writes to patient_treatment_state directly —
that table belongs to ve_treatment_planner, which reacts to new rows here
via its own activity, keeping the two services' write responsibilities
separate the same way ve_connect never writes ve_orchestrator's tables.
"""

import logging
import os
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

from ve_connect_dental.client import DentalPMSClient
from ve_connect_dental.mapper import map_procedures

for _candidate in (
    Path(__file__).resolve().parents[4] if len(Path(__file__).resolve().parents) > 4 else None,
    Path("/app"),
):
    if _candidate and (_candidate / "libs").is_dir():
        sys.path.insert(0, str(_candidate))
        break
from libs.ve_clients.vault_client import get_secret

logger = logging.getLogger(__name__)
CLINIC_ID = os.getenv("CLINIC_ID", "clinic_alnoor_001")


def _db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"), port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "velodb"), user=get_secret("postgres", "user", "DB_USER") or "velo",
        password=get_secret("postgres", "password", "DB_PASSWORD") or "velo_secret",
    )


def _upsert_procedure_history(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO dental_procedure_history
                (history_id, patient_id, clinic_id, source, cdt_code, tooth,
                 surface, procedure_date, status, raw_reference_id)
            VALUES %s
            ON CONFLICT (clinic_id, source, raw_reference_id) DO UPDATE SET
                cdt_code = EXCLUDED.cdt_code,
                tooth = EXCLUDED.tooth,
                surface = EXCLUDED.surface,
                procedure_date = EXCLUDED.procedure_date,
                status = EXCLUDED.status
            """,
            [
                (
                    r["history_id"], r["patient_id"], r["clinic_id"], r["source"],
                    r["cdt_code"], r["tooth"], r["surface"], r["procedure_date"],
                    r["status"], r["raw_reference_id"],
                )
                for r in rows
            ],
        )
    conn.commit()
    return len(rows)


def pull_patient_dental_history(client: DentalPMSClient, patient_id: str, clinic_id: str = CLINIC_ID) -> int:
    """Pulls one patient's procedures from the configured PMS client, maps
    them, and upserts. Returns the row count written — callers (main.py's
    endpoint, and eventually a ve_treatment_planner activity) use this to
    confirm the pull actually did something rather than assuming success."""
    raw_procedures = client.get_procedures(patient_id)
    mapped = map_procedures(raw_procedures, patient_id=patient_id, clinic_id=clinic_id)
    conn = _db()
    try:
        return _upsert_procedure_history(conn, mapped)
    finally:
        conn.close()
