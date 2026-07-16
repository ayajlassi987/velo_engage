"""Value model — E[revenue | reactivate], master spec Phase 1.

E[revenue] = revenue_base_rate * E[amount | revenue > 0]

The base rate (P(a booked patient generates any revenue at all)) is not a
trained model — see ml/training/train_value_model.py for why: attendance in
the current dataset is generated independently of every patient feature, so
no classifier can beat the empirical constant. It's read from the amount
model's MLflow run params rather than hardcoded, so retraining updates it.

The amount model itself (E[amount | revenue > 0]) is a real, trained
regressor over family + high_value_patient + insurance_tier — the three
features that actually determine invoice amount in this dataset.
"""

import os
from functools import lru_cache

import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd

from ml.registry._stage_loader import resolve_production_version

MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
MODEL_NAME = "velo_engage_value_amount"

FEATURES = ["family", "high_value_patient", "insurance_tier"]
DEFAULTS = {"high_value_patient": False, "insurance_tier": "standard"}


@lru_cache(maxsize=1)
def _load():
    mlflow.set_tracking_uri(MLFLOW_URI)
    client = mlflow.MlflowClient()
    resolved = resolve_production_version(client, MODEL_NAME)
    model = mlflow.sklearn.load_model(f"models:/{MODEL_NAME}/{resolved.version}")
    run = client.get_run(resolved.run_id)
    base_rate = float(run.data.params.get("revenue_base_rate", 0.5))
    return model, base_rate


def score_opportunities_batch(rows: list[dict]) -> list[float]:
    """Each row needs: family, and optionally high_value_patient /
    insurance_tier (defaulted when unavailable — most families don't
    surface these in their rule evidence today). Returns E[revenue] per
    row, same order as input."""
    model, base_rate = _load()
    frame = pd.DataFrame([
        {k: row.get(k, DEFAULTS.get(k)) for k in FEATURES}
        for row in rows
    ])
    log_amount = model.predict(frame)
    return (base_rate * np.expm1(log_amount)).tolist()
