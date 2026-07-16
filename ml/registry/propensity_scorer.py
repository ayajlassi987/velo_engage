"""Reactivation/response propensity model — master spec Phase 1.

Loads velo_engage_booking_propensity from MLflow and scores opportunities:
P(patient books an appointment after being contacted about this
opportunity). This is distinct from ml/registry/scorer.py's no-show model,
which predicts whether an *already-booked* appointment will be missed, not
whether an outreach contact will result in a new booking — the two answer
different questions and should not be used interchangeably.
"""

import os
from functools import lru_cache

import mlflow
import mlflow.sklearn
import pandas as pd

from ml.registry._stage_loader import resolve_production_version

MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
MODEL_NAME = "velo_engage_booking_propensity"

# Must match the feature engineering in ml/training/train_propensity.py exactly.
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
    previous_reads, previous_replies, previous_bookings. Returns P(books
    after contact) for each row, same order as input."""
    model = _load_model()
    return model.predict_proba(_engineer(rows))[:, 1].tolist()
