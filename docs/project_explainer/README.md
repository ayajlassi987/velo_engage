# Velo Engage — Project Explainer

This folder explains **every functionality** in the Velo Engage codebase as it
stands right now: what it does, how it's implemented, and why it was built
that way. It's a companion to `PROJECT_STATUS.md` (the chronological session
log of what changed and when) — this folder is organized by *subsystem*
instead, for someone who wants to understand the whole system rather than
its history.

Velo Engage is a patient-reactivation platform for outpatient clinics. Its
job, end to end: **notice a patient has a legitimate reason to come back,
check they can legally be contacted about it, decide if contacting them is
actually worth it, reach them on WhatsApp, and measure whether it worked** —
run once a day, per clinic, forever, with a built-in causal experiment so the
whole thing can prove it's not just taking credit for visits that would have
happened anyway.

## Reading order

If you're new to the codebase, read these roughly in order — each builds on
the last:

1. [`01_architecture_overview.md`](01_architecture_overview.md) — the daily
   pipeline shape, the services, the data flow end to end.
2. [`02_opportunity_detection.md`](02_opportunity_detection.md) — the 16
   "opportunity families" that decide *who* has a reason to be contacted.
3. [`03_guardrails_and_consent.md`](03_guardrails_and_consent.md) — consent,
   cooldowns, frequency caps, one-message-per-patient de-dup.
4. [`04_ml_models.md`](04_ml_models.md) — the 6 trained models and the
   expected-value ranking formula that decides contact *order*.
5. [`05_holdout_experiment.md`](05_holdout_experiment.md) — the causal
   experiment that proves the system's impact isn't fake.
6. [`06_orchestration_temporal.md`](06_orchestration_temporal.md) — Temporal
   workflows/activities/schedules that actually run all of the above, daily,
   per clinic, reliably.
7. [`07_communication_channels.md`](07_communication_channels.md) — WhatsApp
   (primary), SMS (fallback), email (built, not wired).
8. [`08_epic_integration.md`](08_epic_integration.md) — how real patient data
   gets in from Epic's FHIR API.
9. [`09_clinical_note_intelligence.md`](09_clinical_note_intelligence.md) —
   MedGemma + NemoGuard structured extraction from clinical notes.
10. [`10_console_ui.md`](10_console_ui.md) — the web app clinic staff
    actually look at.
11. [`11_multi_clinic.md`](11_multi_clinic.md) — how one deployment serves
    more than one clinic without data leaking between them.
12. [`12_data_model.md`](12_data_model.md) — every table, what it's for, how
    it connects to the others.
13. [`13_known_gaps_and_roadmap.md`](13_known_gaps_and_roadmap.md) — what's
    genuinely not done, why, and what would unblock it.

## The one-paragraph version

Every day, per clinic, a Temporal workflow: **(0)** best-effort refreshes
real patient data from Epic and recomputes historical booking-behavior
features; **(1)** evaluates 16 independent "opportunity family" rules
against every patient's feature row (some rule-based, some backed by a
Neo4j clinical-guideline graph, one backed by a lookalike/collaborative-
filtering model) to find everyone with a legitimate reason to be
recontacted; **(2)** filters that list down to patients who've actually
consented to the specific *kind* of contact each opportunity represents,
haven't been messaged too recently or too often, and collapses multiple
simultaneous reasons per patient into one; **(3)** scores every survivor
with five trained ML models (no-show risk, booking propensity, expected
revenue, causal uplift, predicted time-to-book) and combines them into a
single expected-value ranking, while independently and randomly holding
back a small "holdout" slice from contact entirely as a causal control
group; **(4)** dispatches the highest-value few (a deliberately small daily
cap) as real WhatsApp messages, with SMS as an automatic fallback on
delivery failure; and **(5)** everything downstream — replies, bookings,
attendance, revenue — flows back in through webhooks (or manual
console entry when no automated feed exists yet) so the next day's
ranking, and eventual model retraining, has real outcomes to learn from.
