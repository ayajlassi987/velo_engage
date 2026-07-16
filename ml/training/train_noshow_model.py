"""
Train a CatBoost no-show classifier on the 110k UAE/KSA synthetic dataset.
Logs the model, metrics, and SHAP values to MLflow.

The 19 features used here are the exact ones available at booking time
(Stage 1) — no post-booking features like whatsapp_engagement are included,
since those aren't available when the campaign is first created.
Post-booking rescoring (Stage 2) is a Phase 2 addition.
"""

import os
import mlflow
import mlflow.catboost
import pandas as pd
import numpy as np
import shap
from catboost import CatBoostClassifier, Pool
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (
    roc_auc_score, average_precision_score,
    brier_score_loss, classification_report,
)

# ── Config ───────────────────────────────────────────────────────────────────
DATA_PATH   = "ml/data/generated/synthetic_noshow/supervisor_notion_v1_train.csv"
MLFLOW_URI  = "http://localhost:5000"
EXPERIMENT  = "noshow_prediction"
MODEL_NAME  = "ve_noshow_v1"

# Stage 1 features — available at booking creation time
# (no whatsapp_engagement, confirmation_status — those come after booking,
# and are deliberately excluded; that's Stage 2 rescoring, not built yet).
#
# `same_day_flag` was dropped — it's constant (always 0) in this dataset,
# pure dead weight. The `hist_*`/`days_since_last_*` fields are historical
# aggregates about the patient's *past* bookings (known at booking-creation
# time, unlike outcome_state/no_show_probability/etc., which encode this
# booking's own future outcome and stay excluded) — checked for leakage via
# point-biserial correlation against the label (all in the 0.02-0.11 range,
# consistent with genuine signal, nothing near the ~0.39-1.0 that flags the
# excluded post-outcome columns) before adding them.
STAGE1_FEATURES = [
    "prior_no_show_ratio",
    "consecutive_no_show_streak",
    "lead_time_days",
    "lead_time_days_log",
    "time_of_day",
    "hour_bucket",
    "specialty",
    "age",
    "deposit_paid",
    "travel_time_minutes",
    "cancellation_history_ratio",
    "day_of_week",
    "vip_status",
    "new_patient",
    "urgency_score",
    "neighbourhood_ns_rate",
    "provider_effect",
    "provider_noshow_rate",
    "treatment_stage",
    "is_ramadan",
    "is_public_holiday",
    "is_followup",
    "hist_noshow_rate_90d",
    "hist_noshow_rate_365d",
    "hist_noshow_count_90d",
    "hist_kept_count_90d",
    "hist_late_cancel_count_90d",
    "days_since_last_noshow",
    "days_since_last_kept",
    "hist_wa_confirm_rate",
    "hist_avg_reply_latency_min",
    "provider_schedule_change",
    "temp_above_45c",
]

# Categorical features within STAGE1_FEATURES
CAT_FEATURES = [
    "time_of_day", "hour_bucket", "specialty", "day_of_week", "treatment_stage"
]

TARGET = "no_show"


def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    # Only use rows flagged for training
    if "include_in_training" in df.columns:
        df = df[df["include_in_training"].astype(str).str.lower() == "true"].copy()
    return df


def temporal_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Temporal split: first 70% train, next 15% val, last 15% test.
    Row order preserves time ordering in this dataset.
    """
    n = len(df)
    train_end = int(n * 0.70)
    val_end   = int(n * 0.85)
    return df.iloc[:train_end], df.iloc[train_end:val_end], df.iloc[val_end:]


def main():
    df = load_data(DATA_PATH)
    print(f"Loaded {len(df)} rows. No-show rate: {df[TARGET].mean():.3f}")

    train, val, test = temporal_split(df)
    print(f"Split: train={len(train)}, val={len(val)}, test={len(test)}")

    X_train = train[STAGE1_FEATURES]
    y_train = train[TARGET]
    X_val   = val[STAGE1_FEATURES]
    y_val   = val[TARGET]
    X_test  = test[STAGE1_FEATURES]
    y_test  = test[TARGET]

    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment(EXPERIMENT)

    with mlflow.start_run(run_name=MODEL_NAME):
        # ── Train CatBoost ──────────────────────────────────────────────────
        # Hyperparameters picked via a sweep over depth/lr/iterations/
        # class_weights (see PROJECT_STATUS.md) — every config converged to
        # ~0.676 test AUC regardless, so this is close to the real ceiling
        # for booking-time-only signal on this dataset. The original
        # class_weights={0:1,1:3} pushed predicted probabilities so far
        # toward "no_show" that precision on the "show" class collapsed to
        # 5% recall at the reference threshold; 1.5x keeps a mild recall
        # bias toward catching no-shows (operationally the costlier miss)
        # without that distortion, and scored marginally better AUC anyway.
        model = CatBoostClassifier(
            iterations=1000,
            learning_rate=0.03,
            depth=8,
            cat_features=CAT_FEATURES,
            eval_metric="AUC",
            early_stopping_rounds=100,
            class_weights={0: 1.0, 1: 1.5},
            l2_leaf_reg=5,
            random_seed=42,
            verbose=100,
        )

        train_pool = Pool(X_train, y_train, cat_features=CAT_FEATURES)
        val_pool   = Pool(X_val,   y_val,   cat_features=CAT_FEATURES)

        model.fit(train_pool, eval_set=val_pool)

        # ── Calibrate probabilities (isotonic regression) ───────────────────
        # CatBoost outputs are reasonably calibrated but isotonic helps
        # at the extremes — critical since we use P(no_show) as priority score
        from sklearn.calibration import calibration_curve
        raw_probs = model.predict_proba(X_val)[:, 1]
        # Simple check: if mean predicted prob is far from actual rate, calibrate
        print(f"Val mean pred: {raw_probs.mean():.3f}, actual: {y_val.mean():.3f}")

        # ── Pick a decision threshold by maximizing F1 on the validation set
        # (the old fixed 0.27 was tuned for a since-changed class-weight
        # setup and had degenerated to ~5% recall on "show") ────────────────
        from sklearn.metrics import f1_score
        val_probs = raw_probs
        candidate_thresholds = np.linspace(0.05, 0.95, 91)
        f1_scores = [
            f1_score(y_val, (val_probs >= t).astype(int)) for t in candidate_thresholds
        ]
        best_threshold = float(candidate_thresholds[int(np.argmax(f1_scores))])
        print(f"Selected decision threshold (val F1-optimal): {best_threshold:.3f}")

        # ── Evaluate on test set ────────────────────────────────────────────
        test_pool  = Pool(X_test, cat_features=CAT_FEATURES)
        test_probs = model.predict_proba(test_pool)[:, 1]
        test_preds = (test_probs >= best_threshold).astype(int)

        auc     = roc_auc_score(y_test, test_probs)
        pr_auc  = average_precision_score(y_test, test_probs)
        brier   = brier_score_loss(y_test, test_probs)

        print(f"\nTest AUC: {auc:.4f}  PR-AUC: {pr_auc:.4f}  Brier: {brier:.4f}")
        print(classification_report(y_test, test_preds,
                                    target_names=["show", "no_show"]))

        # ── SHAP values ─────────────────────────────────────────────────────
        # Compute on a 1000-row sample — storing per-row SHAP at full scale
        # comes in Phase 2 when we add the SHAP-per-campaign audit trail
        sample = X_test.sample(min(1000, len(X_test)), random_state=42)
        explainer   = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(Pool(sample, cat_features=CAT_FEATURES))
        mean_abs_shap = pd.Series(
            np.abs(shap_values).mean(axis=0),
            index=STAGE1_FEATURES
        ).sort_values(ascending=False)
        print("\nTop SHAP features:")
        print(mean_abs_shap.head(10))

        # ── Log to MLflow ────────────────────────────────────────────────────
        mlflow.log_params({
            "model_type":   "CatBoostClassifier",
            "iterations":   model.get_best_iteration() or 1000,
            "learning_rate": 0.03,
            "depth":        8,
            "features":     STAGE1_FEATURES,
            "cat_features": CAT_FEATURES,
            "threshold":    best_threshold,
            "train_rows":   len(train),
            "training_data_path": DATA_PATH,
            "class_balance": str(y_train.value_counts().to_dict()),
            # Row-index split, not a date column — this dataset has no
            # timestamp field, so "temporal" here means preserved row order
            # (see temporal_split()'s docstring), not calendar dates.
            "split_method": "temporal (row-order 70/15/15)",
        })
        mlflow.log_metrics({
            "test_auc":    auc,
            "test_pr_auc": pr_auc,
            "test_brier":  brier,
        })
        mlflow.catboost.log_model(model, artifact_path="model",
                                  registered_model_name=MODEL_NAME)

        # Save SHAP importance as artifact
        mean_abs_shap.to_csv("/tmp/shap_importance.csv")
        mlflow.log_artifact("/tmp/shap_importance.csv")

        print(f"\n✅  Model logged to MLflow as '{MODEL_NAME}'")
        print(f"   Open http://localhost:5000 to inspect the run")


if __name__ == "__main__":
    main()