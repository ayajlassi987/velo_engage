# 12. Data Model

All tables live in one Postgres database (`velodb`). MLflow shares the same
database for its own internal bookkeeping (`runs`, `metrics`, `params`,
`registered_models`, `experiments`, etc.) — those aren't part of this
application's data model and aren't described here.

## Patient data

- **`staging_patients`** — one row per patient per clinic: name, DOB, sex,
  phone, language, condition codes, last visit/procedure, coverage end
  date. The "raw" ingested view, written by `ve_connect` (real patients,
  file 8) or the synthetic seed script (demo patients).
- **`patient_features`** — the derived, ML-ready view of the same
  patients: everything in `staging_patients` plus every flag the 16
  opportunity families check (file 2) and every feature the 5 ranking
  models read (file 4), including the historical no-show aggregates
  computed by `refresh_historical_features` (files 4 and 6). One row per
  `(patient_id, clinic_id)`.
- **`consent`** — `(patient_id, clinic_id, consent_class, channel,
  granted_at, revoked_at)`. Per-*class* consent, not a single yes/no — a
  patient can be contactable for `care_recall` but not
  `promotional_outreach` (file 3).

## The pipeline's own tables

- **`opportunities`** — one row per detected match from `evaluate_rules`
  (file 2): which family, which rule, priority score, consent class
  required, JSON evidence (why it matched). `opportunity_id` is a
  deterministic SHA256 hash of `(patient_id, clinic_id, rule_id, date)` —
  re-running the same day's pipeline correctly no-ops here
  (`ON CONFLICT DO NOTHING`) instead of creating duplicates.
- **`campaigns`** — one row per opportunity that survived guardrails and
  got scored/arm-assigned (files 3–5): all 5 model scores, the combined
  `expected_value_score`, `treatment_arm` (`treated`/`holdout`),
  `dispatched_at`. `campaign_id` is similarly deterministic, but here a
  re-run *does* refresh the score columns (`ON CONFLICT DO UPDATE`) — the
  campaign identity is stable but its scores should reflect the latest
  model/data, which is exactly why campaign lists should be read ordered
  by `created_at`, not just `expected_value_score`, when trying to find
  the *freshest* data (an easy mistake — see `PROJECT_STATUS.md` for a
  concrete case where sorting by `expected_value_score DESC` surfaced
  stale pre-model rows ahead of genuinely fresh ones).

## Outcomes and attribution

- **`outcomes`** — one row per campaign: `delivered`/`read`/`replied`/
  `booked`/`attended` booleans plus their first-ever-true timestamps
  (`delivered_at`, etc. — the timing data the survival model trains on,
  file 4) and `revenue`. Written by `ve_reach`'s webhook handler
  (delivered/read/replied), `ve_measure`'s booking listener
  (booked/attended/revenue), or the console's manual outcome endpoint
  (file 10) — all through the same idempotent OR-merge upsert pattern so
  none of the three paths can clobber what another already recorded.
- **`bookings`** — one row per real appointment, attributed back to the
  campaign that plausibly caused it (`ve_measure`'s 30-day lookback
  window). This, not `outcomes.booked`, is what the console's `/bookings`
  page and KPI cards actually count.
- **`revenue_attributions`** — one row per invoice/payment event,
  similarly attributed to a booking/campaign. Summed (paid only) into
  `outcomes.revenue` by `refresh_campaign_revenue`.
- **`wa_message_map`**, **`outbound_messages`**, **`inbound_messages`** —
  the WhatsApp message ledger: which `wa_message_id` belongs to which
  campaign, delivery status per outbound message, and every inbound reply
  with its detected intent (file 4's intent classifier + the deterministic
  keyword gate, file 7).

## Supporting tables

- **`clinical_extractions`** — MedGemma's structured output per clinical
  note (file 9). No raw note text column at all, by design.
- **`epic_tokens`** — persisted OAuth token state for Epic's interactive
  auth flow (file 8).
- **`clinics`**, **`clinic_users`** — multi-clinic scaffolding (file 11):
  which clinics exist, which clinic each console user belongs to.

## Cross-cutting conventions worth knowing

- **Deterministic IDs, not random UUIDs**, for `opportunity_id`/
  `campaign_id` — makes same-day re-runs safely idempotent instead of
  creating duplicates, at the cost of needing to think carefully about
  which columns should `DO NOTHING` (opportunities: identity shouldn't
  change) vs. `DO UPDATE` (campaigns: scores should refresh) on conflict.
- **A `patient_id` prefix convention distinguishes synthetic from real
  patients** (`SYN%`/`P0%` = synthetic/seeded; anything else = a real Epic
  FHIR ID) — checked directly in SQL (`NOT LIKE 'SYN%'`) throughout the
  orchestrator and console, rather than a separate boolean column, because
  it was retrofitted onto an existing ID scheme rather than designed in
  from the start. Used to keep ~20,000 rows of synthetic training-data
  volume from crowding out live evaluation of the much smaller real
  patient population, and to keep console metrics honestly separated by
  cohort.
