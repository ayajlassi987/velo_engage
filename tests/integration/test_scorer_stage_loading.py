"""Real end-to-end proof of Phase 1a/1b's core fix, against the actual
MLflow instance (not mocked, unlike tests/unit/test_scorer_selection.py):
registers two throwaway versions of a tiny dummy model, promotes one via
ml/registry/promote.py, and confirms resolve_production_version picks the
promoted one — not just what the mocked unit test proves in isolation.

Uses a uniquely-named throwaway model (never one of the 6 real registered
models) and cleans it up afterward so this never pollutes the real registry
shown on /models.
"""

import uuid

import mlflow
import pytest
from sklearn.linear_model import LogisticRegression

from ml.registry._stage_loader import resolve_production_version
from ml.registry.promote import promote

MLFLOW_URI = "http://localhost:5000"


@pytest.fixture
def mlflow_client():
    try:
        mlflow.set_tracking_uri(MLFLOW_URI)
        client = mlflow.MlflowClient()
        client.search_experiments(max_results=1)  # cheap reachability check
    except Exception as exc:
        pytest.skip(f"MLflow not reachable at {MLFLOW_URI} ({exc}) — start the stack first.")
    return client


@pytest.fixture
def throwaway_model(mlflow_client):
    # The "Default" experiment (id 0) predates this server's
    # --serve-artifacts/mlflow-artifacts: proxied-upload config and has a
    # stale plain-local-path artifact_location baked in at creation time —
    # writable from inside the mlflow container, not from a host-side test
    # runner. A freshly-created experiment picks up the server's current
    # default_artifact_root (the proxied scheme), which uploads correctly
    # over HTTP regardless of where the test runs from.
    experiment_name = f"test_throwaway_exp_{uuid.uuid4().hex[:8]}"
    mlflow.set_experiment(experiment_name)

    model_name = f"test_throwaway_{uuid.uuid4().hex[:8]}"
    tiny_model = LogisticRegression().fit([[0], [1]], [0, 1])

    with mlflow.start_run():
        v1 = mlflow.sklearn.log_model(
            tiny_model, artifact_path="model", registered_model_name=model_name
        )
    with mlflow.start_run():
        v2 = mlflow.sklearn.log_model(
            tiny_model, artifact_path="model", registered_model_name=model_name
        )

    yield model_name, v1, v2

    try:
        mlflow_client.delete_registered_model(model_name)
        experiment = mlflow_client.get_experiment_by_name(experiment_name)
        mlflow_client.delete_experiment(experiment.experiment_id)
    except Exception:
        pass  # best-effort cleanup — a leftover throwaway model/experiment is harmless


def test_resolve_production_version_picks_promoted_version_not_latest(mlflow_client, throwaway_model):
    model_name, v1, v2 = throwaway_model

    # Before promotion: nothing is staged, falls back to the numerically
    # latest version (v2) with a warning — same behavior as the mocked
    # unit test, now proven against real MLflow.
    resolved = resolve_production_version(mlflow_client, model_name)
    assert resolved.version == "2"

    # Promote the OLDER version (v1) — a deliberate "roll back to a known
    # good version" scenario, the case that actually matters: if promotion
    # just always picked the latest, it wouldn't be doing anything.
    promote(model_name, "1", "Production")

    resolved = resolve_production_version(mlflow_client, model_name)
    assert resolved.version == "1"
    assert resolved.current_stage == "Production"
