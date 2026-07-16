"""Guards Phase 1a's core fix: every ml/registry/*_scorer.py used to pick
the numerically-latest MLflow model version, completely ignoring
current_stage — so a bad candidate registered after the last good
Production version would silently start serving. This test targets the
new shared resolver (ml/registry/_stage_loader.py) that replaces the
duplicated inline logic in all five scorers.

Written before _stage_loader.py exists: at this point it fails with
ModuleNotFoundError, which is the point — it's the acceptance test for
Phase 1a, not a test of pre-existing behavior."""

from dataclasses import dataclass

import pytest

from ml.registry._stage_loader import resolve_production_version


@dataclass
class FakeModelVersion:
    version: str
    current_stage: str | None


class FakeClient:
    def __init__(self, versions):
        self._versions = versions

    def search_model_versions(self, filter_string):
        return self._versions


def test_prefers_production_stage_over_higher_version_number():
    client = FakeClient([
        FakeModelVersion(version="2", current_stage="Production"),
        FakeModelVersion(version="3", current_stage=None),  # newer, never promoted
    ])
    resolved = resolve_production_version(client, "ve_noshow_v1")
    assert resolved.version == "2"


def test_falls_back_to_latest_when_nothing_is_staged():
    client = FakeClient([
        FakeModelVersion(version="1", current_stage=None),
        FakeModelVersion(version="2", current_stage=None),
    ])
    resolved = resolve_production_version(client, "ve_noshow_v1")
    assert resolved.version == "2"


def test_picks_highest_version_among_multiple_production_versions():
    # Shouldn't normally happen if promote.py's archive_existing_versions=True
    # is always used, but defend against it rather than assume.
    client = FakeClient([
        FakeModelVersion(version="2", current_stage="Production"),
        FakeModelVersion(version="4", current_stage="Production"),
    ])
    resolved = resolve_production_version(client, "ve_noshow_v1")
    assert resolved.version == "4"


def test_raises_when_no_versions_registered_at_all():
    client = FakeClient([])
    with pytest.raises(RuntimeError, match="No registered versions"):
        resolve_production_version(client, "ve_noshow_v1")
