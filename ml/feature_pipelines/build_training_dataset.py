#!/usr/bin/env python3

import os
from datetime import datetime, timezone
import pandas as pd
import psycopg2
import json


PG = dict(
    host=os.getenv("DB_HOST", "localhost"),
    port=int(os.getenv("DB_PORT", 5432)),
    dbname=os.getenv("DB_NAME", "velodb"),
    user=os.getenv("DB_USER", "velo"),
    password=os.getenv("DB_PASSWORD", "velo_secret"),
)

DATA_DIR = "ml/feature_pipelines/data"
# "latest" — what every train_*.py script actually reads, unchanged, so this
# versioning doesn't require touching their DATA_PATH. The timestamped copy
# plus LATEST_POINTER_PATH exist so a training run can log exactly which
# snapshot it trained on (see train_propensity.py etc.) instead of silently
# training against whatever the mutable "latest" file happened to contain.
OUT_PATH = f"{DATA_DIR}/training_dataset.parquet"
LATEST_POINTER_PATH = f"{DATA_DIR}/training_dataset.latest_path.txt"


def resolve_dataset_lineage_path(fallback: str = OUT_PATH) -> str:
    """The exact versioned snapshot "latest" currently points at, for
    train_*.py scripts to log as an MLflow param — falls back to the
    mutable path itself if the sidecar doesn't exist yet (dataset built
    before this versioning was added)."""
    try:
        with open(LATEST_POINTER_PATH) as f:
            return f.read().strip()
    except FileNotFoundError:
        return fallback


SQL = """
WITH campaign_outcomes AS (
    SELECT
        c.campaign_id, c.patient_id, c.clinic_id, c.created_at,
        COALESCE(out.read, false) AS read,
        COALESCE(out.replied, false) AS replied,
        COALESCE(out.booked, false) AS booked
    FROM campaigns c
    LEFT JOIN outcomes out ON c.campaign_id = out.campaign_id
),
-- Real prior-engagement history per patient, computed the same way live
-- scoring computes it (ml/../activities.py's rank_and_assign_holdout) —
-- a strictly-prior window (ROWS ... 1 PRECEDING) so a campaign never sees
-- its own or a future outcome. This replaces pulling previous_reads/
-- previous_replies/previous_bookings/previous_campaigns out of
-- rule_evidence, which only the synthetic seed script ever populated —
-- using that would train on a feature that's always missing for every
-- live-detected opportunity (train/serve skew).
prior_stats AS (
    SELECT
        campaign_id,
        COUNT(*) OVER w AS previous_campaigns,
        SUM(read::int) OVER w AS previous_reads,
        SUM(replied::int) OVER w AS previous_replies,
        SUM(booked::int) OVER w AS previous_bookings
    FROM campaign_outcomes
    WINDOW w AS (
        PARTITION BY patient_id, clinic_id ORDER BY created_at
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    )
)
SELECT
    c.campaign_id,
    c.opportunity_id,
    c.patient_id,
    c.clinic_id,
    c.family,
    c.channel,
    c.treatment_arm,
    c.template_id,
    c.created_at AS campaign_created_at,
    c.dispatched_at,

    o.priority_score,
    o.rule_name,
    o.rule_evidence,

    pf.days_since_last_visit,
    pf.visit_cadence_baseline,
    pf.last_procedure_type,
    pf.open_treatment_plan_flag,
    pf.coverage_period_end_date,
    pf.condition_codes,
    pf.age,
    pf.sex,
    pf.clinical_recall_due_flag,
    pf.cross_specialty_gap_flag,
    pf.seasonal_event_eligible_flag,
    pf.engagement_drop_flag,
    pf.preference_match_flag,
    pf.care_gap_due_flag,
    pf.abandoned_booking_flag,
    pf.treatment_lifecycle_due_flag,
    pf.household_lifestage_eligible_flag,
    pf.contextual_trigger_flag,
    pf.slot_fill_eligible_flag,
    pf.quality_followup_due_flag,
    pf.as_of_timestamp,

    COALESCE(out.delivered, false) AS delivered,
    COALESCE(out.read, false) AS read,
    COALESCE(out.replied, false) AS replied,
    COALESCE(out.booked, false) AS booked,
    COALESCE(out.attended, false) AS attended,
    out.recorded_at AS outcome_recorded_at,

    COALESCE(rev.revenue_amount, 0) AS revenue_amount,

    COALESCE(ps.previous_campaigns, 0) AS real_previous_campaigns,
    COALESCE(ps.previous_reads, 0) AS real_previous_reads,
    COALESCE(ps.previous_replies, 0) AS real_previous_replies,
    COALESCE(ps.previous_bookings, 0) AS real_previous_bookings

FROM campaigns c
LEFT JOIN opportunities o
    ON c.opportunity_id = o.opportunity_id
LEFT JOIN patient_features pf
    ON c.patient_id = pf.patient_id
   AND c.clinic_id = pf.clinic_id
LEFT JOIN outcomes out
    ON c.campaign_id = out.campaign_id
LEFT JOIN (
    SELECT campaign_id, SUM(amount) AS revenue_amount
    FROM revenue_attributions
    GROUP BY campaign_id
) rev
    ON c.campaign_id = rev.campaign_id
LEFT JOIN prior_stats ps
    ON c.campaign_id = ps.campaign_id
ORDER BY c.created_at;
"""


def get_evidence_value(value, key, default=None):
    if value is None:
        return default
    if isinstance(value, dict):
        return value.get(key, default)
    try:
        return json.loads(value).get(key, default)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def main():
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)

    with psycopg2.connect(**PG) as conn, conn.cursor() as cur:
        cur.execute(SQL)
        columns = [column.name for column in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=columns)

    for key in [
        "missed_appointments",
        "insurance_tier",
        "preferred_language",
        "weekend_patient",
        "high_value_patient",
        "days_until_expiry",
    ]:
        df[key] = df["rule_evidence"].apply(
            lambda value, evidence_key=key: get_evidence_value(value, evidence_key)
        )

    # Real, leak-safe prior-engagement counts from the SQL window functions
    # above — available for every row (synthetic or live), unlike the
    # rule_evidence-derived versions above, which only the synthetic seed
    # script ever populates.
    df = df.rename(columns={
        "real_previous_campaigns": "previous_campaigns",
        "real_previous_reads": "previous_reads",
        "real_previous_replies": "previous_replies",
        "real_previous_bookings": "previous_bookings",
    })

    if df.empty:
        raise RuntimeError("No campaign data found. Run the Temporal workflow first.")

    df["is_treated"] = (df["treatment_arm"] == "treated").astype(int)
    df["was_dispatched"] = df["dispatched_at"].notna().astype(int)

    df["delivered_label"] = df["delivered"].astype(int)
    df["read_label"] = df["read"].astype(int)
    df["replied_label"] = df["replied"].astype(int)
    df["booked_label"] = df["booked"].astype(int)
    df["attended_label"] = df["attended"].astype(int)

    # Value model (hurdle) labels — only meaningful conditional on having
    # actually reactivated (booked), per the master spec's E[revenue|reactivate].
    df["revenue_amount"] = df["revenue_amount"].astype(float)
    df["has_revenue_label"] = (df["revenue_amount"] > 0).astype(int)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    versioned_path = f"{DATA_DIR}/training_dataset_{timestamp}.parquet"
    df.to_parquet(versioned_path, index=False)
    df.to_parquet(OUT_PATH, index=False)
    with open(LATEST_POINTER_PATH, "w") as f:
        f.write(versioned_path)

    print(f"✅ Training dataset written to: {OUT_PATH} (versioned snapshot: {versioned_path})")
    print(f"Rows: {len(df)}")
    print(f"Columns: {len(df.columns)}")
    print(df[[
        "campaign_id",
        "patient_id",
        "family",
        "treatment_arm",
        "delivered_label",
        "read_label",
        "replied_label",
        "booked_label",
    ]].head(10))


if __name__ == "__main__":
    main()
