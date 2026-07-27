"""Tests recommend_families_batch()'s batching/threshold/cold-start logic
by mocking _load() directly — same boundary-mocking approach used
throughout this test suite for external-dependency calls (e.g.
nemoguard_client's httpx.Client mocking), since there's no existing
precedent in this codebase for unit-testing scorer wrappers against a
mocked MLflow (the real load is verified live instead)."""

import ml.registry.lookalike_scorer as scorer


class FakeModel:
    def __init__(self, fixed_scores: dict):
        self._fixed_scores = fixed_scores

    def recommend_scores(self, known_families):
        return {f: s for f, s in self._fixed_scores.items() if f not in known_families}


def test_recommends_best_family_above_threshold(monkeypatch):
    model = FakeModel({"B": 0.9, "C": 0.2})
    monkeypatch.setattr(scorer, "_load", lambda: (model, 0.5))

    result = scorer.recommend_families_batch([["A"]])

    assert result == [("B", 0.9)]


def test_returns_none_when_best_score_below_threshold(monkeypatch):
    model = FakeModel({"B": 0.3, "C": 0.2})
    monkeypatch.setattr(scorer, "_load", lambda: (model, 0.5))

    result = scorer.recommend_families_batch([["A"]])

    assert result == [None]


def test_returns_none_for_patient_with_no_known_families(monkeypatch):
    model = FakeModel({"B": 0.9})
    monkeypatch.setattr(scorer, "_load", lambda: (model, 0.5))

    result = scorer.recommend_families_batch([[]])

    assert result == [None]


def test_batches_multiple_patients_independently(monkeypatch):
    model = FakeModel({"B": 0.9, "C": 0.6})
    monkeypatch.setattr(scorer, "_load", lambda: (model, 0.5))

    result = scorer.recommend_families_batch([["A"], [], ["B"]])

    assert result == [("B", 0.9), None, ("C", 0.6)]


def test_affinity_threshold_reads_back_from_load(monkeypatch):
    monkeypatch.setattr(scorer, "_load", lambda: (FakeModel({}), 0.734))
    assert scorer.affinity_threshold() == 0.734
