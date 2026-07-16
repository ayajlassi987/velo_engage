import random

from ve_console.drift import compute_psi, PSI_CRITICAL_THRESHOLD, PSI_WARNING_THRESHOLD, MIN_BUCKET_SAMPLES


def test_insufficient_data_below_min_bucket_samples():
    result = compute_psi([0.5] * 5, [0.5] * 5, buckets=10)
    assert result["status"] == "insufficient_data"
    assert result["psi"] is None


def test_identical_distributions_are_stable():
    rng = random.Random(42)
    baseline = [rng.random() for _ in range(500)]
    current = list(baseline)  # exact same distribution
    result = compute_psi(baseline, current)
    assert result["status"] == "stable"
    assert result["psi"] < PSI_WARNING_THRESHOLD


def test_wildly_shifted_distribution_is_critical():
    rng = random.Random(42)
    baseline = [rng.uniform(0.0, 0.1) for _ in range(500)]
    current = [rng.uniform(0.9, 1.0) for _ in range(500)]
    result = compute_psi(baseline, current)
    assert result["status"] == "critical"
    assert result["psi"] >= PSI_CRITICAL_THRESHOLD


def test_baseline_n_and_current_n_reported():
    result = compute_psi([0.5] * 200, [0.5] * 150)
    assert result["baseline_n"] == 200
    assert result["current_n"] == 150


def test_exactly_at_min_bucket_threshold_is_not_insufficient():
    n = 10 * MIN_BUCKET_SAMPLES
    baseline = [i / n for i in range(n)]
    current = [i / n for i in range(n)]
    result = compute_psi(baseline, current)
    assert result["status"] != "insufficient_data"
