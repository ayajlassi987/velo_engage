"""Read delivery configuration from the shared opportunity policy catalog."""

import os
from functools import lru_cache
from pathlib import Path

import yaml

SUPPORTED_METHODS = {"R", "D"}


class PolicyError(ValueError):
    pass


def policy_directory() -> Path:
    configured = os.getenv("OPPORTUNITY_POLICY_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[4] / "policies" / "opportunities"


@lru_cache(maxsize=1)
def load_policies() -> tuple[dict, ...]:
    directory = policy_directory()
    if not directory.is_dir():
        raise PolicyError(f"Opportunity policy directory does not exist: {directory}")
    policies = []
    families = set()
    for path in sorted(directory.glob("*.yml")):
        policy = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(policy, dict):
            raise PolicyError(f"{path.name}: policy must be a YAML object")
        family = str(policy.get("family", "")).upper()
        if path.stem.upper() != family:
            raise PolicyError(f"{path.name}: filename and family must match")
        if not SUPPORTED_METHODS.intersection(policy.get("methods", [])):
            raise PolicyError(f"{path.name}: family must include method R or D")
        if family in families:
            raise PolicyError(f"Duplicate family policy: {family}")
        if policy.get("enabled") and not policy.get("delivery"):
            raise PolicyError(f"{path.name}: enabled policy needs delivery settings")
        families.add(family)
        policy["family"] = family
        policies.append(policy)
    return tuple(policies)


def active_families() -> tuple[str, ...]:
    return tuple(policy["family"] for policy in load_policies() if policy.get("enabled"))


def policy_for_family(family: str) -> dict:
    normalized = family.upper()
    for policy in load_policies():
        if policy["family"] == normalized:
            if not policy.get("enabled"):
                raise PolicyError(f"Family {normalized} is registered but not enabled")
            return policy
    raise PolicyError(f"Unknown R/D opportunity family: {normalized}")
