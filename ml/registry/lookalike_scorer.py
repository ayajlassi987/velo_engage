"""Lookalike / cross-sell scorer — master spec Phase 2-3, feeding family
D's [AI] method (see policies/opportunities/D.yml and
ml/training/train_lookalike_model.py for why this is a documented
co-occurrence heuristic rather than a trained embedding model).

Unlike every other scorer in ml/registry/, this doesn't score existing
opportunities/campaigns — it recommends NEW ones: given a patient's known
opportunity-family history, which family they've never engaged with are
they most likely to respond well to. affinity_threshold (read back from the
training run, same pattern as value_scorer.py's revenue_base_rate) is the
"conservative, top-tier only" bar a recommendation must clear before the
caller should actually act on it — reading below that threshold means
"not confident enough," not "no data."
"""

import os
from functools import lru_cache

import mlflow
import mlflow.sklearn

from ml.registry._stage_loader import resolve_production_version

MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
MODEL_NAME = "velo_engage_lookalike"


@lru_cache(maxsize=1)
def _load():
    mlflow.set_tracking_uri(MLFLOW_URI)
    client = mlflow.MlflowClient()
    resolved = resolve_production_version(client, MODEL_NAME)
    model = mlflow.sklearn.load_model(f"models:/{MODEL_NAME}/{resolved.version}")
    run = client.get_run(resolved.run_id)
    affinity_threshold = float(run.data.params.get("affinity_threshold", 1.0))
    return model, affinity_threshold


def recommend_families_batch(known_families_list: list[list[str]]) -> list[tuple[str, float] | None]:
    """One entry per patient. Returns (recommended_family, score) for the
    single highest-scoring family that patient hasn't engaged with yet, or
    None if the patient has no known families to recommend from (cold
    start — this heuristic has no signal for a patient with zero history)
    or no candidate scored above affinity_threshold."""
    model, affinity_threshold = _load()
    results = []
    for known_families in known_families_list:
        if not known_families:
            results.append(None)
            continue
        scores = model.recommend_scores(known_families)
        if not scores:
            results.append(None)
            continue
        best_family, best_score = max(scores.items(), key=lambda item: item[1])
        results.append((best_family, best_score) if best_score >= affinity_threshold else None)
    return results


def affinity_threshold() -> float:
    """Exposed separately for callers (e.g. the orchestrator) that want to
    log or reason about the bar itself, not just filtered recommendations."""
    return _load()[1]
