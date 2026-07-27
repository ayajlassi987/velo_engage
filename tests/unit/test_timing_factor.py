"""Tests _timing_factor (ve_orchestrator/activities.py) — the piece that
folds the survival model's predicted days-to-book into expected_value
ranking, closing the gap the code used to flag as deliberately deferred
(see PROJECT_STATUS.md's next-event-engine section). Pure function, no
DB/Temporal needed."""

import ve_orchestrator.activities as activities


def test_zero_days_gives_factor_of_one():
    assert activities._timing_factor(0) == 1.0


def test_half_life_gives_factor_of_half():
    assert activities._timing_factor(activities.TIMING_HALF_LIFE_DAYS) == 0.5


def test_longer_predicted_days_gives_smaller_factor():
    assert activities._timing_factor(10) > activities._timing_factor(60)


def test_factor_never_negative_or_above_one():
    for days in [0, 1, 10, 30, 100, 1000]:
        factor = activities._timing_factor(days)
        assert 0 < factor <= 1.0


def test_none_is_neutral_no_discount():
    assert activities._timing_factor(None) == 1.0


def test_negative_days_treated_as_neutral():
    """Shouldn't happen in practice (a real model prediction), but a
    negative input must not produce a factor > 1 (which would boost EV
    beyond what a legitimate 0-day prediction gives)."""
    assert activities._timing_factor(-5) == 1.0
