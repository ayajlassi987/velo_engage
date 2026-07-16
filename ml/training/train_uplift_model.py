#!/usr/bin/env python3
"""Train the Uplift/causal model — master spec Phase 3.

The propensity model (train_propensity.py) answers "how likely is this
patient to book". This model answers a different question: "how much of
that likelihood is actually CAUSED by contacting them" — the whole reason
the mandatory randomized holdout exists.

T-learner: two separate classifiers, one trained only on treated campaigns
and one trained only on holdout (control) campaigns, both predicting
booked_label from the same features. The difference in their predictions
for a given patient is the estimated individual treatment effect (uplift):

    uplift(patient) = P(book | contacted, features) - P(book | not contacted, features)

A patient with high uplift is a "persuadable" — worth spending a contact on.
A patient with near-zero or negative uplift would likely book anyway (or is
actively put off by contact) — the point of uplift targeting is to spend
outreach capacity on the first group, not the other two.
"""

import os
import warnings
from importlib.metadata import version

warnings.filterwarnings("ignore", message="pkg_resources is deprecated as an API.*", category=UserWarning)

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
EXPERIMENT_NAME = "velo-engage-uplift"

FEATURES = [
    "family", "days_since_last_visit", "visit_cadence_baseline",
    "open_treatment_plan_flag", "age", "sex", "priority_score",
    "previous_campaigns", "previous_reads", "previous_replies", "previous_bookings",
]
NUMERIC_FEATURES = [
    "days_since_last_visit", "visit_cadence_baseline", "age", "priority_score",
    "previous_campaigns", "previous_reads", "previous_replies", "previous_bookings",
]
CATEGORICAL_FEATURES = ["family", "open_treatment_plan_flag", "sex"]


def _pipeline():
    preprocessor = ColumnTransformer(transformers=[
        ("num", SimpleImputer(strategy="median"), NUMERIC_FEATURES),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
    ])
    model = LGBMClassifier(
        n_estimators=300, learning_rate=0.04, num_leaves=25,
        min_child_samples=30, class_weight="balanced", random_state=42,
    )
    return Pipeline(steps=[("preprocessor", preprocessor), ("model", model)])


def _train_arm(df: pd.DataFrame, run_name: str, registered_name: str, pip_requirements: list[str]):
    X = df[FEATURES]
    y = df["booked_label"].astype(int)
    # Grouped by patient_id — see the matching comment in train_propensity.py.
    # Repeat synthetic reseeds and repeated live-pipeline triggers give the
    # same patient several near-identical rows; a random split can leak
    # those across train/test and inflate test AUC.
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=42)
    train_idx, test_idx = next(splitter.split(X, y, groups=df["patient_id"]))
    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
    pipeline = _pipeline()
    with mlflow.start_run(run_name=run_name):
        pipeline.fit(X_train, y_train)
        probs = pipeline.predict_proba(X_test)[:, 1]
        auc = roc_auc_score(y_test, probs)
        auc_pr = average_precision_score(y_test, probs)
        mlflow.log_params({"model_type": "LightGBM", "arm": run_name, "n_rows": len(df)})
        mlflow.log_param("training_data_path", resolve_dataset_lineage_path())
        mlflow.log_param("class_balance", str(y.value_counts().to_dict()))
        if "campaign_created_at" in df.columns:
            train_dates = df["campaign_created_at"].iloc[train_idx]
            test_dates = df["campaign_created_at"].iloc[test_idx]
            mlflow.log_param("train_date_range", f"{train_dates.min()} to {train_dates.max()}")
            mlflow.log_param("test_date_range", f"{test_dates.min()} to {test_dates.max()}")
        mlflow.log_metrics({"auc": auc, "auc_pr": auc_pr, "book_rate": float(y.mean())})
        mlflow.sklearn.log_model(
            pipeline, artifact_path="model",
            registered_model_name=registered_name,
            pip_requirements=pip_requirements,
        )
        print(f"✅ Uplift {run_name} model trained — rows={len(df)}, book_rate={y.mean():.4f}, "
              f"AUC={auc:.4f}, AUC-PR={auc_pr:.4f}")


def main():
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment(EXPERIMENT_NAME)

    df = pd.read_parquet(DATA_PATH).dropna(subset=FEATURES + ["booked_label", "is_treated"])

    treated = df[df["is_treated"] == 1]
    control = df[df["is_treated"] == 0]

    for arm_df, label in ((treated, "treated"), (control, "control")):
        if arm_df["booked_label"].nunique() < 2 or arm_df["booked_label"].value_counts().min() < 2:
            raise RuntimeError(
                f"'{label}' arm needs at least 2 examples of each booked_label class; "
                f"found {arm_df['booked_label'].value_counts().to_dict()}."
            )

    pip_requirements = [
        f"mlflow=={mlflow.__version__}",
        f"scikit-learn=={version('scikit-learn')}",
        f"lightgbm=={version('lightgbm')}",
        f"pandas=={pd.__version__}",
    ]

    _train_arm(treated, "treated", "velo_engage_uplift_treated", pip_requirements)
    _train_arm(control, "control", "velo_engage_uplift_control", pip_requirements)

    print("Logged to MLflow:", MLFLOW_TRACKING_URI)


if __name__ == "__main__":
    main()
