#!/usr/bin/env python3

import os
import warnings
from importlib.metadata import version

warnings.filterwarnings(
    "ignore",
    message="pkg_resources is deprecated as an API.*",
    category=UserWarning,
)
warnings.filterwarnings(
    "ignore",
    message="X does not have valid feature names, but LGBMClassifier was fitted with feature names",
    category=UserWarning,
)

import pandas as pd
import mlflow
import mlflow.sklearn

from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import roc_auc_score, average_precision_score
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from lightgbm import LGBMClassifier


import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ml.feature_pipelines.build_training_dataset import resolve_dataset_lineage_path

DATA_PATH = "ml/feature_pipelines/data/training_dataset.parquet"
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
EXPERIMENT_NAME = "velo-engage-propensity"


def main():
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment(EXPERIMENT_NAME)

    df = pd.read_parquet(DATA_PATH)
    df["days_over_baseline"] = (
    df["days_since_last_visit"] - df["visit_cadence_baseline"]
)

    df["is_long_dormant"] = (
      df["days_since_last_visit"] > 240
    ).astype(int)

    df["is_senior"] = (
      df["age"] >= 55
    ).astype(int)

    df["priority_x_days"] = (
      df["priority_score"] * df["days_since_last_visit"]
)

    # Booking attribution is the Phase 1 business outcome. The environment
    # override allows experiments with another label without editing code.
    target = os.getenv("TRAINING_TARGET", "read_label")

    features = [
    "family",
    "days_since_last_visit",
    "visit_cadence_baseline",
    "days_over_baseline",
    "is_long_dormant",
    "open_treatment_plan_flag",
    "age",
    "is_senior",
    "sex",
    "priority_score",
    "priority_x_days",
    "previous_campaigns",
    "previous_reads",
    "previous_replies",
    "previous_bookings",
]
    df = df.dropna(subset=[target])
    X = df[features]
    y = df[target].astype(int)
    groups = df["patient_id"]

    class_counts = y.value_counts()
    if y.nunique() < 2 or class_counts.min() < 2:
        raise RuntimeError(
            f"Target '{target}' needs at least 2 examples in each class for a "
            f"stratified train/test split; found {class_counts.to_dict()}. "
            "Collect another attributed positive outcome before training."
        )

    numeric_features = [
    "days_since_last_visit",
    "visit_cadence_baseline",
    "age",
    "priority_score",
    "previous_campaigns",
    "previous_reads",
    "previous_replies",
    "previous_bookings",
]

    categorical_features = [
    "family",
    "open_treatment_plan_flag",
    "sex",
]

    preprocessor = ColumnTransformer(
        transformers=[
            ("num", SimpleImputer(strategy="median"), numeric_features),
            ("cat", OneHotEncoder(handle_unknown="ignore"), categorical_features),
        ]
    )

    model = LGBMClassifier(
    n_estimators=400,
    learning_rate=0.03,
    num_leaves=31,
    max_depth=-1,
    min_child_samples=20,
    subsample=0.85,
    colsample_bytree=0.85,
    reg_alpha=0.1,
    reg_lambda=1.0,
    random_state=42,
    class_weight="balanced",
)

    pipeline = Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("model", model),
        ]
    )

    # Grouped by patient_id, not a plain random split: the same patient can
    # have several campaign rows (repeat synthetic reseeds across different
    # calendar days share identical outcomes for the same random seed, and
    # repeated live-pipeline triggers add more rows for the same patient
    # over time). A random row-level split can put near-duplicate rows for
    # one patient on both sides, inflating test AUC through leakage rather
    # than genuine generalization — grouping keeps all of one patient's rows
    # together on one side of the split.
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.30, random_state=42)
    train_idx, test_idx = next(splitter.split(X, y, groups=groups))
    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

    with mlflow.start_run():
        pipeline.fit(X_train, y_train)

        probs = pipeline.predict_proba(X_test)[:, 1]

        auc = roc_auc_score(y_test, probs)
        auc_pr = average_precision_score(y_test, probs)

        mlflow.log_param("target", target)
        mlflow.log_param("model_type", "LightGBM")
        mlflow.log_param("n_rows", len(df))
        mlflow.log_param("features", ",".join(features))
        # Lineage + monitoring context — see model_quality.py/drift.py's
        # baseline-window logic in ve_console, which needs to know what data
        # a version trained on.
        mlflow.log_param("training_data_path", resolve_dataset_lineage_path())
        mlflow.log_param("class_balance", str(class_counts.to_dict()))
        if "campaign_created_at" in df.columns:
            train_dates = df["campaign_created_at"].iloc[train_idx]
            test_dates = df["campaign_created_at"].iloc[test_idx]
            mlflow.log_param("train_date_range", f"{train_dates.min()} to {train_dates.max()}")
            mlflow.log_param("test_date_range", f"{test_dates.min()} to {test_dates.max()}")

        mlflow.log_metric("auc", auc)
        mlflow.log_metric("auc_pr", auc_pr)

        mlflow.sklearn.log_model(
            pipeline,
            artifact_path="model",
            registered_model_name="velo_engage_booking_propensity",
            pip_requirements=[
                f"mlflow=={mlflow.__version__}",
                f"scikit-learn=={version('scikit-learn')}",
                f"lightgbm=={version('lightgbm')}",
                f"pandas=={pd.__version__}",
            ],
        )

        print("✅ Propensity model trained")
        print(f"Rows: {len(df)}")
        print(f"AUC: {auc:.4f}")
        print(f"AUC-PR: {auc_pr:.4f}")
        print("Logged to MLflow:", MLFLOW_TRACKING_URI)


if __name__ == "__main__":
    main()
