#!/usr/bin/env python3
"""Assigns treatment arms (15% holdout) and publishes treated campaigns to NATS."""

import random
import uuid
import json
import asyncio
import sys
from datetime import datetime
from pathlib import Path
import psycopg2
import nats

sys.path.insert(0, str(Path(__file__).parents[1]))

PG = dict(host="localhost", port=5432, dbname="velodb", user="velo", password="velo_secret")
HOLDOUT_RATE = 0.15
HOLDOUT_SEED = 42


def _val(row, idx, default):
    """Return row[idx] if the row exists and the value is not None, else default."""
    if row is None:
        return default
    v = row[idx]
    return v if v is not None else default


async def run_decide():
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()

    cur.execute("""
        SELECT opportunity_id, patient_id, clinic_id, family,
               consent_class, priority_score
        FROM opportunities
        ORDER BY priority_score DESC
    """)
    opps = cur.fetchall()

    # ── Step 1: consent gate ──────────────────────────────────────────────────
    allowed_opps = []
    for row in opps:
        opp_id, pid, clinic_id, family, consent_class, priority = row
        cur.execute("""
            SELECT 1 FROM consent
            WHERE patient_id=%s AND clinic_id=%s AND consent_class=%s
              AND channel='whatsapp' AND revoked_at IS NULL
        """, (pid, clinic_id, consent_class))
        if not cur.fetchone():
            print(f"  ✗ {pid} blocked — no consent ({consent_class})")
            continue
        allowed_opps.append(row)

    if not allowed_opps:
        print("No opportunities passed the consent gate — nothing to dispatch.")
        cur.close(); conn.close()
        return

    # ── Step 2: build feature rows ────────────────────────────────────────────
    # Query all ML columns in one shot per patient.
    # COALESCE guarantees we always get a number even if the column is NULL
    # (happens for patients seeded before migration 003 was applied).
    feature_rows = []
    for opp_id, pid, clinic_id, family, consent_class, priority in allowed_opps:
        cur.execute("""
            SELECT
                COALESCE(prior_no_show_ratio,        0.15) AS prior_no_show_ratio,
                COALESCE(lead_time_days,             7)    AS lead_time_days,
                COALESCE(same_day_flag,              0)    AS same_day_flag,
                COALESCE(age,                        35)   AS age,
                COALESCE(deposit_paid,               0)    AS deposit_paid,
                COALESCE(travel_time_minutes,        20.0) AS travel_time_minutes,
                COALESCE(cancellation_history_ratio, 0.10) AS cancellation_history_ratio,
                COALESCE(vip_status,                 0)    AS vip_status,
                COALESCE(new_patient,                1)    AS new_patient,
                COALESCE(urgency_score,              5.0)  AS urgency_score,
                COALESCE(neighbourhood_ns_rate,      0.09) AS neighbourhood_ns_rate,
                COALESCE(provider_effect,            0.0)  AS provider_effect,
                COALESCE(consecutive_no_show_streak, 0)    AS consecutive_no_show_streak,
                COALESCE(time_of_day,                'morning')      AS time_of_day,
                COALESCE(specialty,                  'dental')       AS specialty,
                COALESCE(day_of_week,                'Monday')       AS day_of_week,
                COALESCE(treatment_stage,            'consultation') AS treatment_stage,
                COALESCE(is_ramadan,                 0)    AS is_ramadan,
                COALESCE(is_public_holiday,          0)    AS is_public_holiday
            FROM patient_features
            WHERE patient_id = %s AND clinic_id = %s
        """, (pid, clinic_id))
        row = cur.fetchone()

        feature_rows.append({
            "prior_no_show_ratio":        _val(row, 0,  0.15),
            "lead_time_days":             _val(row, 1,  7),
            "same_day_flag":              _val(row, 2,  0),
            "age":                        _val(row, 3,  35),
            "deposit_paid":               _val(row, 4,  0),
            "travel_time_minutes":        _val(row, 5,  20.0),
            "cancellation_history_ratio": _val(row, 6,  0.10),
            "vip_status":                 _val(row, 7,  0),
            "new_patient":                _val(row, 8,  1),
            "urgency_score":              _val(row, 9,  5.0),
            "neighbourhood_ns_rate":      _val(row, 10, 0.09),
            "provider_effect":            _val(row, 11, 0.0),
            "consecutive_no_show_streak": _val(row, 12, 0),
            "time_of_day":                _val(row, 13, "morning"),
            "specialty":                  _val(row, 14, "dental"),
            "day_of_week":                _val(row, 15, "Monday"),
            "treatment_stage":            _val(row, 16, "consultation"),
            "is_ramadan":                 _val(row, 17, 0),
            "is_public_holiday":          _val(row, 18, 0),
        })

    # ── Step 3: ML scoring (with graceful fallback) ───────────────────────────
    try:
        from ml.registry.scorer import score_patients_batch
        noshow_scores = score_patients_batch(feature_rows)
        print(f"  ✓ ML model scored {len(noshow_scores)} patients")
    except Exception as e:
        print(f"  ⚠ Model scoring failed ({e}) — falling back to rule priority")
        noshow_scores = [priority for _, _, _, _, _, priority in allowed_opps]

    # ── Step 4: holdout assignment + campaign creation ────────────────────────
    campaigns = []
    dispatched = []
    rng = random.Random(HOLDOUT_SEED)

    for i, (opp_id, pid, clinic_id, family, consent_class, _) in enumerate(allowed_opps):
        noshow_score = noshow_scores[i]
        arm = "holdout" if rng.random() < HOLDOUT_RATE else "treated"
        campaign = {
            "campaign_id":    str(uuid.uuid4()),
            "opportunity_id": opp_id,
            "patient_id":     pid,
            "clinic_id":      clinic_id,
            "family":         family,
            "channel":        "whatsapp",
            "treatment_arm":  arm,
            "template_id":    f"tmpl_{family.lower()}_recall_ar_v1",
            "template_vars":  {"patient_first_name": pid},
            "noshow_score":   round(noshow_score, 4),
            "created_at":     datetime.utcnow().isoformat(),
        }
        campaigns.append(campaign)

        cur.execute("""
            INSERT INTO campaigns
              (campaign_id, opportunity_id, patient_id, clinic_id,
               family, channel, treatment_arm, template_id, template_vars, noshow_score)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT DO NOTHING;
        """, (
            campaign["campaign_id"], opp_id, pid, clinic_id,
            family, "whatsapp", arm,
            campaign["template_id"], json.dumps(campaign["template_vars"]),
            campaign["noshow_score"],
        ))

        if arm == "treated":
            dispatched.append(campaign)
        print(
            f"  {'→ SEND  ' if arm == 'treated' else '⊘ HOLDOUT'}"
            f" {pid} [{family}] score={noshow_score:.3f}"
        )

    conn.commit()
    cur.close()
    conn.close()

    # ── Step 5: publish treated campaigns to NATS ─────────────────────────────
    nc = await nats.connect("nats://localhost:4222")
    js = nc.jetstream()
    try:
        await js.add_stream(name="campaigns", subjects=["campaigns.>"])
    except Exception:
        pass  # stream already exists

    for c in dispatched:
        await js.publish(
            f"campaigns.{c['clinic_id']}.{c['family']}",
            json.dumps(c).encode()
        )
        print(f"  📤 Published to NATS: {c['campaign_id'][:8]}… ({c['family']})")

    await nc.close()
    print(
        f"\n✅  {len(campaigns)} campaigns created  "
        f"({len(dispatched)} treated, {len(campaigns) - len(dispatched)} holdout)"
    )


if __name__ == "__main__":
    asyncio.run(run_decide())