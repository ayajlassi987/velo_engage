# 1. Architecture Overview

## The services

| Service | Purpose | Why it's a separate service |
| --- | --- | --- |
| `ve_orchestrator` | Runs the daily pipeline (Temporal workflow + activities): detection, guardrails, ranking, holdout, dispatch. The brain. | Everything that decides *what to do* lives in one place so the decision logic has one owner and one deploy unit. |
| `ve_connect` | Pulls real patient data from Epic's FHIR API (Bulk Data Export + individual reads), maps it into this system's schema, exposes clinical-note extraction. | Epic integration has its own auth flow (SMART Backend Services JWT), its own retry/rate-limit concerns, and its own FHIR-shape-to-internal-schema mapping — isolating it means an Epic outage or auth hiccup can't take down the rest of the pipeline (`pull_epic_data` swallows its own errors). |
| `ve_reach` | Sends WhatsApp messages (Meta Cloud API), handles the SMS fallback (Twilio), receives inbound WhatsApp webhooks (delivery status + patient replies), classifies reply intent. | The only service that talks to Meta/Twilio and holds those credentials; isolating it means a WhatsApp API problem doesn't block detection/ranking from running. |
| `ve_measure` | Listens for booking/billing events (`AppointmentConfirmed`, `AppointmentCompleted`, `Invoice`, `Payment`) over NATS, attributes them back to the campaign that plausibly caused them, and updates outcomes/revenue. | Attribution is its own concern (a 30-day lookback window matching a booking to the right prior campaign) — kept separate from both the decision engine and the send mechanism. |
| `ve_console` | The web app (FastAPI + server-rendered Jinja templates) clinic staff and owners actually look at. | Read-mostly, presentation-focused, needs its own auth/role model (Keycloak) — no reason to share a deploy unit with the pipeline. |
| `ve_clinical_intel` | Runs on a GPU box (DGX Spark), extracts structured diagnoses/medications/risks from unstructured Epic clinical notes using MedGemma, gated by NemoGuard for content safety. | Needs a GPU; everything else in this system doesn't. Physically separate deployment target, so it's a separate service by necessity, not just convention. |
| `ve_agent` | **Not deployed.** A stub showing the same pipeline shape as a LangGraph `StateGraph` instead of a Temporal workflow. | Exists only because the original architecture diagram names a "LangGraph orchestrator" module — kept as a documented placeholder, not built out, because Temporal already does this job with durable retries or free. See `13_known_gaps_and_roadmap.md`. |
| `ve_store`, `ve_intel`, `ve_rules`, `ve_guard`, `ve_decide` | **Empty directories.** Named in an earlier microservice-split design; every one of their responsibilities (feature storage, rule evaluation, guardrails, ranking decisions) was consolidated into `ve_orchestrator` instead. | A monolith-first choice — no evidence yet that scale requires splitting these out, so they weren't force-split just to match a diagram. |

## The daily pipeline, step by step

Everything below is one Temporal workflow (`DailyEngagementWorkflow`,
`services/ve_orchestrator/src/ve_orchestrator/workflows.py`), running once
per clinic per day (see `06_orchestration_temporal.md` for exactly how the
schedule/retry/timeout mechanics work). Each step is a separate Temporal
*activity* — a unit of work that can retry independently without re-running
everything before it.

```
pull_epic_data              (best-effort; failure doesn't block the rest)
        |
refresh_historical_features (recompute no-show-model history from real bookings)
        |
evaluate_rules(clinic_id)   (16 opportunity families -> opportunity_ids)
        |
gate_consent(opportunity_ids)  (consent + cooldown + freq cap + de-dup -> allowed_ids)
        |
rank_and_assign_holdout(allowed_ids, run_date)  (5 ML models -> expected_value; random holdout split -> campaign_ids)
        |
dispatch_treated_to_reach(campaign_ids)  (top N by expected_value -> NATS -> ve_reach -> WhatsApp)
```

Downstream of dispatch, asynchronously:

```
ve_reach's WhatsApp webhook  -> outcomes.delivered / read / replied
ve_reach's reply handler     -> intent_scorer classifies "booking_intent" -> booking_requested
ve_measure's booking_listener -> outcomes.booked / attended, bookings, revenue_attributions
ve_console's manual outcome endpoint -> same tables, for outcomes with no automated feed yet
```

## Why this shape

- **Detect broadly, then narrow aggressively.** Step 1 (`evaluate_rules`)
  intentionally over-generates — any patient matching *any* of 16 rules
  becomes a candidate. Every step after that removes candidates for a
  specific, named reason (no consent, contacted too recently, a better
  reason already claimed this patient, not in today's top-N by value).
  That means at any point you can ask "why didn't patient X get
  contacted today" and get a real, logged answer instead of "the model
  said no."
- **Rule-based detection, ML-based ranking.** *Whether* a patient has a
  legitimate reason to be contacted is (mostly) a deterministic policy
  question — encoded as data (`policies/opportunities/*.yml`), not a
  model. *Which* of several legitimate candidates to contact first, and
  whether it's worth it at all, is where the ML models earn their keep
  (see `04_ml_models.md`). Mixing these up would make the system both
  less auditable (a clinician can't review a rule engine's YAML the same
  way they can review a black-box model) and less effective (ranking is
  a genuinely hard, continuous problem; "does this patient have an
  overdue treatment plan" isn't).
- **A causal holdout is load-bearing, not optional.** Nothing here would
  prove the system is *causing* extra bookings rather than just
  contacting patients who were going to book anyway — that's exactly
  what the holdout arm (`05_holdout_experiment.md`) and the uplift model
  are for.
- **Best-effort external dependencies, hard-fail internal ones.**
  `pull_epic_data` swallows its own errors (an EHR integration hiccup
  shouldn't take down a same-day pipeline run against whatever data is
  already there); `refresh_historical_features`/`evaluate_rules`/etc. use
  Temporal's real retry policy (a transient DB error *should* surface
  and retry, not be silently absorbed) — see `06_orchestration_temporal.md`
  for the retry policy specifics.
