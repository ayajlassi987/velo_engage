#!/usr/bin/env python3
"""Train the Survival / time-to-need model — predicted days from a
campaign being dispatched to the patient actually booking, master spec
Phase 2 ("optimal send timing").

Framed honestly as what the data actually supports, not the idealized
spec description: this predicts *response latency after contact*
(dispatch -> booking), not a patient's true underlying recall cadence
independent of any outreach — the schema has no per-patient visit-history
event log to derive the latter from. Still directly useful for the stated
goal: patient profiles predicted to convert slowly are candidates for
earlier/more-persistent outreach, and vice versa.

Prerequisite fixed before this was trainable at all: `outcomes` previously
had a single `recorded_at` timestamp shared by every stage (delivered/
read/replied/booked/attended) — every update clobbered the previous
stage's real timing, so no duration between dispatch and booking could
ever be recovered, for either real or synthetic data. Fixed in
infra/migrations/015_outcome_stage_timestamps.sql plus the three write
paths that populate it (ve_reach/db.py, ve_measure/booking_listener.py,
scripts/seed_synthetic_phase1.py's realistic per-stage delay simulation).

No survival-analysis library (lifelines/scikit-survival) is used —
deliberately, per team decision: this codebase's existing models handle
"not enough tooling/signal yet" with pragmatic, honestly-documented
approximations (this file's sibling train_value_model.py is the direct
precedent) rather than adding new dependencies. This means right-censored
patients (haven't booked yet as of training time) are simply excluded,
same as any other row missing its label — a known simplification, not a
proper survival model with censoring, and should be revisited if/when a
real product need justifies the added complexity.
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
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import OneHotEncoder
from sklearn.pipeline import Pipeline
from lightgbm import LGBMRegressor

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ml.feature_pipelines.build_training_dataset import resolve_dataset_lineage_path

DATA_PATH = "ml/feature_pipelines/data/training_dataset.parquet"
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
EXPERIMENT_NAME = "velo-engage-survival"

# Same feature set as train_propensity.py — whether a patient converts and
# how long it takes them to convert are the same underlying engagement
# signal, so there's no reason for a different feature list here.
FEATURES = [
    "family", "days_since_last_visit", "visit_cadence_baseline", "days_over_baseline",
    "is_long_dormant", "open_treatment_plan_flag", "age", "is_senior", "sex",
    "priority_score", "priority_x_days",
    "previous_campaigns", "previous_reads", "previous_replies", "previous_bookings",
]
NUMERIC_FEATURES = [
    "days_since_last_visit", "visit_cadence_baseline", "days_over_baseline", "age",
    "priority_score", "priority_x_days",
    "previous_campaigns", "previous_reads", "previous_replies", "previous_bookings",
]
CATEGORICAL_FEATURES = ["family", "is_long_dormant", "open_treatment_plan_flag", "is_senior", "sex"]


def _engineer(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["days_over_baseline"] = df["days_since_last_visit"] - df["visit_cadence_baseline"]
    df["is_long_dormant"] = (df["days_since_last_visit"] > 240).astype(int)
    df["is_senior"] = (df["age"] >= 55).astype(int)
    df["priority_x_days"] = df["priority_score"] * df["days_since_last_visit"]
    return df


def main():
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment(EXPERIMENT_NAME)

    df = pd.read_parquet(DATA_PATH)
    df = _engineer(df)

    # Only rows that actually booked AND have a real booked_at timestamp —
    # the historical synthetic rows seeded before infra/migrations/015 have
    # booked_label==1 but no booked_at at all (right-censored in the sense
    # that we simply never captured when they booked), and patients who
    # haven't booked yet have no event at all. Both are excluded rather
    # than given a fabricated duration.
    booked = df[(df["booked_label"] == 1) & df["booked_at"].notna()].dropna(
        subset=FEATURES + ["campaign_created_at"]
    )

    if len(booked) < 50:
        raise RuntimeError(
            f"Only {len(booked)} campaigns with a real booked_at timestamp — "
            "need more before a survival/timing model is trainable."
        )

    duration_days = (booked["booked_at"] - booked["campaign_created_at"]).dt.total_seconds() / 86400
    # A handful of rows can land at ~0 (e.g. holdout bookings attributed to
    # a campaign created the same instant) — floor at a small positive
    # value so log1p stays well-defined and no row is silently dropped.
    duration_days = duration_days.clip(lower=1 / 24)

    X = booked[FEATURES]
    y = np.log1p(duration_days)

    pip_requirements = [
        f"mlflow=={mlflow.__version__}",
        f"scikit-learn=={version('scikit-learn')}",
        f"lightgbm=={version('lightgbm')}",
        f"pandas=={pd.__version__}",
    ]

    # Grouped by patient_id — same rationale as train_propensity.py: a
    # patient with multiple campaigns must not appear in both train and
    # test, which would leak their personal response-speed baseline across
    # the split.
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=42)
    train_idx, test_idx = next(splitter.split(X, y, groups=booked["patient_id"]))
    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

    preprocessor = ColumnTransformer(transformers=[
        ("num", SimpleImputer(strategy="median"), NUMERIC_FEATURES),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
    ])
    pipeline = Pipeline(steps=[
        ("preprocessor", preprocessor),
        ("model", LGBMRegressor(n_estimators=200, learning_rate=0.05, num_leaves=15, random_state=42)),
    ])

    with mlflow.start_run(run_name="survival_days_to_book"):
        pipeline.fit(X_train, y_train)
        preds = pipeline.predict(X_test)
        actual_days = np.expm1(y_test)
        predicted_days = np.expm1(preds)
        mae_days = mean_absolute_error(actual_days, predicted_days)
        rmse_days = root_mean_squared_error(actual_days, predicted_days)

        mlflow.log_params({
            "model_type": "LightGBM", "target": "days_to_book",
            "n_rows": len(booked), "features": ",".join(FEATURES),
        })
        mlflow.log_param("training_data_path", resolve_dataset_lineage_path())
        train_dates = booked["campaign_created_at"].iloc[train_idx]
        test_dates = booked["campaign_created_at"].iloc[test_idx]
        mlflow.log_param("train_date_range", f"{train_dates.min()} to {train_dates.max()}")
        mlflow.log_param("test_date_range", f"{test_dates.min()} to {test_dates.max()}")
        mlflow.log_metric("mae_days", mae_days)
        mlflow.log_metric("rmse_days", rmse_days)

        mlflow.sklearn.log_model(
            pipeline, artifact_path="model",
            registered_model_name="velo_engage_survival",
            pip_requirements=pip_requirements,
        )
        print(f"✅ Survival/timing model trained — MAE {mae_days:.2f} days, RMSE {rmse_days:.2f} days")
        print(f"   Trained on {len(booked)} campaigns with a real booked_at timestamp")

    print("Logged to MLflow:", MLFLOW_TRACKING_URI)


if __name__ == "__main__":
    main()
