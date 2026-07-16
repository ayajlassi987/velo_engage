from ve_console.model_quality import compute_classification_metrics


def test_insufficient_data_below_min_samples():
    result = compute_classification_metrics([0.9] * 5, [True] * 5)
    assert result["status"] == "insufficient_data"


def test_insufficient_data_single_class():
    # 25 samples but every label is True — no real signal to score against.
    result = compute_classification_metrics([0.9] * 25, [True] * 25)
    assert result["status"] == "insufficient_data"


def test_perfect_predictions_score_1():
    scores = [0.9, 0.8, 0.1, 0.2] * 10  # 40 samples, alternating high/low
    labels = [True, True, False, False] * 10
    result = compute_classification_metrics(scores, labels, threshold=0.5)
    assert result["status"] == "ok"
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0
    assert result["f1"] == 1.0
    assert result["auc"] == 1.0


def test_random_predictions_score_worse_than_perfect():
    scores = [0.5] * 40
    labels = ([True] * 20) + ([False] * 20)
    result = compute_classification_metrics(scores, labels, threshold=0.5)
    assert result["status"] == "ok"
    # All scores tie at the threshold -> predicted all-positive; precision
    # reflects the true positive rate (0.5), recall is perfect (1.0).
    assert result["recall"] == 1.0
    assert result["precision"] == 0.5
