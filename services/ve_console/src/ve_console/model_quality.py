"""Post-hoc classification quality (precision/recall/F1/AUC) computed
against real logged outcomes — distinct from the training-time metrics in
MLflow (ml/training/*.py), this measures what a model's scores actually
correlated with once campaigns played out, using the same cohort split
(synthetic vs real, by patient_id prefix) as the rest of ve_console.

Only meaningful for noshow/propensity — both predict a binary event with a
direct ground-truth column. value_score is a regression target (dollar
amount, not a class) and uplift_score is a causal-effect estimate, not a
direct outcome prediction — neither maps onto precision/recall/F1/AUC
without misrepresenting what the score means, so this module doesn't
force-fit them; callers should skip those two entirely rather than call in
with a fabricated threshold.
"""

from sklearn.metrics import precision_recall_fscore_support, roc_auc_score

MIN_SAMPLES = 20


def compute_classification_metrics(
    scores: list[float], labels: list[bool], threshold: float = 0.5
) -> dict:
    """scores: model output per campaign. labels: the real logged outcome
    (True = the event the score predicts actually happened). Mirrors
    drift.py's insufficient_data empty-state pattern rather than computing
    a statistically meaningless metric on too few or single-class samples."""
    if len(scores) < MIN_SAMPLES or len(set(labels)) < 2:
        return {"status": "insufficient_data", "n": len(scores)}

    predictions = [s >= threshold for s in scores]
    precision, recall, f1, _ = precision_recall_fscore_support(
        labels, predictions, average="binary", zero_division=0
    )
    try:
        auc = roc_auc_score(labels, scores)
    except ValueError:
        auc = None

    return {
        "status": "ok",
        "n": len(scores),
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
        "f1": round(float(f1), 4),
        "auc": round(float(auc), 4) if auc is not None else None,
        "threshold": threshold,
    }
