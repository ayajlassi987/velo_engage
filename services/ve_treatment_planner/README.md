# ve_treatment_planner

**Status: prototype.** Implements the dental treatment-pathway state
machine as one Temporal workflow instance per patient-case (per tooth/
diagnosis, not per patient). See `policies/dental_pathways/README.md` for
why: nothing produced here should be treated as a real clinical suggestion
until a named clinical advisor reviews the pathway it came from.

## Why Temporal, not a bespoke engine

Temporal workflows are already durable state machines. Modeling each
patient-case pathway as a workflow instance gets durable state, timers
(healing periods, recall intervals), and a full audit trail (Temporal's own
workflow event history) for free — no separate engine, no separate
transitions-log storage layer to build and trust, though a thin read-model
table (`patient_treatment_state`) still exists so the console can query
current state without talking to Temporal directly, and
`treatment_transition_log` still exists as the durable feedback-loop record
(accept/override + reason) that trains a future ranker.

## The one place "advisory, never autonomous" is actually enforced

`activities.py`'s `advance_case()`: if exactly one transition is valid from
a case's current state, it's applied automatically — the rule graph already
made that decision unambiguously, there's nothing for a clinician to weigh
in on. If more than one transition is valid, **nothing is applied
automatically** — the options are recorded as a pending suggestion, and the
workflow waits for `record_decision` (the console's accept/override action)
before moving. Read this function before changing it; it's the actual
safety boundary this whole service exists to preserve.

## Running it

Two processes share this image (`Dockerfile`): the FastAPI front door
(`main.py`, default `CMD`) that starts/signals/queries case workflows, and
the Temporal worker (`worker.py`) that actually executes them — both need
to be running, same as `ve_orchestrator`'s worker + trigger split. Neither
does anything without `ve_connect_dental` populating
`dental_procedure_history` for the activities to read.

## What's not built yet

- Enforcing `status: clinician_reviewed` before `initialize_case` will
  start a workflow against a pathway (see `activities.py`'s docstring) —
  there's currently nothing clinically reviewed to enforce it against.
- Diagnosis-confirmed triggers are unreachable — no diagnosis/problem-list
  source is pulled from OpenDental yet (`ve_connect_dental`'s current scope
  is procedures/appointments/patient only).
- The edge-ranker (`pathway_engine.rank_transitions`'s `edge_scores`
  parameter) has no real implementation behind it yet — every ranking
  today falls back to each transition's static YAML `priority`.
- A console page to show pending suggestions and call `/decision` doesn't
  exist yet.
- The real trigger mechanism (`POST /cases/{id}/events`) is only ever
  called manually/by a future integration — nothing currently wires it to
  `ve_connect_dental`'s pull automatically.
