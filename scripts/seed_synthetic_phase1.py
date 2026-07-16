#!/usr/bin/env python3
"""Superseded: real Epic data now flows in automatically via the daily
Temporal workflow (pull_epic_data -> ve_connect's Bulk Data $export). Not
deleted so the existing ~20,000 SYN* patients and their historical
opportunities/campaigns stay intact for demo/dashboard purposes, but this
should not be re-run to add more synthetic volume."""

import random
import uuid
import json
import sys
from datetime import date, timedelta, datetime
from pathlib import Path

import psycopg2
import math

ORCHESTRATOR_SRC = Path(__file__).parents[1] / "services" / "ve_orchestrator" / "src"
sys.path.insert(0, str(ORCHESTRATOR_SRC))

from ve_orchestrator.policy_engine import policy_for_family  # noqa: E402


PG = dict(
    host="localhost",
    port=5432,
    dbname="velodb",
    user="velo",
    password="velo_secret",
)

CLINIC_ID = "clinic_alnoor_001"
# 5000 -> 20000: the live orchestrator's real (non-synthetic) campaign rows
# have a near-zero booking rate right now (no real booking attribution
# wired up yet), so almost all trainable signal for the propensity/value/
# uplift models comes from this synthetic population — quadrupling it
# directly reduces the variance in AUC/PR-AUC estimates and gives the
# uplift model's data-starved control arm meaningfully more positives.
# random.seed(42) below keeps patients 1-5000 bit-identical to before;
# this only adds new patients on top, it doesn't regenerate old ones.
N_PATIENTS = 20000
HOLDOUT_RATE = 0.15
random.seed(42)


FIRST_NAMES = ["Sara", "Omar", "Noura", "Khalid", "Fatima", "Ahmed", "Hind", "Reem", "Yousef", "Maha"]
LAST_NAMES = ["Alharbi", "Alotaibi", "Alqahtani", "Aldosari", "Alzahrani", "Alshammari"]

POLICY_FAMILY_FLAGS = {
    "B": ("clinical_recall_due_flag", "clinical_recall_due", 0.85, "clinical_recall"),
    "D": ("cross_specialty_gap_flag", "cross_specialty_gap", 0.75, "care_coordination"),
    "E": ("seasonal_event_eligible_flag", "seasonal_event_eligible", 0.45, "promotional_outreach"),
    "F": ("engagement_drop_flag", "engagement_drop", 0.50, "engagement"),
    "H": ("preference_match_flag", "preference_match", 0.55, "preference_outreach"),
    "J": ("care_gap_due_flag", "care_gap_due", 0.88, "care_recall"),
    "K": ("abandoned_booking_flag", "abandoned_booking", 0.65, "digital_followup"),
    "L": ("treatment_lifecycle_due_flag", "treatment_lifecycle_due", 0.72, "care_recall"),
    "M": ("household_lifestage_eligible_flag", "household_lifestage_eligible", 0.40, "household_outreach"),
    "O": ("contextual_trigger_flag", "contextual_trigger", 0.60, "contextual_outreach"),
    "P": ("slot_fill_eligible_flag", "slot_fill_eligible", 0.35, "operational_offer"),
    "Q": ("quality_followup_due_flag", "quality_followup_due", 0.82, "quality_followup"),
}
CONSENT_CLASSES = sorted({"care_recall", *(item[3] for item in POLICY_FAMILY_FLAGS.values())})


def rand_phone(i: int) -> str:
    return f"+21695{i:06d}"


def weighted_bool(prob: float) -> bool:
    return random.random() < prob

def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def main():
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    today = date.today()

    print(f"Seeding {N_PATIENTS} synthetic patients...")

    for i in range(1, N_PATIENTS + 1):
        patient_id = f"SYN{i:05d}"
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        age = random.randint(18, 82)
        dob = today - timedelta(days=age * 365)
        sex = random.choice(["M", "F"])

        missed_appointments = random.randint(0, 5)
        previous_campaigns = random.randint(0, 8)
        previous_reads = random.randint(0, previous_campaigns) if previous_campaigns > 0 else 0
        previous_replies = random.randint(0, previous_reads) if previous_reads > 0 else 0
        previous_bookings = random.randint(0, previous_replies) if previous_replies > 0 else 0
        insurance_tier = random.choice(["basic", "standard", "premium"])
        preferred_language = random.choice(["ar", "en"])
        weekend_patient = weighted_bool(0.35)
        high_value_patient = weighted_bool(0.20)

        days_since = random.randint(5, 600)
        last_visit = today - timedelta(days=days_since)

        open_plan = weighted_bool(0.28)
        has_coverage_expiry = weighted_bool(0.35)
        coverage_end = today + timedelta(days=random.randint(1, 60)) if has_coverage_expiry else None

        conditions = []
        if weighted_bool(0.25):
            conditions.append("E11")
        if weighted_bool(0.18):
            conditions.append("I10")
        if weighted_bool(0.10):
            conditions.append("J45")

        phone = rand_phone(i)
        policy_flags = {
            config[0]: weighted_bool(0.04)
            for config in POLICY_FAMILY_FLAGS.values()
        }

        cur.execute("""
            INSERT INTO staging_patients
              (patient_id, clinic_id, first_name, last_name, date_of_birth,
               sex, phone_e164, language, condition_codes, last_visit_date,
               open_treatment_plan, coverage_period_end_date)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'ar',%s,%s,%s,%s)
            ON CONFLICT (patient_id, clinic_id) DO UPDATE
              SET last_visit_date = EXCLUDED.last_visit_date,
                  open_treatment_plan = EXCLUDED.open_treatment_plan,
                  coverage_period_end_date = EXCLUDED.coverage_period_end_date;
        """, (
            patient_id, CLINIC_ID, first, last, dob, sex, phone,
            conditions, last_visit, open_plan, coverage_end
        ))

        flag_columns = ", ".join(policy_flags)
        flag_placeholders = ", ".join(["%s"] * len(policy_flags))
        flag_updates = ", ".join(
            f"{column}=EXCLUDED.{column}" for column in policy_flags
        )
        cur.execute(f"""
            INSERT INTO patient_features
              (patient_id, clinic_id, days_since_last_visit,
               visit_cadence_baseline, open_treatment_plan_flag,
               coverage_period_end_date, condition_codes, age, sex,
               {flag_columns}, as_of_timestamp)
            VALUES (%s,%s,%s,120,%s,%s,%s,%s,%s,{flag_placeholders},now())
            ON CONFLICT (patient_id, clinic_id) DO UPDATE
              SET days_since_last_visit = EXCLUDED.days_since_last_visit,
                  open_treatment_plan_flag = EXCLUDED.open_treatment_plan_flag,
                  coverage_period_end_date = EXCLUDED.coverage_period_end_date,
                  condition_codes = EXCLUDED.condition_codes,
                  age = EXCLUDED.age,
                  sex = EXCLUDED.sex,
                  {flag_updates},
                  as_of_timestamp = now();
        """, (
            patient_id, CLINIC_ID, days_since, open_plan,
            coverage_end, conditions, age, sex, *policy_flags.values()
        ))

        for consent_class in CONSENT_CLASSES:
            cur.execute("""
                INSERT INTO consent (patient_id, clinic_id, consent_class, channel)
                VALUES (%s, %s, %s, 'whatsapp')
                ON CONFLICT DO NOTHING;
            """, (patient_id, CLINIC_ID, consent_class))

        triggered = []

        if days_since > 180:
            triggered.append(("A", "dormancy", 0.7, "care_recall"))

        if open_plan and days_since > 30:
            triggered.append(("C", "open_treatment_plan", 0.9, "care_recall"))

        if coverage_end and 0 <= (coverage_end - today).days <= 45:
            triggered.append(("G", "benefit_lifecycle", 0.8, "care_recall"))

        for family, (flag, rule_name, priority, consent_class) in POLICY_FAMILY_FLAGS.items():
            if policy_flags[flag]:
                triggered.append((family, rule_name, priority, consent_class))

        for family, rule_name, priority, consent_class in triggered:
            opp_id = f"syn_opp_{patient_id}_{family}_{today.isoformat()}"
            evidence = {
                "missed_appointments": missed_appointments,
                "previous_campaigns": previous_campaigns,
                "previous_reads": previous_reads,
                "previous_replies": previous_replies,
                "previous_bookings": previous_bookings,
                "insurance_tier": insurance_tier,
                "preferred_language": preferred_language,
                "weekend_patient": weekend_patient,
                "high_value_patient": high_value_patient,
                "days_until_expiry": (coverage_end - today).days if coverage_end 
                else None, 
            }

            cur.execute("""
                INSERT INTO opportunities
                  (opportunity_id, patient_id, clinic_id, family,
                   consent_class, priority_score, rule_name, rule_evidence)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (opportunity_id) DO NOTHING;
            """, (
                opp_id, patient_id, CLINIC_ID, family, consent_class,
                priority, rule_name, json.dumps({**evidence, **policy_flags})
            ))

            treatment_arm = "holdout" if weighted_bool(HOLDOUT_RATE) else "treated"
            campaign_id = f"syn_campaign_{opp_id}"

            dispatched_at = None
            delivered = False
            read = False
            replied = False
            booked = False
            attended = False

            if treatment_arm == "treated":
              dispatched_at = datetime.utcnow()

              engagement_score = -1.2

              engagement_score += {
                  "A": 0.2, "B": 0.7, "C": 0.9, "D": 0.6, "E": 0.3,
                  "F": 0.4, "G": 0.5, "H": 0.4, "J": 0.8, "K": 0.7,
                  "L": 0.6, "M": 0.3, "O": 0.4, "P": 0.5, "Q": 0.8,
              }.get(family, 0.0)

              if open_plan:
                  engagement_score += 0.8

              if days_since < 120:
                  engagement_score += 0.5
              elif days_since > 365:
                  engagement_score -= 0.6

              if age >= 55:
                  engagement_score += 0.3

              if coverage_end:
                  days_until_expiry = (coverage_end - today).days
                  if days_until_expiry <= 20:
                      engagement_score += 0.6
                  elif days_until_expiry <= 45:
                      engagement_score += 0.3

              engagement_score += 0.25 * previous_reads
              engagement_score += 0.45 * previous_replies
              engagement_score += 0.60 * previous_bookings
              engagement_score -= 0.35 * missed_appointments

              if insurance_tier == "premium":
                  engagement_score += 0.4
              elif insurance_tier == "basic":
                  engagement_score -= 0.2

              if weekend_patient:
                  engagement_score += 0.15

              if high_value_patient:
                  engagement_score += 0.25

              read_prob = sigmoid(engagement_score)
              reply_prob = sigmoid(engagement_score - 1.2)
              book_prob = sigmoid(engagement_score - 2.0)

              delivered = weighted_bool(0.94)
              read = delivered and weighted_bool(read_prob)
              replied = read and weighted_bool(reply_prob)
              booked = replied and weighted_bool(book_prob)
              attended = booked and weighted_bool(0.82)

            else:
                # holdout can still book naturally, but no message is sent
                booked = weighted_bool(0.04)
                attended = booked and weighted_bool(0.75)

            cur.execute("""
                INSERT INTO campaigns
                  (campaign_id, opportunity_id, patient_id, clinic_id, family,
                   channel, treatment_arm, template_id, template_vars, dispatched_at)
                VALUES (%s,%s,%s,%s,%s,'whatsapp',%s,%s,%s,%s)
                ON CONFLICT (campaign_id) DO NOTHING;
            """, (
                campaign_id, opp_id, patient_id, CLINIC_ID, family,
                treatment_arm,
                policy_for_family(family)["delivery"]["template"]["name"],
                json.dumps({"patient_first_name": first}),
                dispatched_at
            ))

            revenue_amount = 0
            if booked:
                booking_id = f"syn_booking_{campaign_id}"
                appointment_date = datetime.combine(
                    today + timedelta(days=7), datetime.min.time()
                ).replace(hour=9)
                booking_status = "attended" if attended else "booked"
                cur.execute("""
                    INSERT INTO bookings
                      (booking_id, patient_id, clinic_id, campaign_id,
                       appointment_date, status, source_event_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (booking_id) DO UPDATE SET
                      appointment_date=EXCLUDED.appointment_date,
                      status=EXCLUDED.status,
                      campaign_id=EXCLUDED.campaign_id,
                      updated_at=now();
                """, (
                    booking_id, patient_id, CLINIC_ID, campaign_id,
                    appointment_date, booking_status,
                    f"syn_booking_event_{campaign_id}",
                ))

                if attended:
                    revenue_amount = (
                        {
                            "A": 180, "B": 280, "C": 450, "D": 340,
                            "E": 220, "F": 190, "G": 260, "H": 210,
                            "J": 360, "K": 240, "L": 300, "M": 200,
                            "O": 230, "P": 250, "Q": 320,
                        }.get(family, 220)
                        + (250 if high_value_patient else 0)
                        + (100 if insurance_tier == "premium" else 0)
                    )
                    invoice_id = f"syn_invoice_{campaign_id}"
                    cur.execute("""
                        INSERT INTO revenue_attributions
                          (revenue_id, invoice_id, booking_id, patient_id,
                           clinic_id, campaign_id, amount, currency, paid,
                           source_event_id, occurred_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,'USD',TRUE,%s,%s)
                        ON CONFLICT (invoice_id) DO UPDATE SET
                          booking_id=EXCLUDED.booking_id,
                          campaign_id=EXCLUDED.campaign_id,
                          amount=EXCLUDED.amount,
                          paid=TRUE,
                          occurred_at=EXCLUDED.occurred_at,
                          updated_at=now();
                    """, (
                        f"syn_revenue_{campaign_id}", invoice_id, booking_id,
                        patient_id, CLINIC_ID, campaign_id, revenue_amount,
                        f"syn_revenue_event_{campaign_id}", appointment_date,
                    ))

            cur.execute("""
                INSERT INTO outcomes
                  (campaign_id, patient_id, delivered, read, replied,
                   booked, attended, revenue, recorded_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT (campaign_id) DO UPDATE
                  SET delivered = EXCLUDED.delivered,
                      read = EXCLUDED.read,
                      replied = EXCLUDED.replied,
                      booked = EXCLUDED.booked,
                      attended = EXCLUDED.attended,
                      revenue = EXCLUDED.revenue,
                      recorded_at = now();
            """, (
                campaign_id, patient_id, delivered, read,
                replied, booked, attended, revenue_amount
            ))

            if treatment_arm == "treated":
                wa_message_id = f"synthetic_wamid_{uuid.uuid4().hex}"
                cur.execute("""
                    INSERT INTO wa_message_map
                      (wa_message_id, campaign_id, patient_id)
                    VALUES (%s,%s,%s)
                    ON CONFLICT DO NOTHING;
                """, (wa_message_id, campaign_id, patient_id))

    conn.commit()

    cur.execute("SELECT COUNT(*) FROM staging_patients WHERE patient_id LIKE 'SYN%';")
    patients = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM opportunities WHERE opportunity_id LIKE 'syn_opp_%';")
    opps = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM campaigns WHERE campaign_id LIKE 'syn_campaign_%';")
    campaigns = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM bookings WHERE booking_id LIKE 'syn_booking_%';")
    bookings = cur.fetchone()[0]

    cur.execute("""
        SELECT COALESCE(SUM(amount),0) FROM revenue_attributions
        WHERE invoice_id LIKE 'syn_invoice_%' AND paid;
    """)
    recovered_revenue = cur.fetchone()[0]

    cur.execute("""
        SELECT
          SUM(CASE WHEN treatment_arm='treated' THEN 1 ELSE 0 END),
          SUM(CASE WHEN treatment_arm='holdout' THEN 1 ELSE 0 END)
        FROM campaigns
        WHERE campaign_id LIKE 'syn_campaign_%';
    """)
    treated, holdout = cur.fetchone()

    cur.close()
    conn.close()

    print("✅ Synthetic Phase 1 data created")
    print(f"Patients:      {patients}")
    print(f"Opportunities: {opps}")
    print(f"Campaigns:     {campaigns}")
    print(f"Treated:       {treated}")
    print(f"Holdout:       {holdout}")
    print(f"Bookings:      {bookings}")
    print(f"Revenue:       USD {recovered_revenue:,.2f}")


if __name__ == "__main__":
    main()
