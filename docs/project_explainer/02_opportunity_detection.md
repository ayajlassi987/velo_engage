# 2. Opportunity Detection — the 16 families

## Purpose

Before anything gets ranked or sent, the system needs to answer: **does
this patient have any legitimate reason to be contacted right now?** That
question is answered by 16 independent, named "opportunity families" — each
one a self-contained policy that either matches a patient or doesn't. A
patient can match zero, one, or several families on the same day (only the
highest-priority match survives de-dup — see `03_guardrails_and_consent.md`).

## How it's implemented

Every family is a YAML file in `policies/opportunities/` (`A.yml` through
`Q.yml`, skipping `N`), loaded and evaluated by
`services/ve_orchestrator/src/ve_orchestrator/policy_engine.py`. A family
definition has four parts:

```yaml
family: A
title: Dormancy / personal-cadence anomaly
methods: [R, D]              # R=rule, D=data-driven flag, AI=model, Graph=Neo4j
rule:
  consent_class: care_recall  # which consent this family requires (see file 3)
  priority: 0.70              # used for de-dup ranking AND as the "priority_score" ranking input
  conditions: {...}           # a boolean expression over patient_features columns
delivery:
  template: {...}             # the WhatsApp template to use if this family fires
```

`policy_engine.py`'s `evaluate_policy()` walks the `conditions` tree
(`all`/`any` combinators over leaf checks like `eq`, `gt`, `not_null`,
`days_until_between`, `contains_prefix`) against one patient's full
`patient_features` row and returns match evidence (or `None`). This runs
once per patient per family per day inside the `evaluate_rules` Temporal
activity — for a small clinic's real patient population this is cheap; for
the ~20,000-row synthetic demo population it's excluded entirely (see
`feature_store.py`'s `fetch_patient_features`, which filters out
`SYN%`/`P0%` patient_ids from live evaluation on purpose — that population
exists for ML training data, not for the live pipeline to re-evaluate every
day).

### The `contains_prefix` operator

Added specifically for family I. Epic returns full-precision ICD-10 codes
(`"E11.9"`); this system's synthetic training/seed data uses bare 3-character
categories (`"E11"`). A plain `contains`/`equals` check would never match a
real Epic patient against a rule written for the category. `contains_prefix`
does `any(code.startswith(expected) for code in actual)` so both
representations match the same rule. As of the most recent audit (see
`13_known_gaps_and_roadmap.md`), family I is the only family that checks a
condition-code field at all, so it's the only one that needs this operator.

## The 16 families

| Family | Title | Method | Consent class | Priority | What triggers it |
| --- | --- | --- | --- | --- | --- |
| A | Dormancy / personal-cadence anomaly | Rule | `care_recall` | 0.70 | `days_since_last_visit > 180` |
| B | Clinical recall (condition/age/sex) | **Neo4j graph** | `clinical_recall` | 0.85 | A condition/age match against a clinical-guideline graph (see below) says a recall is due |
| C | Open / incomplete treatment plans | Rule | `care_recall` | 0.90 | `open_treatment_plan_flag = true` AND (never visited or `days_since_last_visit > 30`) |
| D | Cross-specialty (gap + lookalike) | Rule **+ lookalike model** | `care_coordination` | 0.75 | A cross-specialty gap flag, or the lookalike model recommending a family based on similar patients (see `04_ml_models.md`) |
| E | Event / seasonal (derma/beauty) | Rule | `promotional_outreach` | 0.45 | `seasonal_event_eligible_flag = true` |
| F | Behavioural / engagement drop | Rule | `engagement` | 0.50 | `engagement_drop_flag = true` |
| G | Benefit / financial lifecycle | Rule | `care_recall` | 0.80 | Coverage expires in 0–45 days |
| H | Preference-based | Rule | `preference_outreach` | 0.55 | `preference_match_flag = true` |
| I | Predictive clinical risk / deterioration | Rule (real, not a model) | `clinical_recall` | 0.85 | A chronic-disease ICD-10 prefix match (diabetes, hypertension, CAD, heart failure, COPD, asthma) AND `days_since_last_visit > 240` |
| J | Care-gap analysis (guideline sweep) | Rule | `care_recall` | 0.88 | `care_gap_due_flag = true` |
| K | Digital intent (abandoned booking) | Rule | `digital_followup` | 0.65 | `abandoned_booking_flag = true` |
| L | Treatment/product lifecycle (re-treatment, refills) | Rule | `care_recall` | 0.72 | `treatment_lifecycle_due_flag = true` |
| M | Household & life-stage | Rule | `household_outreach` | 0.40 | `household_lifestage_eligible_flag = true` |
| O | External / contextual (allergy/UV/flu/events) | Rule | `contextual_outreach` | 0.60 | `contextual_trigger_flag = true` |
| P | Operational yield (slot fill) | Rule | `operational_offer` | 0.35 | `slot_fill_eligible_flag = true` (its "AI half" — a price-elasticity model — doesn't exist; see `04_ml_models.md` and `13_known_gaps_and_roadmap.md` for why) |
| Q | Outcome / quality follow-up | Rule | `quality_followup` | 0.82 | `quality_followup_due_flag = true` |

Most of these (`_flag` columns) are booleans computed upstream — either by
Epic-derived features (`open_treatment_plan_flag`, `coverage_period_end_date`)
or by synthetic seeding for demo purposes (`scripts/seed_synthetic_phase1.py`'s
`POLICY_FAMILY_FLAGS`, which randomly assigns each flag with a documented
probability so the synthetic population exercises every family realistically).
For real Epic patients, only the families backed by genuinely-derivable Epic
data (A, C, G, I, and B via the graph) can ever fire — the others require
flags this system has no real data source for yet (see
`13_known_gaps_and_roadmap.md`).

### Family B — the Neo4j clinical-recall graph

The only family whose logic lives as *data in a graph database* rather than
as a YAML condition. `services/ve_orchestrator/src/ve_orchestrator/graph_client.py`
runs two Cypher queries against Neo4j: one matching a patient's ICD-10 codes
to `(Condition)-[:REQUIRES_FOLLOWUP]->(Service)` edges, one matching age
bands to `(AgeBand)-[:SCREENING_DUE]->(Service)` edges — e.g. "diabetes
(E11) requires HbA1c monitoring via Endocrinology every 90 days." Why a
graph instead of more YAML: this is genuinely relational, clinical-guideline
knowledge (condition → recommended follow-up service → specialty), and
representing it as a graph makes it independently editable by someone
maintaining clinical content without touching the rule-evaluation code.
Batched across the whole patient cohort in one query (`clinical_recall_due_batch`)
rather than one Neo4j round-trip per patient — the worst-scaling part of
`evaluate_rules` otherwise. Falls back to the plain `clinical_recall_due_flag`
feature (same as every other family) if Neo4j is unreachable, logged once
rather than per-patient.

### Family D's lookalike/cross-sell half

Separate from D's rule-based half (`cross_specialty_gap_flag`). Detects
patients who've never engaged with a particular family but resemble (by
co-occurrence pattern) other patients who did. See `04_ml_models.md` for how
this model works and why it replaced an initial matrix-factorization
attempt that failed for a real, diagnosed reason (data sparsity, not a
coding bug).

### Family I — a real rule, deliberately not tagged as AI

The master spec calls for a "predictive deterioration risk" family. There is
no real deterioration-outcome data anywhere in this system to train a model
against (no clinic-confirmed "this patient deteriorated" label exists).
Rather than fabricate a fake model to satisfy the name, family I is built as
an honest, clinically-reasonable rule: a chronic-disease diagnosis plus a
long gap since last visit. Its `methods: [R]` tag (not `[R, AI]`) is
deliberate — it says plainly this is a rule, not a trained model, so nobody
reading the policy file is misled about what's actually driving it.
