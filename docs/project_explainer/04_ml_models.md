# 4. ML Models and the Ranking Formula

## Purpose

Detection says *who's eligible*. Guardrails say *who's contactable*.
Ranking says **who's worth contacting today, and in what order**, given a
daily dispatch cap far smaller than the guardrail-passed candidate list.
That's what the five ranking models plus the expected-value formula in
`rank_and_assign_holdout` (`ve_orchestrator/activities.py`) do. Two more
models — lookalike and intent — serve different, earlier/later parts of the
pipeline. All models are trained offline (`ml/training/train_*.py`),
tracked and versioned in MLflow, and loaded at scoring time via
`ml/registry/*.py` using a shared `resolve_production_version()` pattern
(load whatever's currently tagged Production in MLflow, not a hardcoded
version number).

Every registry scorer degrades gracefully: if MLflow is unreachable or a
model fails to load, `rank_and_assign_holdout` catches the exception,
logs a warning, and substitutes a safe neutral fallback (e.g. rule
`priority_score` for no-show/propensity, `1.0` neutral multiplier for
value/uplift) rather than crashing the whole day's pipeline run over one
model being briefly unavailable.

## The five ranking models

| Model | MLflow name | Trained in | Answers | Real-data status |
| --- | --- | --- | --- | --- |
| No-show risk | `ve_noshow_v1` | `train_noshow_model.py` | P(patient books but doesn't show up) | Trained on synthetic data (`ml/data/generated/synthetic_noshow/`); scores every real patient live (see below for a feature-completeness caveat) |
| Booking propensity | `velo_engage_booking_propensity` | `train_propensity.py` | P(this contact results in a new booking at all) | Synthetic-trained |
| Value | `velo_engage_value_amount` | `train_value_model.py` | E[revenue \| patient books] — a trained regressor over family/high-value-flag/insurance-tier, times a base "any revenue at all" rate read from the model's own MLflow run params (not hardcoded, since attendance-conditional revenue turned out independent of every other feature in this dataset — no classifier could beat the empirical constant) | Synthetic-trained |
| Uplift | `velo_engage_uplift_treated` / `velo_engage_uplift_control` | `train_uplift_model.py` | The **causal** effect of contact: a T-learner — two separately-trained classifiers (one on historically-treated patients, one on historically-control/holdout patients), each predicting P(book \| their arm's features); uplift = treated-model prediction − control-model prediction | Synthetic-trained; the T-learner design is what makes it trainable at all — see `05_holdout_experiment.md` |
| Survival / time-to-need | `velo_engage_survival` | `train_survival_model.py` | Predicted days until this patient would book if contacted — a LightGBM regression on `log1p(days_to_book)` | Trained on **3,603 real timing examples** once real per-stage outcome timestamps existed (see below) — the one model in this list with a real, non-synthetic training set |

### The expected-value formula

```
persuadable_multiplier = 1.0 if uplift_score > 0 else 0.1
timing_factor          = 1.0 / (1.0 + predicted_days_to_book / 30.0)
show_probability       = 1.0 - noshow_score
expected_value = priority_score * propensity_score * value_score
                 * persuadable_multiplier * timing_factor * show_probability
```

Read left to right: **is this contact appropriate at all** (rule
`priority_score`) **× will it plausibly result in a booking** (propensity)
**× how much is that booking worth** (value) **× is this patient actually
persuadable by contact, or would they book/not-book regardless**
(uplift-gated 10x discount for non-persuadables — this is the causal
component; without it, ranking would just favor patients who were going to
book anyway) **× how soon, given a fixed daily dispatch budget, would
contacting them pay off** (the survival model, hyperbolically discounted so
a slower predicted booking doesn't get zeroed out, just deprioritized) **×
how likely are they to actually show up once booked** (no-show risk,
inverted). The highest-`expected_value` campaigns get dispatched first once
`DISPATCH_LIMIT` truncates the list (file 6 covers the dispatch step
itself).

### Why uplift gates persuadability instead of just ranking by propensity

A patient with high booking propensity might book *regardless of contact*
("a sure thing") — contacting them isn't wrong, but it's not where scarce
outreach capacity should go first. A patient with very low propensity might
be genuinely unreachable ("a lost cause") — same conclusion, different
reason. The uplift model is the only one of the five actually estimating
the *causal* effect of contact rather than a correlational prediction, and
it's only trainable because of the holdout arm's randomized assignment (see
file 5) — without a genuine randomized control group, there'd be no valid
way to estimate "what would have happened without contact."

### Why family P's "AI half" doesn't exist as a separate model

The master spec calls for family P (operational yield / slot-fill) to have
a price-elasticity AI component — how demand responds to a discount. No
real discount/price-variation experiment has ever run in this system, so
there's no data to train real elasticity from anywhere in this schema.
Rather than fabricate one, family P's ranking uses the same
`show_probability` term (`1 - noshow_score`) as every other family: a
patient likely to book but also likely to no-show doesn't actually solve a
scarce-slot yield problem, which is the real operational question family P
is meant to answer. Applied universally (not special-cased to family P)
because a wasted contact from a no-show is a real cost for every family,
not just this one.

## Two more models, serving different parts of the pipeline

### Lookalike / collaborative-filtering (family D's AI half)

`velo_engage_lookalike`. Answers: "this patient has never engaged with
family X, but do patients who share their *other* engagement patterns
respond well to family X?" Implementation: a co-occurrence heuristic
(`CooccurrenceLookalikeModel` in `ml/training/train_lookalike_model.py`) —
`P(patient has family Y | patient has family X)`, computed directly via a
crosstab and matrix multiplication, gated by a minimum-support threshold so
rare co-occurrences don't produce noisy recommendations.

**Why not matrix factorization (the "standard" approach here):** the first
real attempt used `sklearn.decomposition.NMF` and scored AUC 0.29 — worse
than random. Rather than ship that or silently drop the feature, the
failure was diagnosed: 74% of patients have only one family interaction
ever recorded, nowhere near enough signal for a learned embedding. A
corrected per-patient train/eval split confirmed this wasn't an evaluation
bug — NMF genuinely can't learn from this little data per patient. The
co-occurrence approach, which needs much less data per patient, scored
AUC 0.86 on the identical data, confirming the original failure was a
method/data-sparsity mismatch, not unlearnable data. This diagnostic
process (fail → investigate why → fix the actual mismatch, not just retry
harder) is preserved in `PROJECT_STATUS.md` §9 for anyone revisiting this.

### Intent classifier

`ve_intent_v1` (`ml/training/train_intent_classifier.py`,
`ml/registry/intent_scorer.py`). Classifies free-text inbound WhatsApp
replies (e.g. "yes book me in", "stop messaging me") into an intent label —
`booking_intent`, `opt_out`, etc. Feeds `inbound_messages.detected_intent`,
which in turn feeds the console's `booking_requested` flag and the opt-out
mechanism. Separate from the five ranking models because it runs on
inbound patient text at reply-time, not on structured patient features at
ranking-time.

## The honest caveat that applies to all of the above

Every model here (except survival) is trained exclusively on synthetic
data, because no real patient has yet accumulated enough real outcome
history to train on. The scoring **mechanism** is real and running — every
real patient gets genuinely computed, differentiated scores on every
pipeline run, verified directly against Postgres. Whether those specific
numbers are *well-calibrated* for real patients specifically is a separate,
harder, and currently unanswered question — `ve_console`'s `/models` page
has a real-cohort quality check that correctly reports `insufficient_data`
for the real population rather than fabricating a confidence number. See
`13_known_gaps_and_roadmap.md`.

The no-show model has one further caveat worth knowing:
`ml/registry/scorer.py`'s `STAGE1_FEATURES` list names 32 required
features, 15 of which didn't exist as `patient_features` columns until a
recent fix (`infra/migrations/018_noshow_historical_features.sql` +
`ve_orchestrator/historical_features.py`) — before that, the model was
silently scoring every patient with constant placeholder values for those
15 features. 11 of them now get real values computed from actual
booking/message history on every pipeline run (a documented rule-based
proxy for "no-show," since this system has no distinct cancellation event
type to tell a genuine no-show apart from a properly-cancelled booking);
the other 4 (provider-level rate, provider schedule-change, weather) stay
on fixed defaults because no provider entity or weather data source exists
anywhere in this schema to compute them from.
