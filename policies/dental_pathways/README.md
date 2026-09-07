# Dental treatment pathway graphs

Each `*.yml` file here is a state machine for one dental specialty pathway,
loaded and validated by `ve_treatment_planner`'s `pathway_engine.py`. Same
authoring philosophy as `policies/opportunities/*.yml`: **clinical logic is
data, not code**, so a domain expert can review and edit it directly.

## `status` — the field that actually matters

Every pathway file has a top-level `status`:

- `prototype` — engineering scaffolding only. Content was written to prove
  the state-machine/Temporal design works end to end, **not** by a dental
  clinical advisor. Nothing derived from a `prototype` pathway should ever
  be shown to a real clinician as an actual suggestion — `ve_treatment_
  planner` should refuse to serve suggestions from a pathway in this state
  outside of local/test environments (enforce this before any real rollout;
  not yet enforced in this prototype).
- `clinician_reviewed` — a named clinical advisor has reviewed and signed
  off on every state and transition. Required before this pathway can
  suggest anything to a real dentist in production.

## Schema

```yaml
version: 1
pathway: <unique id, matches the filename stem>
title: <human title>
status: prototype | clinician_reviewed
reviewed_by: <name, required once status is clinician_reviewed>
specialty: <free text>

states:
  - id: <unique within this file>
    title: <human title>
    entry_codes: [<CDT codes that place a case in this state when first observed>]
    terminal: <true | false>

transitions:
  - from: <state id>
    to: <state id>
    trigger:
      type: procedure_performed | diagnosis_confirmed | time_elapsed
      codes: [<CDT codes>]        # procedure_performed
      code: <diagnosis code>       # diagnosis_confirmed
      min_days: <int>              # time_elapsed
    guard:
      time_elapsed_min_days: <int>  # optional additional gate
    priority: <float, higher = preferred when multiple transitions are valid>
```

Validation (`pathway_engine.load_pathways()`) enforces: every `from`/`to`
references a state that exists, every state id is unique, at least one
terminal state exists, and every state is reachable from at least one state
with no incoming transitions (the pathway's implicit entry points) — a
malformed or unreachable state fails to load rather than silently degrading
the graph a patient could get stuck in.
