#!/usr/bin/env python3
"""Seed 10 fake patients for fictional pilot clinic 'Clinic Al-Noor'.

Superseded: real Epic data now flows in automatically via the daily
Temporal workflow (pull_epic_data -> ve_connect's Bulk Data $export). Not
deleted so the existing 10 seed patients and their historical
opportunities/campaigns stay intact for demo/dashboard purposes, but this
should not be re-run to add more fake patients."""

import json
from datetime import date, timedelta
import psycopg2
import redis

PG = dict(host="localhost", port=5432, dbname="velodb", user="velo", password="velo_secret")
REDIS_HOST = "localhost"
REDIS_PORT = 6379
CLINIC_ID = "clinic_alnoor_001"
CADENCE_BASELINE_DAYS = 120

PATIENTS = [
    ("P001", "محمد",   "الزهراني", "1978-03-15", "M", "+966501110001", "ar", ["E11", "I10"], 270, False, None),
    ("P002", "فاطمة",  "العتيبي",  "1990-07-22", "F", "+966501110002", "ar", ["J45"],        90,  True,  None),
    ("P003", "عبدالله","المطيري",  "1965-11-08", "M", "+966501110003", "ar", ["E11", "N18"], 310, False, None),
    ("P004", "نورة",   "السهلي",   "1985-04-30", "F", "+966501110004", "ar", [],             30,  False, 38),
    ("P005", "خالد",   "الدوسري",  "1992-09-14", "M", "+966501110005", "ar", ["K21"],        200, True,  None),
    ("P006", "سارة",   "الحربي",   "1973-12-01", "F", "+966501110006", "ar", ["I10"],        50,  False, None),
    ("P007", "أحمد",   "القحطاني", "1958-06-19", "M", "+966501110007", "ar", ["E11","E78"],  400, False, None),
    ("P008", "هند",    "الشمري",   "1999-02-28", "F", "+966501110008", "ar", [],             None,False, 40),
    ("P009", "سلطان",  "العجمي",   "1980-08-05", "M", "+966501110009", "ar", ["Z87.891"],   180, True,  None),
    ("P010", "ريم",    "البقمي",   "1995-01-17", "F", "+966501110010", "ar", [],             20,  False, None),
]

POLICY_FLAG_COLUMNS = [
    "clinical_recall_due_flag", "cross_specialty_gap_flag",
    "seasonal_event_eligible_flag", "engagement_drop_flag",
    "preference_match_flag", "care_gap_due_flag", "abandoned_booking_flag",
    "treatment_lifecycle_due_flag", "household_lifestage_eligible_flag",
    "contextual_trigger_flag", "slot_fill_eligible_flag",
    "quality_followup_due_flag",
]
DEMO_POLICY_FLAGS = {
    "P001": {"clinical_recall_due_flag"},
    "P002": {"cross_specialty_gap_flag"},
    "P003": {"seasonal_event_eligible_flag"},
    "P004": {"engagement_drop_flag"},
    "P005": {"preference_match_flag"},
    "P006": {"care_gap_due_flag"},
    "P007": {"abandoned_booking_flag"},
    "P008": {"treatment_lifecycle_due_flag"},
    "P009": {"household_lifestage_eligible_flag"},
    "P010": {"contextual_trigger_flag", "slot_fill_eligible_flag", "quality_followup_due_flag"},
}
CONSENT_CLASSES = [
    "care_recall", "clinical_recall", "care_coordination",
    "promotional_outreach", "engagement", "preference_outreach",
    "digital_followup", "household_outreach", "contextual_outreach",
    "operational_offer", "quality_followup",
]

def compute_age(dob_str: str) -> int:
    dob = date.fromisoformat(dob_str)
    today = date.today()
    return (today - dob).days // 365

def seed(pg_conn, r: redis.Redis):
    cur = pg_conn.cursor()
    today = date.today()

    for (pid, fname, lname, dob, sex, phone, lang, conditions,
         last_visit_offset, open_plan, coverage_offset) in PATIENTS:

        last_visit = (today - timedelta(days=last_visit_offset)) if last_visit_offset else None
        coverage_end = (today + timedelta(days=coverage_offset)) if coverage_offset else None
        days_since = last_visit_offset if last_visit_offset else None
        age = compute_age(dob)

        cur.execute("""
            INSERT INTO staging_patients
              (patient_id, clinic_id, first_name, last_name, date_of_birth,
               sex, phone_e164, language, condition_codes, last_visit_date,
               last_procedure_type, open_treatment_plan, coverage_period_end_date)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (patient_id, clinic_id) DO UPDATE
              SET last_visit_date = EXCLUDED.last_visit_date,
                  ingested_at = now();
        """, (pid, CLINIC_ID, fname, lname, dob, sex, phone, lang,
              conditions, last_visit, None, open_plan, coverage_end))

        flag_values = [column in DEMO_POLICY_FLAGS.get(pid, set()) for column in POLICY_FLAG_COLUMNS]
        flag_columns = ", ".join(POLICY_FLAG_COLUMNS)
        flag_placeholders = ", ".join(["%s"] * len(POLICY_FLAG_COLUMNS))
        flag_updates = ", ".join(
            f"{column}=EXCLUDED.{column}" for column in POLICY_FLAG_COLUMNS
        )
        cur.execute(f"""
            INSERT INTO patient_features
              (patient_id, clinic_id, days_since_last_visit,
               visit_cadence_baseline, open_treatment_plan_flag,
               coverage_period_end_date, condition_codes, age, sex,
               {flag_columns}, as_of_timestamp)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,{flag_placeholders},now())
            ON CONFLICT (patient_id, clinic_id) DO UPDATE
              SET days_since_last_visit = EXCLUDED.days_since_last_visit,
                  open_treatment_plan_flag = EXCLUDED.open_treatment_plan_flag,
                  coverage_period_end_date = EXCLUDED.coverage_period_end_date,
                  condition_codes = EXCLUDED.condition_codes,
                  age = EXCLUDED.age,
                  sex = EXCLUDED.sex,
                  {flag_updates},
                  as_of_timestamp = now();
        """, (pid, CLINIC_ID, days_since, CADENCE_BASELINE_DAYS,
              open_plan, coverage_end, conditions, age, sex, *flag_values))

        for consent_class in CONSENT_CLASSES:
            cur.execute("""
                INSERT INTO consent (patient_id, clinic_id, consent_class, channel)
                VALUES (%s, %s, %s, 'whatsapp')
                ON CONFLICT DO NOTHING;
            """, (pid, CLINIC_ID, consent_class))

        redis_key = f"features:{CLINIC_ID}:{pid}"
        r.hset(redis_key, mapping={
            "days_since_last_visit": days_since if days_since is not None else "",
            "visit_cadence_baseline": CADENCE_BASELINE_DAYS,
            "open_treatment_plan_flag": int(open_plan),
            "coverage_period_end_date": str(coverage_end) if coverage_end else "",
            "condition_codes": json.dumps(conditions),
            "age": age,
            "sex": sex,
            **{column: int(value) for column, value in zip(POLICY_FLAG_COLUMNS, flag_values)},
        })
        r.expire(redis_key, 86400 * 2)

        print(f"  ✓ {pid} {fname} {lname} — seeded")

    pg_conn.commit()
    cur.close()
    print(f"\n✅  10 patients seeded to Postgres + Redis for {CLINIC_ID}")

if __name__ == "__main__":
    conn = psycopg2.connect(**PG)
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    seed(conn, r)
    conn.close()
