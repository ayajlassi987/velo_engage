# 13. Known Gaps and Roadmap

Honest inventory of what's genuinely not done, organized by *why* it's not
done — because the reason determines what would actually unblock it.

## Recently closed (worth knowing existed)

- **`clinical_recall` consent asymmetry** — real patients only ever got
  `care_recall` consent granted at ingestion (`ve_connect/adapter.py`),
  while synthetic patients got all 11 classes any family might require.
  Not a real consent difference — an incomplete placeholder that silently
  blocked families B, I, and others for every real patient. Fixed: real
  patients now get the same 11 classes. Still an honest placeholder either
  way (see "External, needs a real registration/approval" below) — this
  fix removed an *accidental* gap on top of the *real* one.
- **No-show model running on placeholder features** — `ve_noshow_v1`
  requires 32 features; 15 didn't exist in `patient_features` at all,
  silently defaulted for every patient the whole time. 11 now computed for
  real from booking/message history (`historical_features.py`); 4 stay
  fixed because the data to compute them doesn't exist anywhere in this
  schema (see below).
- **Cross-tenant campaign-detail leak** — any logged-in console user could
  view any other clinic's campaign by guessing its ID, found while adding
  multi-clinic support. Fixed.
- **Missing-phone real patients silently skipped** — the sandbox WhatsApp
  redirect only ever substituted for an *existing* phone value; a patient
  with no phone at all still got skipped before the redirect logic ran.
  Fixed.

## Genuinely external-blocked (no code change unblocks these)

These all require a real clinic contract, a real Epic/Meta registration, or
real business decisions this codebase can't make for itself:

- Epic Bulk Data Export for a real (non-sandbox) clinic — needs a
  production Epic Client ID and that clinic's IT team provisioning a real
  Group ID.
- Per-clinic Epic OAuth credentials and per-clinic WhatsApp Business
  Accounts — today's Epic/Meta connections are single, global credentials;
  a second *real* clinic (not the demo clinic used to verify multi-clinic
  mechanics, file 11) needs its own registrations.
- A permanent WhatsApp access token (Meta's test tokens expire every 24h,
  requiring System User verification to fix) and Arabic template approval
  (Meta review, timeline outside this team's control).
- Real clinical/appointment/booking write-back to Epic (`Appointment.create`)
  — Epic's own authorization has already rejected an Appointment search
  attempt in this sandbox; needs a real scope grant.
- Real outcome data accumulation and model retraining on it — the 5 ranking
  models (file 4) are trained exclusively on synthetic data because no real
  patient has yet generated enough real booking/attendance history. This is
  a "wait, then retrain" gap, not a missing feature — `/models`' real-cohort
  quality check honestly reports `insufficient_data` rather than fabricating
  a confidence number.
- Packaging tiers, billing, self-serve onboarding — a commercial/pricing
  decision, explicitly deferred rather than guessed at.
- Connection Hub / Epic Showroom listing — a paid vendor-services
  membership and submission process, not an engineering task.

## Not computable with today's data model (would need new data sources)

- **Provider-level no-show rate, provider schedule-change events** — this
  system has no `provider` entity anywhere (`bookings` has no
  `provider_id` column). Would need real per-provider scheduling data.
- **Weather (`temp_above_45c`)** — would need an external weather API
  integration; nothing here today has any concept of weather at all.
- **Distinct cancellation events** — `bookings.status` only ever
  transitions `booked → attended`; there's no way to tell a genuine
  no-show apart from a booking that was properly cancelled in advance.
  `hist_late_cancel_count_90d` stays at 0 for this reason, honestly, rather
  than guessing.
- **Price-elasticity model (family P's "AI half")** — no real
  discount/price-variation experiment has ever run in this system, so
  there's no data to train real elasticity from. Family P's ranking uses
  `show_probability` (a real, already-trained signal) instead of a
  fabricated elasticity number.
- **A genuine next-event sequence model** — the master spec's "next-event
  engine" would need real chronological campaign history per patient
  across many independent days; today's campaigns were mostly all created
  in the same tight synthetic-seeding window. Descoped to a *unification
  layer* instead: the survival model's predicted time-to-book and the
  no-show model's inverted risk are folded directly into the ranking
  formula (`timing_factor`, `show_probability` — file 4) as an honest
  approximation of what a real sequence model would eventually provide.

## Deliberately built partially, or not wired in, by choice

- **Email channel** (`ve_reach/channels/email.py`) — the send mechanism is
  real and tested. Not wired into dispatch: no email column exists on any
  patient record, no Epic mapping pulls one, and no family policy asks for
  an email channel. Completing those without a concrete need would be
  speculative infrastructure (file 7).
- **`ve_agent`** (LangGraph orchestrator stub) — exists only because the
  architecture diagram names this module. Not built out because Temporal
  already provides durable retries/history/scheduling for free, and no
  concrete use case has come up that Temporal's linear-activity model
  can't handle. Would need a real multi-step *agentic reasoning* need
  (not just "run these steps in order") to justify replacing Temporal.
- **VW intervention chooser / waitlist ranker** — confirmed via full-repo
  search that no code for this exists anywhere (`src/services/
  intervention_chooser.py`, `src/services/waitlist/`, any Vowpal Wabbit
  reference). This would be a brand-new ML subsystem, not a completion —
  needs a product spec (reward signal, action space, how it interacts with
  the existing rule-based dispatch) before it's buildable at all.
- **Vault production backend** — dev mode is in-memory (secrets lost on
  every restart, worked around by a `vault-seed` container that re-seeds
  from env vars on every startup). A real backend (Raft/Consul) needs real
  unseal-key management and different startup semantics — deliberately not
  built against `docker-compose.dev.yml`, since no production deployment
  target exists yet to build it for.
- **Microservice split** (`ve_rules`/`ve_intel`/`ve_decide`/`ve_guard`) —
  empty placeholder directories from an earlier design; everything they'd
  have owned is consolidated into `ve_orchestrator` today. No scale
  evidence yet that a monolith is actually the bottleneck.

## The honest summary

Most of what's "left" is external — waiting on a real clinic, a real Epic/
Meta approval, or real time for outcome data to accumulate — not missing
engineering. Where something looked like a simple missing feature but
turned out to have no real data behind it (price elasticity, provider
no-show rates, a true sequence model), the choice made throughout this
project has been the same: build an honest, documented proxy or explicitly
report `insufficient_data`, rather than fabricate a number that looks
finished but isn't grounded in anything real.
