# 3. Guardrails and Consent

## Purpose

Detection (file 2) intentionally over-generates candidates. This layer's
entire job is to narrow that list down to contacts that are **legally
permitted, not excessive, and not redundant** — before any ranking or ML
scoring happens. Implemented as the `gate_consent` Temporal activity
(`services/ve_orchestrator/src/ve_orchestrator/activities.py`), which takes
a list of `opportunity_id`s and returns a smaller list of `opportunity_id`s
that survived every gate, logging exactly why each dropped candidate was
dropped.

## The three gates, in order

### 1. Consent

Every opportunity family declares a `consent_class` (e.g. `care_recall`,
`clinical_recall`, `promotional_outreach` — see file 2's table). A patient
only passes this gate if there's a live row in the `consent` table for
their exact `(patient_id, clinic_id, consent_class)` triple, on the
`whatsapp` channel, with no `revoked_at`. This is a **per-class** check —
consenting to `care_recall` contact does not imply consent to
`promotional_outreach` contact. Batched as one query fetching every consent
row touching any candidate patient, then matched in Python — one round trip
instead of one query per opportunity.

For real Epic patients, consent rows are granted at ingestion time by
`ve_connect/adapter.py`'s `_upsert()` (a placeholder — see
`08_epic_integration.md` and `13_known_gaps_and_roadmap.md` for the honest
limitations of this: it's not a genuine per-class consent signal read from
Epic, because Epic doesn't expose one here). For synthetic demo patients,
`scripts/seed_synthetic_phase1.py` grants the same set of classes.

### 2. Cooldown + rolling frequency cap

Two independent checks, both evaluated **per patient**, regardless of which
family/opportunity is asking — a patient can't be recontacted through a
*different* family the moment one family's cooldown lapses:

- **Cooldown** (`CONTACT_COOLDOWN_DAYS`): blocks a patient if their most
  recent dispatched campaign was too recent.
- **Frequency cap** (`MAX_CONTACTS_PER_WINDOW` per `CONTACT_WINDOW_DAYS`):
  blocks a patient who's already been contacted the maximum allowed number
  of times in the rolling window, even if individually spaced out.

Both are computed with one batched `GROUP BY` query over `campaigns` for
every candidate patient at once, rather than one query per patient.

### 3. One-primary-opportunity-per-patient de-dup

If a patient matches multiple families on the same day (e.g. both "dormant"
and "open treatment plan"), only the single highest-`priority_score` match
survives — clinical families are configured with higher priority than
commercial ones in their YAML (file 2's table), so this naturally favors
clinical relevance over marketing opportunities without any special-case
code for it. This also means a patient only ever gets **one** message per
day regardless of how many legitimate reasons exist.

## Why this order, and why it's a hard gate rather than a ranking input

Consent is checked first and is absolute — no ranking score can override a
missing consent grant. This is a deliberate design choice: legal/ethical
contactability is a yes/no gate, not something a model should be allowed to
trade off against "but this patient looks very persuadable." Cooldown and
frequency cap exist to prevent the system from being a nuisance even to
patients who *have* consented and *are* good candidates — repeated,
well-targeted contact can still be over-contact. De-dup exists so ranking
(file 4) only ever has to decide relative priority *across patients*, never
*within* one patient's multiple simultaneous reasons — that ambiguity is
resolved here, deterministically, before ranking sees it.
