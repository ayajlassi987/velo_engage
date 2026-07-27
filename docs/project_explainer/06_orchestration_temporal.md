# 6. Orchestration — Temporal

## Purpose

Something has to actually run the daily pipeline (file 1), reliably, once
per clinic per day, retrying transient failures without re-running work
that already succeeded, and doing this identically whether triggered by a
schedule, manually, or after a worker restart. That's Temporal's job here —
not a cron job calling a script, because a plain cron job re-executed
end-to-end on failure would double-dispatch messages, double-count
opportunities, and generally violate every idempotency guarantee this
system relies on.

## The pieces

- **`workflows.py`** — `DailyEngagementWorkflow`, a `@workflow.defn` class.
  Defines the *sequence* of activities (file 1's diagram) and how data flows
  between them. Workflow code must be deterministic (Temporal replays it
  from history on recovery) — this is why `run_date` is derived from
  `workflow.now()` rather than wall-clock time when a scheduled run invokes
  it with no explicit date.
- **`activities.py`** — the actual work: `pull_epic_data`,
  `refresh_historical_features`, `evaluate_rules`, `gate_consent`,
  `rank_and_assign_holdout`, `dispatch_treated_to_reach`. Each is a
  `@activity.defn` function — allowed to do non-deterministic things
  (DB calls, HTTP calls, `random.random()`) that workflow code itself can't.
- **`worker.py`** — connects to the Temporal server, registers the workflow
  and every activity function it's willing to execute, and polls
  `velo-engage-task-queue` for work. Must run continuously — if it's down,
  scheduled workflows queue up but don't execute until a worker reconnects.
  **A new activity function has to be registered in two places** —
  imported and listed in `worker.py`'s `activities=[...]` list, *and*
  imported in `workflows.py` — missing either one produces a
  `NotFoundError: Activity function ... is not registered on this worker`
  at execution time, not at startup.
- **`schedules.py`** — creates one Temporal Schedule per active clinic
  (`daily-engagement-schedule-{clinic_id}`, cron `0 2 * * *`,
  `ScheduleOverlapPolicy.SKIP` so a slow run doesn't stack with the next
  day's). Idempotent and IaC-style: reads `clinics WHERE active` from
  Postgres, skips any clinic whose schedule already exists rather than
  erroring or duplicating it. Written specifically to replace an earlier
  hand-created schedule that had no reproducible record of its own
  configuration — a real gap discovered while adding a second clinic.
- **`trigger.py`** — a CLI for manually firing a specific clinic's workflow
  outside its schedule (used constantly during development/testing).

## Retry and timeout policy

Every activity call in `workflows.py` uses `RetryPolicy(maximum_attempts=3)`
and a 10-minute `start_to_close_timeout`, **except** `pull_epic_data`
(`maximum_attempts=1`, 15-minute timeout) — deliberately not retried,
because its own docstring explains it already swallows its own errors and
returns a `{"status": "failed", ...}` result rather than raising, so the
rest of the pipeline can proceed against whatever `patient_features` data
already exists. Retrying it would just delay the rest of the day's pipeline
for no benefit. Every other activity is allowed to genuinely fail and
retry — a transient Postgres blip during `refresh_historical_features`
*should* surface and retry, not be silently absorbed the way an Epic
connectivity issue is.

## Multi-clinic scoping

`evaluate_rules` and `refresh_historical_features` are the only activities
that take `clinic_id` as an explicit argument — they're the ones that
decide *which clinic's patient population* to operate on. Every activity
downstream (`gate_consent`, `rank_and_assign_holdout`,
`dispatch_treated_to_reach`) operates purely on the opportunity/campaign
IDs it's handed and reads each row's own `clinic_id` column from the
database, rather than filtering by a separately-passed parameter — so they
stay correctly scoped without every activity needing to know which clinic
explicitly. See `11_multi_clinic.md` for the full data-model side of this
(consent, campaigns, patient_features all keyed by `clinic_id`).

## Why Temporal instead of a simpler scheduler

Every one of the following is something a hand-rolled cron+script setup
would have to reimplement from scratch, and Temporal provides for free:
step-level retries with backoff (a `gate_consent` DB hiccup doesn't force
re-running `evaluate_rules`), durable workflow history (a crashed worker
resumes exactly where it left off, not from the beginning), and
`ScheduleOverlapPolicy.SKIP` (a slow day's run can't stack with the next
day's trigger). `ve_agent`'s LangGraph stub exists specifically to show
what replacing this with a different orchestration model would look like —
see `13_known_gaps_and_roadmap.md` for why that hasn't happened and,
per an explicit user decision, isn't being built without a concrete reason
Temporal can't already handle.
