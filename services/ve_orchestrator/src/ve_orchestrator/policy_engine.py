"""Load and safely evaluate opportunity policies stored as YAML data."""

import os
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_METHODS = {"R", "D"}
SUPPORTED_OPERATORS = {
    "eq", "ne", "gt", "gte", "lt", "lte", "in", "contains", "contains_prefix",
    "is_null", "not_null", "days_until_between",
}


class PolicyError(ValueError):
    pass


def policy_directory() -> Path:
    configured = os.getenv("OPPORTUNITY_POLICY_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[4] / "policies" / "opportunities"


def _validate(policy: dict, path: Path) -> None:
    required = {"version", "family", "title", "methods", "enabled", "activation"}
    missing = required - policy.keys()
    if missing:
        raise PolicyError(f"{path.name}: missing {', '.join(sorted(missing))}")
    if policy["version"] != 1:
        raise PolicyError(f"{path.name}: unsupported policy version")
    if path.stem.upper() != str(policy["family"]).upper():
        raise PolicyError(f"{path.name}: filename and family must match")
    if not SUPPORTED_METHODS.intersection(policy["methods"]):
        raise PolicyError(f"{path.name}: policy must include method R or D")
    if policy["enabled"]:
        if not policy.get("rule") or not policy.get("delivery"):
            raise PolicyError(f"{path.name}: enabled policy needs rule and delivery")
        conditions = policy["rule"].get("conditions")
        if not conditions:
            raise PolicyError(f"{path.name}: enabled policy needs conditions")


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
        _validate(policy, path)
        family = str(policy["family"]).upper()
        if family in families:
            raise PolicyError(f"Duplicate family policy: {family}")
        families.add(family)
        policy["family"] = family
        policies.append(policy)
    return tuple(policies)


def active_policies() -> tuple[dict, ...]:
    return tuple(policy for policy in load_policies() if policy["enabled"])


def policy_for_family(family: str, *, require_enabled: bool = True) -> dict:
    normalized = family.upper()
    for policy in load_policies():
        if policy["family"] == normalized:
            if require_enabled and not policy["enabled"]:
                raise PolicyError(f"Family {normalized} is registered but not enabled")
            return policy
    raise PolicyError(f"Unknown R/D opportunity family: {normalized}")


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _leaf_matches(condition: dict, features: dict, as_of: date) -> bool:
    operator = condition.get("operator")
    if operator not in SUPPORTED_OPERATORS:
        raise PolicyError(f"Unsupported policy operator: {operator}")
    actual = features.get(condition.get("field"))
    expected = condition.get("value")
    if operator == "is_null":
        return actual is None
    if operator == "not_null":
        return actual is not None
    if operator == "days_until_between":
        target = _coerce_date(actual)
        return bool(target and expected[0] <= (target - as_of).days <= expected[1])
    if operator == "eq":
        return actual == expected
    if operator == "ne":
        return actual != expected
    if actual is None:
        return False
    if operator == "gt":
        return actual > expected
    if operator == "gte":
        return actual >= expected
    if operator == "lt":
        return actual < expected
    if operator == "lte":
        return actual <= expected
    if operator == "in":
        return actual in expected
    if operator == "contains":
        return expected in actual
    if operator == "contains_prefix":
        # ICD-10 category matching: real Epic condition_codes are stored
        # at full precision ("E11.9"), while the synthetic seed generator
        # only ever stores bare 3-character categories ("E11") — plain
        # "contains" (exact array-element equality) can't match both
        # representations against the same code list. Family I
        # (predictive clinical risk) needs "any code in this ICD-10
        # category" regardless of which representation is present.
        return any(str(code).startswith(expected) for code in (actual or []))
    return False


def conditions_match(conditions: dict, features: dict, as_of: date) -> bool:
    if "all" in conditions:
        return all(conditions_match(item, features, as_of) for item in conditions["all"])
    if "any" in conditions:
        return any(conditions_match(item, features, as_of) for item in conditions["any"])
    return _leaf_matches(conditions, features, as_of)


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def build_evidence(policy: dict, features: dict, as_of: date) -> dict:
    evidence = {}
    for key, source in policy["rule"].get("evidence", {}).items():
        if "feature" in source:
            value = features.get(source["feature"])
        elif "days_until" in source:
            target = _coerce_date(features.get(source["days_until"]))
            value = (target - as_of).days if target else None
        else:
            value = source.get("literal")
        evidence[key] = _json_value(value)
    return evidence


def evaluate_policy(policy: dict, features: dict, as_of: date) -> dict | None:
    if not policy["enabled"]:
        return None
    if not conditions_match(policy["rule"]["conditions"], features, as_of):
        return None
    return build_evidence(policy, features, as_of)
