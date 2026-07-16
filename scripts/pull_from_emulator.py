#!/usr/bin/env python3
"""
Pulls patients + appointment history from the EHR emulator
and writes them into Postgres (staging_patients + patient_features + consent).
Replaces seed_dummy_patients.py entirely.
"""

import json
import httpx
import psycopg2
from datetime import date, datetime

EMULATOR_BASE = "http://localhost:8090"
CLINIC_ID     = "clinic_alnoor_001"
CADENCE_DAYS  = 120

PG = dict(host="localhost", port=5432, dbname="velodb",
          user="velo", password="velo_secret")


def pull_patients(limit: int = 200) -> list[dict]:
    resp = httpx.get(f"{EMULATOR_BASE}/api/patients", params={"limit": limit})
    resp.raise_for_status()
    data = resp.json()
    # emulator returns {"items": [...]} or a list — handle both
    return data.get("items", data) if isinstance(data, dict) else data


def pull_appointments(patient_id: int) -> list[dict]:
    resp = httpx.get(f"{EMULATOR_BASE}/api/appointments",
                     params={"patient_id": patient_id, "limit": 50})
    resp.raise_for_status()
    data = resp.json()
    return data.get("items", data) if isinstance(data, dict) else data


def compute_days_since_last_visit(appointments: list[dict]) -> int | None:
    fulfilled = [
        a for a in appointments
        if a.get("status") in ("fulfilled", "checked_in")
    ]
    if not fulfilled:
        return None
    latest_str = max(a["start_dt"] for a in fulfilled)
    latest = datetime.fromisoformat(latest_str.replace("Z", "+00:00")).date()
    return (date.today() - latest).days


def compute_open_treatment_plan(appointments: list[dict]) -> bool:
    """True if patient has a booked/confirmed appointment in the future."""
    today = date.today()
    return any(
        a.get("status") in ("booked", "confirmed")
        and datetime.fromisoformat(
            a["start_dt"].replace("Z", "+00:00")
        ).date() >= today
        for a in appointments
    )


def compute_age(dob: str | None) -> int | None:
    if not dob:
        return None
    d = date.fromisoformat(dob[:10])
    return (date.today() - d).days // 365


def seed(conn, patient: dict, appointments: list[dict]):
    cur = conn.cursor()
    pid     = str(patient["id"])
    name    = patient.get("name", "")
    parts   = name.split(" ", 1)
    fname   = parts[0]
    lname   = parts[1] if len(parts) > 1 else ""
    dob     = patient.get("dob")
    gender  = patient.get("gender", "unknown")
    phone   = patient.get("phone", "")
    lang    = patient.get("preferred_language", "ar")
    days    = compute_days_since_last_visit(appointments)
    open_plan = compute_open_treatment_plan(appointments)
    age     = compute_age(dob)

    # staging_patients
    cur.execute("""
        INSERT INTO staging_patients
          (patient_id, clinic_id, first_name, last_name, date_of_birth,
           sex, phone_e164, language, condition_codes, last_visit_date,
           open_treatment_plan, coverage_period_end_date)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (patient_id, clinic_id) DO UPDATE SET
          open_treatment_plan = EXCLUDED.open_treatment_plan,
          ingested_at = now()
    """, (pid, CLINIC_ID, fname, lname, dob, gender,
          phone, lang, [], None, open_plan, None))

    # patient_features
    cur.execute("""
        INSERT INTO patient_features
          (patient_id, clinic_id, days_since_last_visit, visit_cadence_baseline,
           open_treatment_plan_flag, age, sex, condition_codes, as_of_timestamp)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now())
        ON CONFLICT (patient_id, clinic_id) DO UPDATE SET
          days_since_last_visit    = EXCLUDED.days_since_last_visit,
          open_treatment_plan_flag = EXCLUDED.open_treatment_plan_flag,
          as_of_timestamp          = now()
    """, (pid, CLINIC_ID, days, CADENCE_DAYS,
          open_plan, age, gender, []))

    # consent — grant if patient has WhatsApp opt-in
    if patient.get("whatsapp_opt_in", True):
        cur.execute("""
            INSERT INTO consent (patient_id, clinic_id, consent_class, channel)
            VALUES (%s, %s, 'care_recall', 'whatsapp')
            ON CONFLICT DO NOTHING
        """, (pid, CLINIC_ID))

    cur.close()


if __name__ == "__main__":
    print("Pulling patients from EHR emulator...")
    patients = pull_patients(limit=200)
    conn = psycopg2.connect(**PG)
    ok = 0
    for p in patients:
        try:
            appts = pull_appointments(p["id"])
            seed(conn, p, appts)
            ok += 1
            print(f"  ✓ {p['id']} {p.get('name','')}")
        except Exception as e:
            print(f"  ✗ {p['id']}: {e}")
    conn.commit(); conn.close()
    print(f"\n✅  {ok}/{len(patients)} patients pulled from emulator → Postgres")