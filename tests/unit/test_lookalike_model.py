"""Pure-logic tests for the co-occurrence lookalike model — no MLflow/DB
needed, matches this codebase's precedent of unit-testing the parts that
don't require live infra (see test_drift.py, test_model_quality.py) and
leaving "does it load correctly from real MLflow" to manual/live
verification (already done for this model — see PROJECT_STATUS.md)."""

import numpy as np
import pandas as pd

from ml.training.train_lookalike_model import CooccurrenceLookalikeModel, _fit_cooccurrence


def test_recommend_scores_excludes_known_families():
    model = CooccurrenceLookalikeModel(
        families=["A", "B", "C"],
        cooccurrence=np.array([[1.0, 0.5, 0.1], [0.5, 1.0, 0.2], [0.1, 0.2, 1.0]]),
        support=np.array([100, 100, 100]),
    )
    scores = model.recommend_scores(["A"])
    assert "A" not in scores
    assert set(scores.keys()) == {"B", "C"}


def test_recommend_scores_takes_best_evidence_across_known_families():
    model = CooccurrenceLookalikeModel(
        families=["A", "B", "C"],
        cooccurrence=np.array([[1.0, 0.1, 0.05], [0.1, 1.0, 0.9], [0.05, 0.9, 1.0]]),
        support=np.array([100, 100, 100]),
    )
    # Patient known for A and B; C's best evidence should come from B (0.9), not A (0.05).
    scores = model.recommend_scores(["A", "B"])
    assert scores["C"] == 0.9


def test_recommend_scores_ignores_low_support_families():
    model = CooccurrenceLookalikeModel(
        families=["A", "B"],
        cooccurrence=np.array([[1.0, 0.9], [0.9, 1.0]]),
        support=np.array([100, 2]),  # B has too little support to trust
    )
    # Known family B has high co-occurrence with A, but B's own support is
    # below MIN_SUPPORT — A should get no score from this evidence.
    scores = model.recommend_scores(["B"])
    assert scores["A"] == 0.0


def test_recommend_scores_empty_when_no_known_families():
    model = CooccurrenceLookalikeModel(
        families=["A", "B"],
        cooccurrence=np.array([[1.0, 0.5], [0.5, 1.0]]),
        support=np.array([100, 100]),
    )
    scores = model.recommend_scores([])
    assert scores == {"A": 0.0, "B": 0.0}


def test_fit_cooccurrence_computes_correct_conditional_probability():
    # 4 patients: [A,B], [A], [A,B], [B] -> P(B|A) = 2/3, P(A|B) = 2/3
    matrix = pd.DataFrame(
        [[1, 1], [1, 0], [1, 1], [0, 1]],
        columns=["A", "B"],
        index=["p1", "p2", "p3", "p4"],
    ).astype(float)
    model = _fit_cooccurrence(matrix)
    a_idx, b_idx = model.families.index("A"), model.families.index("B")
    assert abs(model.cooccurrence[a_idx, b_idx] - (2 / 3)) < 1e-9
    assert abs(model.cooccurrence[b_idx, a_idx] - (2 / 3)) < 1e-9
    assert model.support[a_idx] == 3
    assert model.support[b_idx] == 3


def test_fit_cooccurrence_handles_zero_support_family():
    matrix = pd.DataFrame(
        [[1, 0], [1, 0]],
        columns=["A", "B"],
        index=["p1", "p2"],
    ).astype(float)
    model = _fit_cooccurrence(matrix)
    b_idx = model.families.index("B")
    # No patient has B at all — dividing by zero support must not raise or produce NaN.
    assert not np.isnan(model.cooccurrence[b_idx]).any()
