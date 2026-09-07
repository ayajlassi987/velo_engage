# 8. Epic Integration

## Purpose

Every family in file 2, every feature the ML models score on, and every
patient's phone number ultimately has to come from somewhere real — that's
Epic, the EHR this system integrates with via FHIR. `ve_connect` is the
only service that talks to Epic directly; everything else reads from this
system's own Postgres tables that `ve_connect` populates.

## Two separate auth flows — a real, easy-to-miss distinction

Epic exposes two *completely independent* authentication mechanisms here,
with independent tokens, independent expiry, and independent code paths:

1. **Interactive OAuth** (`auth.py`) — PKCE-based user login flow
   (`/auth/login`), used for individual patient FHIR reads
   (`get_resource`/`search_resources` in `fhir_client.py`). Token expires
   and needs interactive re-login.
2. **SMART Backend Services (Bulk Data Export)** (`bulk_auth.py`) —
   client-credentials/JWT-assertion flow (`_build_client_assertion`,
   `get_bulk_token`), used only for `epic_bulk.py`'s `$export` Bulk Data
   flow. Self-signed JWT, no interactive login at all.

These can be in completely different states at the same time — e.g. the
interactive token can be expired for days while Bulk Data exports keep
succeeding, because they're unrelated credentials with unrelated lifetimes.
Anyone debugging an Epic connectivity issue needs to know which of the two
flows is actually failing before chasing the wrong one.

Epic's non-production sandbox refresh tokens have their own fixed lifetime,
independent of how recently they've been used — so the interactive flow's
refresh token dying (`invalid_grant`) and requiring a fresh `/auth/login`
is a real, recurring, expected characteristic of testing against a sandbox
app, not a bug to chase.

### Reaching `/auth/login` from outside — the ngrok tunnel-sharing problem

Epic requires an exact-match `redirect_uri`, registered as one bare ngrok
domain with no path (`EPIC_REDIRECT_URI`). That's the same public domain
`docker-compose.dev.yml`'s `ngrok` service tunnels to `ve_reach` for
WhatsApp webhooks (`07_communication_channels.md`) — ngrok's free tier only
grants one reserved domain, so both purposes have to share it. `ve_reach`
has three proxy routes for exactly this (`main.py`): `/auth/login`,
`/auth/callback`, and `/` all forward to `ve_connect:8000`'s real handlers
over the internal Docker network and relay the response back — `/auth/login`
relays Epic's redirect Location header, the callback routes forward
`code`/`state` and relay `ve_connect`'s JSON response verbatim (success or
error status). This means the one public tunnel serves both purposes
permanently; re-authorizing the interactive flow is just opening
`https://<ngrok-domain>/auth/login` in a browser, no tunnel reconfiguration
needed.

## The Bulk Data Export path (`epic_bulk.py`)

`run_bulk_export(group_id)`: kicks off a `$export` request against a Group
(a defined patient cohort in Epic), polls the returned status URL until
complete, downloads the resulting NDJSON files, and deletes the export
afterward. This is the mechanism a real clinic's full patient population
would flow through in production — currently exercised against a real,
independently-verified Epic sandbox Group ID (see `PROJECT_STATUS.md` for
how a previously-unverified Group ID from a pasted document was caught and
replaced with one confirmed directly against Epic's own sandbox catalog).

## Mapping Epic's FHIR shape into this system's schema

`mapper.py`'s `map_patient_to_features()` takes raw FHIR resources
(`Patient`, `Condition`, `Encounter`, `Procedure`, `Coverage`, and now
`DocumentReference`/`Binary` for clinical notes — file 9) and extracts the
specific fields this system's `patient_features`/`staging_patients` tables
need: ICD-10 codes, last visit date, last procedure, coverage end date,
phone number. Two real bugs were found and fixed here during Epic sandbox
testing, both worth knowing about because they're the kind of silent,
no-error-thrown failure that's easy to miss:

- **`extract_last_visit()`** originally filtered `Encounter.class.code`
  against standard FHIR v3-ActCode values (`ambulatory`/`outpatient`/
  `office`) — Epic populates `class` with its own proprietary internal
  coding system instead, so the filter matched zero real encounters,
  silently. Fixed by dropping the class check (`status: finished`, already
  filtered at the API call, is sufficient signal).
- **`CarePlan` search** was rejected by Epic's authorization in two
  different ways in sequence, with no way to iterate further against live
  requests. Rather than keep guessing, `CarePlan` fetching was made
  fault-tolerant (`_careplans_or_empty()`) — one resource type being
  unavailable for this app's authorized scope degrades
  `open_treatment_plan_flag` to `False` for that patient rather than
  blocking the other resource types (which do work) from being pulled at
  all.

## Seeing the raw pull before anything is mapped

Every Epic FHIR resource fetched here (`Patient`, `Condition`, `Encounter`,
`Procedure`, `CarePlan`, `Coverage`) gets fed straight into
`map_patient_to_features()` and discarded — the raw JSON was never
persisted or exposed anywhere, matching the same no-raw-retention
discipline as clinical notes (file 9). `GET /patients/{id}/raw`
(`adapter.py`'s `pull_raw_resources()`) exists purely as a diagnostic: it
calls the *exact same* fetch functions with the *exact same* search
parameters as `_resolve_and_upsert()` (the real pipeline's per-patient
resolve step), so what it returns is genuinely what the pipeline sees —
not a separate or different pull — and, like the clinical-notes endpoint,
it writes nothing to Postgres or disk; the response body is the only place
this data ever exists on this machine.

This surfaced something worth knowing when actually looking at it: several
of the real Epic sandbox patients' `DocumentReference` notes turned out to
be sandbox connectivity-test filler (`"Test note from fhir-template
sandbox verification. Not clinical content."`) or literal repeated-
character load-test artifacts, not real documentation — explaining why
MedGemma extraction (file 9) sometimes correctly returns empty results for
a given note. That's the sandbox's data quality, not a bug in extraction —
confirmed by checking the actual note text via this same read path before
concluding anything was broken.

## `adapter.py` — the actual write path into Postgres

`_upsert()` writes to `staging_patients`, `patient_features`, and `consent`
in one transaction per patient, called from `pull_patient_cohort`/
`pull_patient_roster` (exposed as `POST /pull-cohort`, `/pull-bulk`,
`/pull-bulk-sync`). The consent write here is an explicit, documented
placeholder — production should only grant the specific `consent_class` a
patient actually signed in Epic; this system has no way to read
per-class consent signals from Epic at all, so every real patient gets the
same 11 consent classes granted at ingestion (matching what synthetic
seeding grants, for consistency — see `03_guardrails_and_consent.md` and
`13_known_gaps_and_roadmap.md` for the real gap this represents and the
fix that closed an accidental *asymmetry* in it).

## Why a separate service, and why this design

- **Isolating Epic-specific failure modes.** Token expiry, rate limits,
  resource-authorization quirks, and FHIR-shape surprises are all Epic-
  specific concerns that shouldn't be able to take down rule evaluation or
  ranking. `pull_epic_data` (the activity that calls this service from the
  daily pipeline) explicitly swallows its own errors for exactly this
  reason (file 1/6).
- **Fault-tolerant per-resource-type fetching**, not all-or-nothing. A
  single unavailable FHIR resource type degrades one feature to a safe
  default rather than blocking every other resource type Epic *does*
  authorize for this app.
- **Never trust an unverified identifier.** The Bulk Data Group ID mixup
  and the App-ID-vs-Client-ID mixup (both in `PROJECT_STATUS.md`'s early
  sections) are both instances of the same lesson: an identifier pasted
  from a document, however authoritative-looking, gets independently
  verified against Epic's own API responses before being trusted.
