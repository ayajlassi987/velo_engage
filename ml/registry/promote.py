#!/usr/bin/env python3
"""Promotes a registered MLflow model version to Production — the
deliberate manual gate for what ml/registry/*_scorer.py's stage-based
loader (see _stage_loader.py) will actually serve.

Deliberately manual, not automated: there's no real-outcome data yet to
safely decide "the new version is actually better" (see PROJECT_STATUS.md),
so training scripts register candidates unstaged and a human promotes.

Usage:
    python -m ml.registry.promote ve_noshow_v1 3 --stage Production
"""

import argparse
import os

import mlflow

MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")


def promote(model_name: str, version: str, stage: str) -> None:
    mlflow.set_tracking_uri(MLFLOW_URI)
    client = mlflow.MlflowClient()
    client.transition_model_version_stage(
        name=model_name,
        version=version,
        stage=stage,
        archive_existing_versions=True,
    )
    print(f"{model_name} v{version} -> {stage} (previous {stage} version, if any, archived)")
    print("Restart ve_orchestrator (and ve_console/ve_reach if they score with this model) "
          "to pick this up — each scorer caches its loaded model for the life of the process.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_name", help="Registered MLflow model name, e.g. ve_noshow_v1")
    parser.add_argument("version", help="Version number to promote, e.g. 3")
    parser.add_argument("--stage", default="Production", choices=["Production", "Staging", "Archived"])
    args = parser.parse_args()
    promote(args.model_name, args.version, args.stage)


if __name__ == "__main__":
    main()
