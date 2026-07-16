#!/usr/bin/env python3
"""Train the Value model — E[revenue | reactivate], master spec Phase 1.

E[revenue] = P(revenue > 0 | booked) * E[amount | revenue > 0]

Investigated both halves before training either:
  - Whether a booked patient generates any revenue at all is driven by
    attendance, which in the current dataset is generated independently of
    every patient feature (a fixed-probability coin flip). No classifier
    can beat that base rate, so rather than deploy a model that can't
    outperform a constant, this script computes the empirical base rate and
    logs it as an MLflow param for the scorer to read — a documented
    heuristic, not a disguised no-op model. Revisit once real (non-synthetic)
    attendance data exists where this actually depends on patient behavior.
  - The amount, given revenue occurs, IS cleanly determined by
    family + high_value_patient + insurance_tier — a real regression target.
"""

import os
import warnings
from importlib.metadata import version

warnings.filterwarnings("ignore", message="pkg_resources is deprecated as an API.*", category=UserWarning)

import numpy as np
import pandas as pd
import mlflow
import mlflow.sklearn

from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.pipeline import Pipeline
from lightgbm import LGBMRegressor

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ml.feature_pipelines.build_training_dataset import resolve_dataset_lineage_path

DATA_PATH = "ml/feature_pipelines/data/training_dataset.parquet"
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
EXPERIMENT_NAME = "velo-engage-value"

FEATURES = ["family", "high_value_patient", "insurance_tier"]


def main():
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment(EXPERIMENT_NAME)

    df = pd.read_parquet(DATA_PATH)
    booked = df[df["booked_label"] == 1].dropna(subset=FEATURES + ["has_revenue_label", "revenue_amount"])

    if len(booked) < 50:
        raise RuntimeError(
            f"Only {len(booked)} booked campaigns available — need more attributed "
            "bookings before a value model is trainable."
        )

    base_rate = float(booked["has_revenue_label"].mean())

    pip_requirements = [
        f"mlflow=={mlflow.__version__}",
        f"scikit-learn=={version('scikit-learn')}",
        f"lightgbm=={version('lightgbm')}",
        f"pandas=={pd.__version__}",
    ]

    positive = booked[booked["has_revenue_label"] == 1]
    X = positive[FEATURES]
    y = np.log1p(positive["revenue_amount"].astype(float))

    # Grouped by patient_id — see the matching comment in
    # train_propensity.py. Same rationale applies here.
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=42)
    train_idx, test_idx = next(splitter.split(X, y, groups=positive["patient_id"]))
    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

    preprocessor = ColumnTransformer(transformers=[
        ("cat", OneHotEncoder(handle_unknown="ignore"), FEATURES),
    ])
    pipeline = Pipeline(steps=[
        ("preprocessor", preprocessor),
        ("model", LGBMRegressor(n_estimators=200, learning_rate=0.05, num_leaves=15, random_state=42)),
    ])

    with mlflow.start_run(run_name="value_amount"):
        pipeline.fit(X_train, y_train)
        preds = pipeline.predict(X_test)
        actual = np.expm1(y_test)
        predicted = np.expm1(preds)
        mae_currency = mean_absolute_error(actual, predicted)
        rmse_currency = root_mean_squared_error(actual, predicted)

        mlflow.log_params({
            "model_type": "LightGBM", "stage": "amount",
            "n_rows": len(positive), "features": ",".join(FEATURES),
        })
        # The gate's base rate travels as a param on the amount model's run
        # so ml/registry/value_scorer.py can read both from one place.
        mlflow.log_param("revenue_base_rate", round(base_rate, 4))
        mlflow.log_param("revenue_base_rate_n", len(booked))
        mlflow.log_param("training_data_path", resolve_dataset_lineage_path())
        if "campaign_created_at" in positive.columns:
            train_dates = positive["campaign_created_at"].iloc[train_idx]
            test_dates = positive["campaign_created_at"].iloc[test_idx]
            mlflow.log_param("train_date_range", f"{train_dates.min()} to {train_dates.max()}")
            mlflow.log_param("test_date_range", f"{test_dates.min()} to {test_dates.max()}")
        mlflow.log_metric("mae_currency", mae_currency)
        mlflow.log_metric("rmse_currency", rmse_currency)

        mlflow.sklearn.log_model(
            pipeline, artifact_path="model",
            registered_model_name="velo_engage_value_amount",
            pip_requirements=pip_requirements,
        )
        print(f"✅ Value amount model trained — MAE {mae_currency:.2f} currency units")
        print(f"   Revenue base rate (heuristic, not modeled): {base_rate:.4f} over {len(booked)} booked campaigns")

    print("Logged to MLflow:", MLFLOW_TRACKING_URI)


if __name__ == "__main__":
    main()
