"""Shared model-version resolution — every ml/registry/*_scorer.py used to
duplicate the same `max(versions, key=lambda v: int(v.version))` logic,
which ignores MLflow's Production/Staging stage concept entirely: a model
version registered after the last deliberate promotion would silently
start being served, with no promotion step involved at all.

Prefers the version staged Production (via ml/registry/promote.py); falls
back to the numerically-latest version with a warning if nothing has been
promoted yet, so a freshly-registered model still scores instead of
crashing everything downstream.
"""

import logging

logger = logging.getLogger(__name__)


def resolve_production_version(client, model_name: str):
    versions = client.search_model_versions(f"name='{model_name}'")
    if not versions:
        raise RuntimeError(f"No registered versions found for model '{model_name}'")

    production = [v for v in versions if v.current_stage == "Production"]
    if production:
        return max(production, key=lambda v: int(v.version))

    latest = max(versions, key=lambda v: int(v.version))
    logger.warning(
        f"No version of '{model_name}' is staged Production — falling back to "
        f"latest registered version {latest.version}. Run "
        f"`python -m ml.registry.promote {model_name} {latest.version} --stage Production` "
        f"to pin a deliberate live version."
    )
    return latest
