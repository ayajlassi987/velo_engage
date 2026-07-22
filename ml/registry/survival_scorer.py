"""Survival / time-to-need model — master spec Phase 2 ("optimal send
timing"). See ml/training/train_survival_model.py for the full framing:
this predicts response latency after contact (dispatch -> booking) rather
than a patient's true underlying recall cadence, which the schema has no
event log to derive. A high predicted days_to_book means this patient
profile historically converts slowly — a candidate for earlier/more
persistent outreach, not necessarily a lower-priority one.
"""

import os
from functools import lru_cache

import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd

from ml.registry._stage_loader import resolve_production_version

MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
MODEL_NAME = "velo_engage_survival"

# Must match the feature engineering in ml/training/train_survival_model.py
# exactly — same feature set as propensity_scorer.py, since whether a
# patient converts and how long it takes them are the same underlying
# engagement signal.
FEATURES = [
    "family", "days_since_last_visit", "visit_cadence_baseline",
    "days_over_baseline", "is_long_dormant", "open_treatment_plan_flag",
    "age", "is_senior", "sex", "priority_score", "priority_x_days",
    "previous_campaigns", "previous_reads", "previous_replies", "previous_bookings",
]


@lru_cache(maxsize=1)
def _load_model():
    mlflow.set_tracking_uri(MLFLOW_URI)
    client = mlflow.MlflowClient()
    resolved = resolve_production_version(client, MODEL_NAME)
    return mlflow.sklearn.load_model(f"models:/{MODEL_NAME}/{resolved.version}")


def _engineer(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["days_over_baseline"] = df["days_since_last_visit"] - df["visit_cadence_baseline"]
    df["is_long_dormant"] = (df["days_since_last_visit"] > 240).astype(int)
    df["is_senior"] = (df["age"] >= 55).astype(int)
    df["priority_x_days"] = df["priority_score"] * df["days_since_last_visit"]
    return df[FEATURES]


def score_opportunities_batch(rows: list[dict]) -> list[float]:
    """Each row needs: family, days_since_last_visit, visit_cadence_baseline,
    open_treatment_plan_flag, age, sex, priority_score, previous_campaigns,
    previous_reads, previous_replies, previous_bookings. Returns predicted
    days-to-book for each row (currency-scale, not log), same order as input."""
    model = _load_model()
    log_days = model.predict(_engineer(rows))
    return np.expm1(log_days).tolist()
