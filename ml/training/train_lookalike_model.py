#!/usr/bin/env python3
"""Train the Lookalike / cross-sell model — master spec Phase 2-3, feeding
family D's "cross-specialty" detection (see policies/opportunities/D.yml,
tagged methods: [R, D, AI] — only the [R] rule exists today; this is the
[AI] piece).

Unlike every other model in ml/training/ (propensity, value, uplift,
survival), this one doesn't score opportunities the rule engine already
found — it recommends NEW ones: for each patient, which opportunity family
they've never engaged with are they nonetheless likely to respond well to,
based on which families tend to co-occur across the patient base.

A genuine matrix-factorization / embedding approach (NMF) was tried first
and produced a held-out AUC of ~0.29 — *worse* than random, not just weak.
Investigated why before concluding anything was broken: 74% of patients
with any booked family history (2,334 of 3,163) have booked for exactly
ONE family, ever; only 829 have 2+, and almost all of those have exactly 2.
Matrix factorization needs patients with multiple item interactions to
discover which patients are "similar" — with three-quarters of the base
having a single data point, there's no cross-family correlation signal for
any factorization method to find yet. This is a data-density limitation,
not a code bug (confirmed via a leave-one-out eval that never lets NMF see
its own held-out answer as a zero — the result didn't change).

Given that, this deliberately is NOT a trained embedding model. It's a
documented heuristic — same precedent as train_value_model.py's
revenue_base_rate: rather than ship a model that's measurably worse than
random, this computes real family-to-family co-occurrence probabilities
directly (P(patient also has family Y | patient has family X)) and
recommends based on that. Revisit with real matrix factorization once
enough patients accumulate multi-family history for it to be learnable.
"""

import os
import warnings

warnings.filterwarnings("ignore", message="pkg_resources is deprecated as an API.*", category=UserWarning)

import numpy as np
import pandas as pd
import mlflow
import mlflow.sklearn

from sklearn.metrics import roc_auc_score

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ml.feature_pipelines.build_training_dataset import resolve_dataset_lineage_path

DATA_PATH = "ml/feature_pipelines/data/training_dataset.parquet"
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
EXPERIMENT_NAME = "velo-engage-lookalike"

AFFINITY_PERCENTILE = 90   # "conservative, top-tier only" threshold, per user decision
MIN_SUPPORT = 5            # minimum patients with family X needed before P(Y|X) is trusted


class CooccurrenceLookalikeModel:
    """P(patient also has family Y | patient has family X), for every
    ordered pair. Not a fitted estimator with a predict() method — a
    documented lookup table, per this module's docstring. Logged via
    mlflow.sklearn.log_model() anyway (works fine for any picklable object,
    just skips the optional pyfunc flavor) so it's versioned/promotable
    through the exact same registry every other model here uses."""

    def __init__(self, families: list[str], cooccurrence: np.ndarray, support: np.ndarray):
        self.families = families
        self.cooccurrence = cooccurrence  # [i, j] = P(has j | has i)
        self.support = support            # [i] = number of patients with family i (for MIN_SUPPORT gating)

    def recommend_scores(self, known_families: list[str]) -> dict[str, float]:
        """For families NOT in known_families, the best co-occurrence
        evidence from any of the patient's known families."""
        idx = {f: i for i, f in enumerate(self.families)}
        known_idx = [idx[f] for f in known_families if f in idx]
        scores = {}
        for f in self.families:
            if f in known_families:
                continue
            j = idx[f]
            candidates = [self.cooccurrence[i, j] for i in known_idx if self.support[i] >= MIN_SUPPORT]
            scores[f] = max(candidates) if candidates else 0.0
        return scores


def _build_interaction_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Patient x family matrix, 1 if the patient was ever booked for that
    family, else 0. Uses every booked row regardless of synthetic/real
    origin — same precedent as every other training script here (the
    SYN%/P0% distinction is applied downstream in ve_console/feature_store,
    not in offline training)."""
    booked = df[df["booked_label"] == 1][["patient_id", "family"]].drop_duplicates()
    matrix = pd.crosstab(booked["patient_id"], booked["family"])
    return (matrix > 0).astype(float)


def _fit_cooccurrence(matrix: pd.DataFrame) -> CooccurrenceLookalikeModel:
    families = matrix.columns.tolist()
    values = matrix.values
    support = values.sum(axis=0)
    both = values.T @ values  # [i, j] = count of patients with both family i and family j
    with np.errstate(divide="ignore", invalid="ignore"):
        cooccurrence = np.where(support[:, None] > 0, both / support[:, None], 0.0)
    return CooccurrenceLookalikeModel(families, cooccurrence, support)


def _evaluate(matrix: pd.DataFrame, rng: np.random.RandomState) -> float:
    """Leave-one-out by patient, same discipline as every other model's
    held-out split — co-occurrence is computed only from training patients,
    never from an eval patient's own held-out family, so there's no
    equivalent of the NMF bug this module's docstring describes."""
    patient_ids = matrix.index.tolist()
    rng.shuffle(patient_ids)
    split = int(len(patient_ids) * 0.7)
    train_patients, eval_patients = patient_ids[:split], patient_ids[split:]

    model = _fit_cooccurrence(matrix.loc[train_patients])

    eval_matrix = matrix.loc[eval_patients]
    eligible = eval_matrix[eval_matrix.sum(axis=1) >= 2]

    scores, labels = [], []
    for patient_id in eligible.index:
        row = eligible.loc[patient_id]
        known = row[row > 0].index.tolist()
        hidden_family = rng.choice(known)
        remaining_known = [f for f in known if f != hidden_family]

        never_interacted = row[row == 0].index.tolist()
        if not never_interacted:
            continue
        negative_family = rng.choice(never_interacted)

        recs = model.recommend_scores(remaining_known)
        scores += [recs.get(hidden_family, 0.0), recs.get(negative_family, 0.0)]
        labels += [1, 0]

    return roc_auc_score(labels, scores)


def main():
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment(EXPERIMENT_NAME)

    df = pd.read_parquet(DATA_PATH)
    matrix = _build_interaction_matrix(df)

    n_patients, n_families = matrix.shape
    n_positive = int(matrix.values.sum())
    if n_positive < 200:
        raise RuntimeError(
            f"Only {n_positive} positive (patient, family) interactions available — "
            "need more booking history before even a co-occurrence heuristic is trustworthy."
        )

    rng = np.random.RandomState(42)
    held_out_auc = _evaluate(matrix, rng)

    final_model = _fit_cooccurrence(matrix)

    # Threshold for "confident enough to actually contact the patient" —
    # computed over every real (patient, untried-family) candidate pair,
    # per the user's "conservative, top-tier only" decision.
    all_candidate_scores = []
    for patient_id in matrix.index:
        row = matrix.loc[patient_id]
        known = row[row > 0].index.tolist()
        if not known:
            continue
        all_candidate_scores.extend(final_model.recommend_scores(known).values())
    affinity_threshold = float(np.percentile(all_candidate_scores, AFFINITY_PERCENTILE)) if all_candidate_scores else 1.0

    pip_requirements = [f"mlflow=={mlflow.__version__}", f"pandas=={pd.__version__}"]

    with mlflow.start_run(run_name="lookalike_cooccurrence"):
        mlflow.log_param("model_type", "cooccurrence_heuristic")
        mlflow.log_param("n_patients", n_patients)
        mlflow.log_param("n_families", n_families)
        mlflow.log_param("n_positive_interactions", n_positive)
        mlflow.log_param("min_support", MIN_SUPPORT)
        mlflow.log_param("affinity_threshold", affinity_threshold)
        mlflow.log_param("affinity_percentile", AFFINITY_PERCENTILE)
        mlflow.log_param("training_data_path", resolve_dataset_lineage_path())

        mlflow.log_metric("held_out_auc", held_out_auc)

        mlflow.sklearn.log_model(
            final_model, artifact_path="model",
            registered_model_name="velo_engage_lookalike",
            pip_requirements=pip_requirements,
        )

    print("✅ Lookalike (co-occurrence) model trained")
    print(f"Patients: {n_patients}, families: {n_families}, positive interactions: {n_positive}")
    print(f"Held-out AUC: {held_out_auc:.4f}")
    print(f"Affinity threshold (p{AFFINITY_PERCENTILE}): {affinity_threshold:.4f}")


if __name__ == "__main__":
    main()
