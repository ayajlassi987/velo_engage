"""Pure-function coverage for the rule-matching logic evaluate_rules() calls
per patient (ve_orchestrator/activities.py) — written before Phase 2's
batching changes touch evaluate_rules, so a regression there is caught
independently of the DB/Neo4j plumbing around it."""

from datetime import date

import pytest

from ve_orchestrator.policy_engine import (
    PolicyError,
    build_evidence,
    conditions_match,
    evaluate_policy,
)

TODAY = date(2026, 7, 16)


def test_leaf_gte_matches():
    conditions = {"field": "days_since_last_visit", "operator": "gte", "value": 180}
    assert conditions_match(conditions, {"days_since_last_visit": 200}, TODAY) is True
    assert conditions_match(conditions, {"days_since_last_visit": 100}, TODAY) is False


def test_leaf_gte_missing_feature_is_false_not_error():
    conditions = {"field": "days_since_last_visit", "operator": "gte", "value": 180}
    assert conditions_match(conditions, {}, TODAY) is False


def test_leaf_is_null_and_not_null():
    assert conditions_match({"field": "coverage_period_end_date", "operator": "is_null"}, {}, TODAY) is True
    assert conditions_match(
        {"field": "coverage_period_end_date", "operator": "not_null"},
        {"coverage_period_end_date": "2026-08-01"}, TODAY,
    ) is True


def test_leaf_in_operator():
    conditions = {"field": "condition_codes", "operator": "contains", "value": "E11"}
    assert conditions_match(conditions, {"condition_codes": ["E11", "I10"]}, TODAY) is True
    assert conditions_match(conditions, {"condition_codes": ["I10"]}, TODAY) is False


def test_leaf_days_until_between():
    conditions = {"field": "coverage_period_end_date", "operator": "days_until_between", "value": [0, 30]}
    assert conditions_match(conditions, {"coverage_period_end_date": "2026-08-01"}, TODAY) is True
    assert conditions_match(conditions, {"coverage_period_end_date": "2027-01-01"}, TODAY) is False
    assert conditions_match(conditions, {"coverage_period_end_date": None}, TODAY) is False


def test_all_requires_every_condition():
    conditions = {"all": [
        {"field": "age", "operator": "gte", "value": 40},
        {"field": "open_treatment_plan_flag", "operator": "eq", "value": True},
    ]}
    assert conditions_match(conditions, {"age": 45, "open_treatment_plan_flag": True}, TODAY) is True
    assert conditions_match(conditions, {"age": 45, "open_treatment_plan_flag": False}, TODAY) is False


def test_any_requires_at_least_one_condition():
    conditions = {"any": [
        {"field": "age", "operator": "gte", "value": 60},
        {"field": "vip_status", "operator": "eq", "value": True},
    ]}
    assert conditions_match(conditions, {"age": 30, "vip_status": True}, TODAY) is True
    assert conditions_match(conditions, {"age": 30, "vip_status": False}, TODAY) is False


def test_nested_all_within_any():
    conditions = {"any": [
        {"all": [
            {"field": "age", "operator": "gte", "value": 65},
            {"field": "days_since_last_visit", "operator": "gte", "value": 90},
        ]},
        {"field": "vip_status", "operator": "eq", "value": True},
    ]}
    features = {"age": 70, "days_since_last_visit": 100, "vip_status": False}
    assert conditions_match(conditions, features, TODAY) is True


def test_unsupported_operator_raises():
    with pytest.raises(PolicyError):
        conditions_match({"field": "age", "operator": "regex", "value": ".*"}, {"age": 1}, TODAY)


def test_build_evidence_from_feature_and_days_until():
    policy = {"rule": {"evidence": {
        "priority_days": {"days_until": "coverage_period_end_date"},
        "age": {"feature": "age"},
        "note": {"literal": "benefit_lifecycle"},
    }}}
    features = {"coverage_period_end_date": "2026-08-01", "age": 45}
    evidence = build_evidence(policy, features, TODAY)
    assert evidence == {"priority_days": 16, "age": 45, "note": "benefit_lifecycle"}


def test_evaluate_policy_disabled_returns_none():
    policy = {"enabled": False, "rule": {"conditions": {"field": "age", "operator": "gte", "value": 1}, "evidence": {}}}
    assert evaluate_policy(policy, {"age": 99}, TODAY) is None


def test_evaluate_policy_no_match_returns_none():
    policy = {
        "enabled": True,
        "rule": {"conditions": {"field": "age", "operator": "gte", "value": 99}, "evidence": {}},
    }
    assert evaluate_policy(policy, {"age": 20}, TODAY) is None


def test_evaluate_policy_match_returns_evidence_dict():
    policy = {
        "enabled": True,
        "rule": {
            "conditions": {"field": "age", "operator": "gte", "value": 18},
            "evidence": {"age": {"feature": "age"}},
        },
    }
    result = evaluate_policy(policy, {"age": 45}, TODAY)
    assert result == {"age": 45}
