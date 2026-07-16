"""
Loads the latest production no-show model from MLflow and scores patients.
Called by run_decide.py (and eventually the Temporal workflow) before
assigning priority scores and holdout arms.
"""

import os
import mlflow
import mlflow.catboost
import pandas as pd
from functools import lru_cache

from ml.registry._stage_loader import resolve_production_version

MLFLOW_URI  = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
MODEL_NAME  = "ve_noshow_v1"

# Must match ml/training/train_noshow_model.py's STAGE1_FEATURES/CAT_FEATURES
# exactly — a mismatch doesn't fail loudly, it silently confuses CatBoost's
# dtype inference (a categorical column can get treated as numeric and throw
# a "Cannot convert '<value>' to float" error deep in its C++ layer).
CAT_FEATURES = ["time_of_day", "hour_bucket", "specialty", "day_of_week", "treatment_stage"]

STAGE1_FEATURES = [
    "prior_no_show_ratio", "consecutive_no_show_streak", "lead_time_days",
    "lead_time_days_log", "time_of_day", "hour_bucket", "specialty", "age",
    "deposit_paid", "travel_time_minutes", "cancellation_history_ratio",
    "day_of_week", "vip_status", "new_patient", "urgency_score",
    "neighbourhood_ns_rate", "provider_effect", "provider_noshow_rate",
    "treatment_stage", "is_ramadan", "is_public_holiday", "is_followup",
    "hist_noshow_rate_90d", "hist_noshow_rate_365d", "hist_noshow_count_90d",
    "hist_kept_count_90d", "hist_late_cancel_count_90d",
    "days_since_last_noshow", "days_since_last_kept", "hist_wa_confirm_rate",
    "hist_avg_reply_latency_min", "provider_schedule_change", "temp_above_45c",
]

# Missing features default to these safe neutral values so a model score is
# always returned even with partial data. days_since_last_noshow/kept default
# to a large value (never happened recently) rather than 0 (happened today).
DEFAULTS = {
    "prior_no_show_ratio": 0.15,
    "consecutive_no_show_streak": 0,
    "lead_time_days": 7,
    "lead_time_days_log": 2.08,
    "time_of_day": "morning",
    "hour_bucket": "morning",
    "specialty": "dental",
    "age": 35,
    "deposit_paid": 0,
    "travel_time_minutes": 20.0,
    "cancellation_history_ratio": 0.10,
    "day_of_week": "Monday",
    "vip_status": 0,
    "new_patient": 0,
    "urgency_score": 5,
    "neighbourhood_ns_rate": 0.09,
    "provider_effect": 0.0,
    "provider_noshow_rate": 0.10,
    "treatment_stage": "consultation",
    "is_ramadan": 0,
    "is_public_holiday": 0,
    "is_followup": 0,
    "hist_noshow_rate_90d": 0.15,
    "hist_noshow_rate_365d": 0.15,
    "hist_noshow_count_90d": 0,
    "hist_kept_count_90d": 0,
    "hist_late_cancel_count_90d": 0,
    "days_since_last_noshow": 365,
    "days_since_last_kept": 365,
    "hist_wa_confirm_rate": 0.5,
    "hist_avg_reply_latency_min": 60.0,
    "provider_schedule_change": 0,
    "temp_above_45c": 0,
}


@lru_cache(maxsize=1)
def _load_model():
    mlflow.set_tracking_uri(MLFLOW_URI)
    client = mlflow.MlflowClient()
    resolved = resolve_production_version(client, MODEL_NAME)
    return mlflow.catboost.load_model(f"models:/{MODEL_NAME}/{resolved.version}")


def _feature_row(features: dict) -> dict:
    return {k: features.get(k, DEFAULTS[k]) for k in STAGE1_FEATURES}


def score_patient(features: dict) -> float:
    """Takes a dict of patient features (from patient_features table) and
    returns P(no_show) as a float between 0 and 1."""
    df = pd.DataFrame([_feature_row(features)])
    model = _load_model()
    prob = model.predict_proba(df)[0][1]
    return float(prob)


def score_patients_batch(features_list: list[dict]) -> list[float]:
    """Batch version — more efficient than calling score_patient() in a loop."""
    df = pd.DataFrame([_feature_row(f) for f in features_list])
    model = _load_model()
    return model.predict_proba(df)[:, 1].tolist()


def explain_patient(features: dict) -> dict:
    """Per-feature SHAP contributions for a single patient's no-show score —
    "why this patient" for the console, not just the score itself.

    Uses CatBoost's native SHAP support (no separate `shap` dependency).
    """
    from catboost import Pool

    row = _feature_row(features)
    df = pd.DataFrame([row])
    model = _load_model()
    pool = Pool(df, cat_features=CAT_FEATURES)

    shap_row = model.get_feature_importance(pool, type="ShapValues")[0]
    base_value = float(shap_row[-1])
    contributions = [
        {"feature": feature, "patient_value": row[feature], "shap_value": float(value)}
        for feature, value in zip(STAGE1_FEATURES, shap_row[:-1])
    ]
    contributions.sort(key=lambda c: abs(c["shap_value"]), reverse=True)

    return {
        "base_value": base_value,
        "predicted_score": base_value + sum(c["shap_value"] for c in contributions),
        "contributions": contributions,
    }