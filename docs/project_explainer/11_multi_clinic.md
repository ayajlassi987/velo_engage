# 11. Multi-Clinic Productization

## Purpose

Turn a system that only ever worked correctly for one hardcoded clinic
into one that can genuinely serve several, with zero data leaking between
them — a real productization requirement, not just a scaling concern.

## What was already there vs. what was missing

Every table already had a `clinic_id` column (confirmed by investigation
before building anything new) — so the raw data model was already
tenant-scoped. What was missing: nothing recorded *which clinics actually
exist*, nothing recorded *which clinic a logged-in console user belongs
to*, the orchestrator only ever ran for one hardcoded `CLINIC_ID` env var,
and one campaign-detail query was missing a `clinic_id` filter entirely —
a real cross-tenant information-disclosure bug (any logged-in user could
view any other clinic's campaign detail page just by guessing its ID),
found and fixed while adding this.

## The data model

`infra/migrations/017_clinics.sql`: a `clinics` table (one row per clinic)
and a `clinic_users` table — **one clinic per username**, deliberately not
a many-to-many membership table. A real multi-location group (one person
overseeing several clinics) is a plausible future need, but nothing in this
codebase's auth model (Keycloak roles are unrelated to clinic identity) has
ever supported switching between clinics, and nothing asked for it here.
One clinic per user is the simplest thing that actually proves data
isolation works end to end — adding many-to-many machinery for a use case
nobody requested would be speculative.

## Console: clinic-aware sessions

`auth.py`'s `_resolve_clinic(username)` queries `clinic_users`/`clinics` at
login time and stores `clinic_id`/`clinic_name` in the session — falling
back to a default clinic (with a logged warning) on any lookup failure,
rather than breaking login entirely. Every one of `main.py`'s ~25 routes
was converted from a module-level `CLINIC_ID` constant to a per-request
`_clinic_id(request)` helper reading the session. The login page no longer
names one hardcoded clinic ("...open your clinic's console" instead of
"...open Al Noor Clinic's console").

## Orchestrator: per-clinic pipeline runs

`workflows.py`'s `DailyEngagementWorkflow.run()` takes an explicit
`clinic_id` argument. Only `evaluate_rules` and `refresh_historical_features`
need it directly — they're the ones deciding which clinic's patient
population to operate on; every activity downstream reads each row's own
`clinic_id` from the database instead (file 6 covers why). `schedules.py`
creates one Temporal Schedule per active clinic
(`daily-engagement-schedule-{clinic_id}`), replacing an earlier hand-created
single schedule that had no reproducible record of its own configuration.

## Verified, not just built

A second demo clinic (`clinic_demo_002`, "Riverside Dental Group") was
seeded and run through the full pipeline specifically to prove isolation —
confirmed live: each clinic's schedule fires independently, campaigns and
opportunities stay correctly scoped, and a logged-in user for one clinic
cannot see the other's data anywhere in the console (including the
cross-tenant campaign-detail bug found and closed during this work).

## Why this scope, not more

Per an explicit decision made when this was built: go only as far as
"build the core mechanism, verify with a second demo clinic" — not stand up
a genuinely separate second real clinic with its own Epic/WhatsApp
credentials, because those are external registrations a second real clinic
would have to complete themselves (see file 13). Packaging tiers, billing,
and self-serve onboarding are explicitly out of scope here too — a
commercial/pricing decision, not an engineering one, deliberately deferred
rather than guessed at.
