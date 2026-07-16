"""Uplift/causal model — master spec Phase 3.

T-learner: uplift(patient) = P(book | treated, features) - P(book | control, features)

Loads the two arm-specific classifiers trained in
ml/training/train_uplift_model.py and returns the estimated individual
treatment effect — how much of a patient's booking likelihood is actually
caused by contacting them, as opposed to being about to book regardless
(or being unaffected either way). Used to target "persuadable" patients
rather than spending outreach capacity on sure things or lost causes.
"""

import os
from functools import lru_cache

import mlflow
import mlflow.sklearn
import pandas as pd

from ml.registry._stage_loader import resolve_production_version

MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
TREATED_MODEL_NAME = "velo_engage_uplift_treated"
CONTROL_MODEL_NAME = "velo_engage_uplift_control"

FEATURES = [
    "family", "days_since_last_visit", "visit_cadence_baseline",
    "open_treatment_plan_flag", "age", "sex", "priority_score",
    "previous_campaigns", "previous_reads", "previous_replies", "previous_bookings",
]


@lru_cache(maxsize=1)
def _load(model_name: str):
    mlflow.set_tracking_uri(MLFLOW_URI)
    client = mlflow.MlflowClient()
    resolved = resolve_production_version(client, model_name)
    return mlflow.sklearn.load_model(f"models:/{model_name}/{resolved.version}")


def score_opportunities_batch(rows: list[dict]) -> list[float]:
    """Each row needs: family, days_since_last_visit, visit_cadence_baseline,
    open_treatment_plan_flag, age, sex, priority_score, previous_campaigns,
    previous_reads, previous_replies, previous_bookings. Returns the
    estimated uplift (can be negative) per row, same order as input."""
    frame = pd.DataFrame(rows)[FEATURES]
    treated_model = _load(TREATED_MODEL_NAME)
    control_model = _load(CONTROL_MODEL_NAME)
    p_treated = treated_model.predict_proba(frame)[:, 1]
    p_control = control_model.predict_proba(frame)[:, 1]
    return (p_treated - p_control).tolist()
