# 5. The Holdout Experiment

## Purpose

Answer one question this system cannot get right any other way: **is
Velo Engage actually causing extra bookings, or just contacting patients
who were going to book anyway and taking credit for it?** Every metric on
`/revenue` and `/holdout` (booking rate, recovered revenue, ROI) is
meaningless without this — a naive "compare booked patients before/after
Velo Engage" measurement can't distinguish "contact caused this" from
"this patient books regardless, we just happened to also message them."

## How it's implemented

In `rank_and_assign_holdout` (`ve_orchestrator/activities.py`), *after*
every guardrail-passed candidate has been scored, each one is randomly
assigned an arm:

```python
seed = HOLDOUT_SEED_BASE + today.toordinal()   # deterministic per calendar day
rng  = random.Random(seed)
arm  = "holdout" if rng.random() < HOLDOUT_RATE else "treated"   # HOLDOUT_RATE = 0.15
```

- **Treated arm (~85%)**: eligible for real dispatch, subject to
  `DISPATCH_LIMIT` truncation by `expected_value_score`.
- **Holdout arm (~15%)**: a real `campaigns` row gets created (so it's
  fully visible in the console, fully counted in every metric), but
  `dispatch_treated_to_reach` only ever reads rows `WHERE treatment_arm =
  'treated'` — a holdout campaign is structurally incapable of being sent.

The critical property: **assignment happens independently of ranking**.
A patient with the highest `expected_value_score` in the whole clinic can
still land in holdout — this is required for the causal comparison to be
valid. If holdout only ever caught "low-value" patients, any booking-rate
difference between arms would be confounded by exactly the same value
differences the ranking model is supposed to capture, not by contact
itself.

## The non-negotiable safety gate

```sql
SELECT * FROM campaigns WHERE treatment_arm='holdout' AND dispatched_at IS NOT NULL;
```

Documented in `TESTING_GUIDE.md`/`RELEASE_CHECKLIST.md` as must-always-be-
zero-rows (one pre-existing 2026-07-03 row predates current safeguards and
is a known, documented exception). Any *other* row here is a release-
blocking bug — it means the experiment's control group was contaminated,
silently invalidating every causal claim the system makes about itself.

As of a recent fix (see `13_known_gaps_and_roadmap.md` and
`10_console_ui.md`), the manual outcome-marking feature in the console
explicitly rejects any attempt to mark a holdout campaign booked/attended,
for the identical reason: crediting a holdout patient with an outcome would
corrupt the same causal comparison just as badly as an accidental real
dispatch would, even though no message was actually sent.

## Why this specific design, not something simpler

- **Why not just A/B test dispatch on/off globally, alternating days?**
  Because patient-level randomization is required to control for
  patient-level confounds (some patients are just more likely to book
  regardless of anything) — day-level randomization would only control for
  day-level confounds (which barely exist here) while leaving patient-level
  ones completely uncontrolled.
- **Why 15%, not 50%?** A real clinic loses real revenue opportunity on
  every holdout patient — the experiment's statistical power has to be
  balanced against that real cost. 15% is small enough to limit that cost
  while still being enough volume to detect a real effect.
- **Why does uplift modeling (file 4) need this too?** The T-learner uplift
  model is trained on exactly this treated/holdout split — it's the
  *reason* two arm-specific classifiers (rather than one, with treatment as
  a feature) can validly estimate a causal effect at all. Without a real
  randomized holdout, there'd be no valid ground truth to train or evaluate
  uplift against.
