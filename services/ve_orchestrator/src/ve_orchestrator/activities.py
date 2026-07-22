"""
activities.py — Temporal activities, payload-safe version.
Activities pass only IDs between each other, not full objects.
Each activity re-fetches what it needs from Postgres directly.
This keeps every activity result well under Temporal's 2MB limit.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values
import nats
from temporalio import activity

# Locate the repo root that contains the top-level `ml/` package — differs
# between local dev (services/ve_orchestrator/src/ve_orchestrator/activities.py,
# 4 levels down) and the Docker image (/app/src/ve_orchestrator/activities.py,
# where `ml/` is copied in alongside `src/`).
for _candidate in (
    Path(__file__).resolve().parents[4] if len(Path(__file__).resolve().parents) > 4 else None,
    Path("/app"),
):
    if _candidate and (_candidate / "ml").is_dir():
        sys.path.insert(0, str(_candidate))
        break

from libs.ve_clients.vault_client import get_secret

PG_HOST = os.getenv("DB_HOST", "localhost")
PG_PORT = int(os.getenv("DB_PORT", 5432))
PG_DBNAME = os.getenv("DB_NAME", "velodb")
CLINIC_ID             = os.getenv("CLINIC_ID", "clinic_alnoor_001")
HOLDOUT_RATE          = 0.15
HOLDOUT_SEED_BASE     = 42

# Guard: don't over-message. A patient who was just contacted gets a short
# cooldown regardless of how many opportunities they match; a longer rolling
# window caps the total number of contacts even if each individual cooldown
# has expired.
CONTACT_COOLDOWN_DAYS   = int(os.getenv("CONTACT_COOLDOWN_DAYS", 3))
CONTACT_WINDOW_DAYS     = int(os.getenv("CONTACT_WINDOW_DAYS", 30))
MAX_CONTACTS_PER_WINDOW = int(os.getenv("MAX_CONTACTS_PER_WINDOW", 3))

# Dev safety nets — cap how many opportunities/campaigns one workflow run can
# push forward and how many WhatsApp sends it can trigger. Unset (None) means
# no cap.
WORKFLOW_BATCH_LIMIT = int(os.environ["WORKFLOW_BATCH_LIMIT"]) if os.getenv("WORKFLOW_BATCH_LIMIT") else None
DISPATCH_LIMIT       = int(os.environ["DISPATCH_LIMIT"]) if os.getenv("DISPATCH_LIMIT") else None


def _db():
    return psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_DBNAME,
        user=get_secret("postgres", "user", "DB_USER") or "velo",
        password=get_secret("postgres", "password", "DB_PASSWORD") or "velo_secret",
    )


def _val(row, idx, default):
    if row is None:
        return default
    v = row[idx]
    return v if v is not None else default


VE_CONNECT_URL = os.getenv("VE_CONNECT_URL", "http://ve_connect:8000")


# ── Activity 0 ────────────────────────────────────────────────────────────────
# Refreshes real Epic patient data (via ve_connect's Bulk Data $export) before
# rule evaluation runs, so every daily run works from current clinical data
# instead of whatever was last pulled manually. Best-effort and non-fatal: if
# Epic is briefly unreachable or a token expired, the rest of the pipeline
# still runs against whatever is already in patient_features — the daily
# campaign pipeline must not go down because an upstream EHR integration
# hiccuped, same reasoning as the Redis/Neo4j optional-infra fallbacks.
@activity.defn
async def pull_epic_data() -> dict:
    req = urllib.request.Request(f"{VE_CONNECT_URL}/pull-bulk-sync", method="POST", data=b"")
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            result = json.loads(resp.read())
            activity.logger.info(f"Epic data refresh: {result}")
            return result
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        activity.logger.warning(
            f"Epic data refresh failed ({exc}) — continuing with existing patient_features data"
        )
        return {"status": "failed", "error": str(exc)}


# ── Activity 1 ────────────────────────────────────────────────────────────────
# Evaluates every enabled family in policies/opportunities/*.yml (via
# policy_engine.py) against the full patient_features row for each patient.
# Returns: list of opportunity_ids (strings only — tiny payload)
@activity.defn
async def evaluate_rules() -> list[str]:
    from ve_orchestrator.ids import deterministic_opportunity_id
    from ve_orchestrator.policy_engine import active_policies, evaluate_policy

    from ve_orchestrator.feature_store import fetch_patient_features

    conn  = _db()
    cur   = conn.cursor()
    today = date.today()

    rows = fetch_patient_features(cur, CLINIC_ID)

    policies = active_policies()

    # Family B (clinical recall) resolved for every patient in one batched
    # Neo4j call up front — at most 2 queries total, instead of a new
    # session + up to 2 queries per patient inside the loop below (the
    # worst-scaling piece of this activity; see graph_client.py's
    # clinical_recall_due_batch). A whole-batch failure falls back to
    # evaluate_policy's clinical_recall_due_flag feature for every patient,
    # logged once rather than per-patient.
    family_b_results: dict[str, dict | None] = {}
    graph_batch_available = False
    try:
        from ve_orchestrator import graph_client as _graph_client
        family_b_results = _graph_client.clinical_recall_due_batch(
            [
                {
                    "id": pid,
                    "condition_codes": features.get("condition_codes"),
                    "age": features.get("age"),
                    "days_since_last_visit": features.get("days_since_last_visit"),
                }
                for pid, features in rows
            ],
            today,
        )
        graph_batch_available = True
    except Exception as exc:
        activity.logger.warning(
            f"VE Graph (Neo4j) batch query unavailable ({exc}) — family B will "
            f"fall back to the clinical_recall_due_flag feature for every patient"
        )

    matches = []  # (priority, family, opp_id) — every real match, written regardless of any batch cap
    insert_rows = []  # collected and written in one batched INSERT after the loop
    for pid, features in rows:
        for policy in policies:
            family = policy["family"]
            if family == "B" and graph_batch_available:
                evidence = family_b_results.get(pid)
            else:
                evidence = evaluate_policy(policy, features, today)
            if evidence is None:
                continue
            rule = policy["rule"]
            opp_id = deterministic_opportunity_id(pid, CLINIC_ID, rule["id"], today)
            insert_rows.append((
                opp_id, pid, CLINIC_ID, policy["family"],
                rule["consent_class"], rule["priority"],
                rule["id"], json.dumps(evidence),
            ))
            matches.append((rule["priority"], policy["family"], opp_id))

    if insert_rows:
        # One round trip instead of one INSERT per match — at 7 real patients
        # this was never a bottleneck, but the synthetic-history population
        # this ran against daily for weeks made it a real cost (see
        # PROJECT_STATUS.md's crowding-out writeup); worth fixing now while
        # it's cheap rather than after real-patient growth.
        execute_values(cur, """
            INSERT INTO opportunities
              (opportunity_id, patient_id, clinic_id, family,
               consent_class, priority_score, rule_name, rule_evidence)
            VALUES %s
            ON CONFLICT (opportunity_id) DO NOTHING;
        """, insert_rows)

    conn.commit(); cur.close(); conn.close()
    activity.logger.info(
        f"evaluate_rules: {len(matches)} opportunities written "
        f"across {len(policies)} active families"
    )

    # Every match is persisted above regardless of the batch limit — this cap
    # only bounds how many flow into consent/holdout/dispatch this run.
    #
    # Sorting all matches by raw priority and truncating would let a single
    # high-volume family monopolize every run: priority is a fixed constant
    # per family (e.g. family C is always 0.9), and family C alone produces
    # thousands of matches — a plain sort+truncate returns 100% family C,
    # every single time, starving every other family before the real
    # ML-based ranking downstream (rank_and_assign_holdout's expected-value
    # formula) ever sees a diverse candidate pool. Round-robin across
    # families instead (higher-priority families still go first within each
    # round, so clinical-outranks-commercial still holds at the margin).
    by_family: dict[str, list[str]] = {}
    family_priority: dict[str, float] = {}
    for priority, family, opp_id in matches:
        by_family.setdefault(family, []).append(opp_id)
        family_priority[family] = priority
    families_by_priority = sorted(by_family, key=lambda f: family_priority[f], reverse=True)

    if WORKFLOW_BATCH_LIMIT is None:
        opportunity_ids = [opp_id for family in families_by_priority for opp_id in by_family[family]]
    else:
        opportunity_ids = []
        while len(opportunity_ids) < WORKFLOW_BATCH_LIMIT and any(by_family.values()):
            for family in families_by_priority:
                if len(opportunity_ids) >= WORKFLOW_BATCH_LIMIT:
                    break
                if by_family[family]:
                    opportunity_ids.append(by_family[family].pop(0))

    # Return only IDs — tiny payload, well under 2MB limit
    return opportunity_ids


# ── Activity 2 ────────────────────────────────────────────────────────────────
# Guard: consent -> cooldown/frequency cap -> one-primary-per-patient de-dup.
# Receives: list of opportunity_ids
# Returns:  list of opportunity_ids that passed every gate (still just IDs)
@activity.defn
async def gate_consent(opportunity_ids: list[str]) -> list[str]:
    if not opportunity_ids:
        return []

    conn = _db(); cur = conn.cursor()

    placeholders = ",".join(["%s"] * len(opportunity_ids))
    cur.execute(f"""
        SELECT opportunity_id, patient_id, clinic_id, consent_class, priority_score, family
        FROM opportunities
        WHERE opportunity_id IN ({placeholders})
    """, opportunity_ids)
    rows = cur.fetchall()

    # Batched instead of one SELECT per opportunity: fetch every consent row
    # touching a candidate patient in one query, then match the exact
    # (patient_id, clinic_id, consent_class) triple in Python — same result,
    # one round trip instead of len(rows).
    candidate_patient_ids = list({pid for _, pid, _, _, _, _ in rows})
    cur.execute("""
        SELECT patient_id, clinic_id, consent_class FROM consent
        WHERE patient_id = ANY(%s) AND channel='whatsapp' AND revoked_at IS NULL
    """, (candidate_patient_ids,))
    consented_triples = {(pid, clinic_id, consent_class) for pid, clinic_id, consent_class in cur.fetchall()}

    consented = []
    for opp_id, pid, clinic_id, consent_class, priority_score, family in rows:
        if (pid, clinic_id, consent_class) in consented_triples:
            consented.append((opp_id, pid, clinic_id, priority_score, family))
        else:
            activity.logger.warning(f"{pid} blocked — no consent for {consent_class}")

    # Cooldown + rolling frequency cap: evaluated per patient, independent of
    # which family/opportunity is asking, so a patient can't be reached again
    # through a different family the moment one cooldown lapses. Batched via
    # GROUP BY instead of one query per patient — a patient absent from the
    # result (never dispatched to) is exactly equivalent to the original
    # per-patient query's (0, NULL) default, handled by the .get() below.
    consented_patient_ids = list({pid for _, pid, _, _, _ in consented})
    cur.execute("""
        SELECT patient_id, clinic_id,
               count(*) FILTER (WHERE dispatched_at >= now() - %s * interval '1 day'),
               max(dispatched_at)
        FROM campaigns
        WHERE patient_id = ANY(%s) AND dispatched_at IS NOT NULL
        GROUP BY patient_id, clinic_id
    """, (CONTACT_WINDOW_DAYS, consented_patient_ids))
    contact_stats = {
        (pid, clinic_id): (contacts_in_window, last_contacted)
        for pid, clinic_id, contacts_in_window, last_contacted in cur.fetchall()
    }

    not_over_messaged = []
    for opp_id, pid, clinic_id, priority_score, family in consented:
        contacts_in_window, last_contacted = contact_stats.get((pid, clinic_id), (0, None))

        if last_contacted is not None:
            cooldown_remaining = (
                datetime.now(last_contacted.tzinfo) - last_contacted
            ).total_seconds() / 86400
            if cooldown_remaining < CONTACT_COOLDOWN_DAYS:
                activity.logger.info(
                    f"{pid} blocked — {cooldown_remaining:.1f}d since last "
                    f"contact, cooldown is {CONTACT_COOLDOWN_DAYS}d"
                )
                continue

        if contacts_in_window >= MAX_CONTACTS_PER_WINDOW:
            activity.logger.info(
                f"{pid} blocked — {contacts_in_window} contacts in the last "
                f"{CONTACT_WINDOW_DAYS}d, cap is {MAX_CONTACTS_PER_WINDOW}"
            )
            continue

        not_over_messaged.append((opp_id, pid, priority_score, family))

    # De-dup: one primary opportunity per patient per run. Clinical families
    # are configured with a higher priority_score than commercial ones (see
    # policies/opportunities/*.yml), so this naturally ranks clinical first.
    best_per_patient: dict[str, tuple[str, float, str]] = {}
    for opp_id, pid, priority_score, family in not_over_messaged:
        current = best_per_patient.get(pid)
        if current is None or priority_score > current[1]:
            best_per_patient[pid] = (opp_id, priority_score, family)

    allowed_ids = [opp_id for opp_id, _, _ in best_per_patient.values()]

    cur.close(); conn.close()
    activity.logger.info(
        f"gate_consent: {len(allowed_ids)}/{len(opportunity_ids)} passed "
        f"(consent={len(consented)}, not_over_messaged={len(not_over_messaged)}, "
        f"after_dedup={len(allowed_ids)})"
    )
    return allowed_ids


# ── Activity 3 ────────────────────────────────────────────────────────────────
# Receives: list of opportunity_ids + run_date string
# Returns:  list of campaign_ids (strings only)
@activity.defn
async def rank_and_assign_holdout(
    opportunity_ids: list[str], run_date: str
) -> list[str]:
    import random
    from ve_orchestrator.ids import deterministic_campaign_id

    if not opportunity_ids:
        return []

    run_date = str(run_date) if not isinstance(run_date, str) else run_date
    today = date.fromisoformat(run_date[:10])
    seed  = HOLDOUT_SEED_BASE + today.toordinal()
    rng   = random.Random(seed)

    conn = _db(); cur = conn.cursor()

    # Fetch full opportunity data + ML features in one join. prior_stats
    # computes each patient's real campaign-engagement history (same
    # definition ml/feature_pipelines/build_training_dataset.py uses for
    # training) so the propensity/uplift models see this signal live, not
    # just in offline eval.
    placeholders = ",".join(["%s"] * len(opportunity_ids))
    cur.execute(f"""
        WITH prior_stats AS (
            SELECT
                c.patient_id, c.clinic_id,
                COUNT(*) AS previous_campaigns,
                SUM(COALESCE(out.read, false)::int) AS previous_reads,
                SUM(COALESCE(out.replied, false)::int) AS previous_replies,
                SUM(COALESCE(out.booked, false)::int) AS previous_bookings
            FROM campaigns c
            LEFT JOIN outcomes out ON c.campaign_id = out.campaign_id
            GROUP BY c.patient_id, c.clinic_id
        )
        SELECT
            o.opportunity_id, o.patient_id, o.clinic_id, o.family,
            o.consent_class, o.priority_score,
            COALESCE(pf.prior_no_show_ratio,        0.15),
            COALESCE(pf.lead_time_days,             7),
            COALESCE(pf.same_day_flag,              0),
            COALESCE(pf.age,                        35),
            COALESCE(pf.deposit_paid,               0),
            COALESCE(pf.travel_time_minutes,        20.0),
            COALESCE(pf.cancellation_history_ratio, 0.10),
            COALESCE(pf.vip_status,                 0),
            COALESCE(pf.new_patient,                1),
            COALESCE(pf.urgency_score,              5.0),
            COALESCE(pf.neighbourhood_ns_rate,      0.09),
            COALESCE(pf.provider_effect,            0.0),
            COALESCE(pf.consecutive_no_show_streak, 0),
            COALESCE(pf.time_of_day,                'morning'),
            COALESCE(pf.specialty,                  'dental'),
            COALESCE(pf.day_of_week,                'Monday'),
            COALESCE(pf.treatment_stage,            'consultation'),
            COALESCE(pf.is_ramadan,                 0),
            COALESCE(pf.is_public_holiday,          0),
            COALESCE(pf.days_since_last_visit,      365),
            COALESCE(pf.visit_cadence_baseline,     180),
            COALESCE(pf.open_treatment_plan_flag,   false),
            COALESCE(pf.sex,                        'F'),
            COALESCE((o.rule_evidence->>'high_value_patient')::boolean, false),
            COALESCE(o.rule_evidence->>'insurance_tier', 'standard'),
            COALESCE(ps.previous_campaigns, 0),
            COALESCE(ps.previous_reads, 0),
            COALESCE(ps.previous_replies, 0),
            COALESCE(ps.previous_bookings, 0)
        FROM opportunities o
        LEFT JOIN patient_features pf
          ON o.patient_id = pf.patient_id AND o.clinic_id = pf.clinic_id
        LEFT JOIN prior_stats ps
          ON o.patient_id = ps.patient_id AND o.clinic_id = ps.clinic_id
        WHERE o.opportunity_id IN ({placeholders})
        ORDER BY o.priority_score DESC
    """, opportunity_ids)
    rows = cur.fetchall()

    # Build feature lists for batch ML scoring — two different questions:
    # no-show risk (already-booked appointment) vs. reactivation propensity
    # (will this contact result in a new booking at all).
    noshow_feature_rows = []
    propensity_feature_rows = []
    value_feature_rows = []
    for row in rows:
        noshow_feature_rows.append({
            "prior_no_show_ratio":        _val(row, 6,  0.15),
            "lead_time_days":             _val(row, 7,  7),
            "same_day_flag":              _val(row, 8,  0),
            "age":                        _val(row, 9,  35),
            "deposit_paid":               _val(row, 10, 0),
            "travel_time_minutes":        _val(row, 11, 20.0),
            "cancellation_history_ratio": _val(row, 12, 0.10),
            "vip_status":                 _val(row, 13, 0),
            "new_patient":                _val(row, 14, 1),
            "urgency_score":              _val(row, 15, 5.0),
            "neighbourhood_ns_rate":      _val(row, 16, 0.09),
            "provider_effect":            _val(row, 17, 0.0),
            "consecutive_no_show_streak": _val(row, 18, 0),
            "time_of_day":                _val(row, 19, "morning"),
            "specialty":                  _val(row, 20, "dental"),
            "day_of_week":                _val(row, 21, "Monday"),
            "treatment_stage":            _val(row, 22, "consultation"),
            "is_ramadan":                 _val(row, 23, 0),
            "is_public_holiday":          _val(row, 24, 0),
        })
        propensity_feature_rows.append({
            "family":                     row[3],
            "days_since_last_visit":      _val(row, 25, 365),
            "visit_cadence_baseline":     _val(row, 26, 180),
            "open_treatment_plan_flag":   _val(row, 27, False),
            "age":                        _val(row, 9,  35),
            "sex":                        _val(row, 28, "F"),
            "priority_score":             row[5],
            "previous_campaigns":         _val(row, 31, 0),
            "previous_reads":             _val(row, 32, 0),
            "previous_replies":           _val(row, 33, 0),
            "previous_bookings":          _val(row, 34, 0),
        })
        value_feature_rows.append({
            "family":                     row[3],
            "high_value_patient":         _val(row, 29, False),
            "insurance_tier":             _val(row, 30, "standard"),
        })

    try:
        from ml.registry.scorer import score_patients_batch
        noshow_scores = score_patients_batch(noshow_feature_rows)
        activity.logger.info(f"ML scored {len(noshow_scores)} patients (no-show risk)")
    except Exception as e:
        activity.logger.warning(f"No-show scoring failed ({e}) — using rule priority")
        noshow_scores = [row[5] for row in rows]  # fallback to priority_score

    try:
        from ml.registry.propensity_scorer import score_opportunities_batch
        propensity_scores = score_opportunities_batch(propensity_feature_rows)
        activity.logger.info(f"ML scored {len(propensity_scores)} patients (booking propensity)")
    except Exception as e:
        activity.logger.warning(f"Propensity scoring failed ({e}) — using rule priority")
        propensity_scores = [row[5] for row in rows]  # fallback to priority_score

    try:
        from ml.registry.value_scorer import score_opportunities_batch as score_value_batch
        value_scores = score_value_batch(value_feature_rows)
        activity.logger.info(f"ML scored {len(value_scores)} patients (expected revenue)")
    except Exception as e:
        activity.logger.warning(f"Value scoring failed ({e}) — treating value as neutral (1.0)")
        value_scores = [1.0 for _ in rows]  # neutral multiplier — degrades to priority x propensity

    try:
        from ml.registry.uplift_scorer import score_opportunities_batch as score_uplift_batch
        # Same feature shape as the propensity model — reuse those rows.
        uplift_scores = score_uplift_batch(propensity_feature_rows)
        activity.logger.info(f"ML scored {len(uplift_scores)} patients (uplift)")
    except Exception as e:
        activity.logger.warning(f"Uplift scoring failed ({e}) — treating everyone as persuadable")
        uplift_scores = [1.0 for _ in rows]  # no discount applied

    try:
        from ml.registry.survival_scorer import score_opportunities_batch as score_survival_batch
        # Same feature shape as the propensity model — reuse those rows.
        # Informational only for now: predicted days-to-book is persisted
        # and monitored but not folded into expected_value below — blending
        # a duration estimate into a per-contact EV formula needs its own
        # deliberate mathematical treatment (e.g. discounting later
        # conversions), a separate design decision from training the model.
        survival_scores = score_survival_batch(propensity_feature_rows)
        activity.logger.info(f"ML scored {len(survival_scores)} patients (predicted days-to-book)")
    except Exception as e:
        activity.logger.warning(f"Survival/timing scoring failed ({e}) — leaving unscored")
        survival_scores = [None for _ in rows]

    to_insert = []
    for i, row in enumerate(rows):
        opp_id       = row[0]
        pid          = row[1]
        clinic_id    = row[2]
        family       = row[3]
        priority     = row[5]
        noshow_score = noshow_scores[i]
        propensity_score = propensity_scores[i]
        value_score  = value_scores[i]
        uplift_score = uplift_scores[i]
        survival_score = survival_scores[i]
        arm          = "holdout" if rng.random() < HOLDOUT_RATE else "treated"
        campaign_id  = deterministic_campaign_id(opp_id, today)
        # EV(patient) = appropriateness/urgency (priority_score) x
        # P(reactivate|contact) (booking propensity) x E[revenue|reactivate]
        # (value) — the master spec's ranking formula, minus contact/incentive
        # cost terms (not modeled) — then heavily discounted for patients the
        # uplift model estimates would book anyway or are unmoved by contact
        # (uplift <= 0), so outreach capacity favors genuine persuadables.
        persuadable_multiplier = 1.0 if uplift_score > 0 else 0.1
        expected_value = priority * propensity_score * value_score * persuadable_multiplier
        to_insert.append((
            campaign_id, opp_id, pid, clinic_id, family, arm,
            noshow_score, propensity_score, value_score, uplift_score, expected_value,
            survival_score,
        ))

    # Highest expected value dispatched first once DISPATCH_LIMIT truncates.
    # expected_value is second-to-last now that survival_score (informational
    # only, not part of this ranking) is appended after it.
    to_insert.sort(key=lambda r: r[-2], reverse=True)

    # One batched upsert instead of one INSERT per campaign — same
    # ON_CONFLICT/EXCLUDED semantics, applied once across every row (see the
    # matching evaluate_rules INSERT batching above for why this matters
    # more against the synthetic-history table volume than at the current
    # real-patient count).
    insert_rows = [
        (
            campaign_id, opp_id, pid, clinic_id, family, arm,
            f"tmpl_{family.lower()}_recall_ar_v1",
            json.dumps({"patient_first_name": pid}),
            round(noshow_score, 4), round(propensity_score, 4),
            round(value_score, 4), round(uplift_score, 4), round(ev, 4),
            round(survival_score, 4) if survival_score is not None else None,
        )
        for campaign_id, opp_id, pid, clinic_id, family, arm, noshow_score, propensity_score, value_score, uplift_score, ev, survival_score in to_insert
    ]
    if insert_rows:
        execute_values(cur, """
            INSERT INTO campaigns
              (campaign_id, opportunity_id, patient_id, clinic_id, family,
               channel, treatment_arm, template_id, template_vars,
               noshow_score, booking_propensity_score, value_score,
               uplift_score, expected_value_score, survival_score)
            VALUES %s
            ON CONFLICT (campaign_id) DO UPDATE SET
              noshow_score=EXCLUDED.noshow_score,
              booking_propensity_score=EXCLUDED.booking_propensity_score,
              value_score=EXCLUDED.value_score,
              uplift_score=EXCLUDED.uplift_score,
              expected_value_score=EXCLUDED.expected_value_score,
              survival_score=EXCLUDED.survival_score;
        """, insert_rows, template="(%s,%s,%s,%s,%s,'whatsapp',%s,%s,%s,%s,%s,%s,%s,%s,%s)")

    campaign_ids = [row[0] for row in to_insert]

    conn.commit(); cur.close(); conn.close()

    activity.logger.info(
        f"rank_and_assign_holdout: {len(campaign_ids)} campaigns created"
    )
    return campaign_ids  # IDs only


# ── Activity 4 ────────────────────────────────────────────────────────────────
# Receives: list of campaign_ids
# Returns:  count of dispatched messages (int — trivially small)
@activity.defn
async def dispatch_treated_to_reach(campaign_ids: list[str]) -> int:
    if not campaign_ids:
        return 0

    conn = _db(); cur = conn.cursor()

    # Fetch only treated campaigns
    placeholders = ",".join(["%s"] * len(campaign_ids))
    cur.execute(f"""
        SELECT campaign_id, patient_id, clinic_id, family,
               treatment_arm, template_id, template_vars, noshow_score
        FROM campaigns
        WHERE campaign_id IN ({placeholders})
          AND treatment_arm = 'treated'
        ORDER BY expected_value_score DESC NULLS LAST
    """, campaign_ids)
    treated = cur.fetchall()
    cur.close(); conn.close()

    if not treated:
        activity.logger.info("dispatch_treated_to_reach: no treated campaigns")
        return 0

    if DISPATCH_LIMIT is not None and len(treated) > DISPATCH_LIMIT:
        activity.logger.info(
            f"dispatch_treated_to_reach: capping {len(treated)} treated "
            f"campaigns to DISPATCH_LIMIT={DISPATCH_LIMIT}"
        )
        treated = treated[:DISPATCH_LIMIT]

    nc = await nats.connect(os.getenv("NATS_URL", "nats://localhost:4222"))
    js = nc.jetstream()
    try:
        await js.add_stream(name="campaigns", subjects=["campaigns.>"])
    except Exception:
        pass

    count = 0
    for row in treated:
        campaign_id, pid, clinic_id, family, arm, tmpl_id, tmpl_vars, score = row
        payload = {
            "campaign_id":   campaign_id,
            "patient_id":    pid,
            "clinic_id":     clinic_id,
            "family":        family,
            "treatment_arm": arm,
            "template_id":   tmpl_id,
            "template_vars": tmpl_vars,
            "noshow_score":  score,
        }
        await js.publish(
            f"campaigns.{clinic_id}.{family}",
            json.dumps(payload).encode()
        )
        count += 1

    await nc.close()
    activity.logger.info(
        f"dispatch_treated_to_reach: published {count} campaigns to NATS"
    )
    return count