"""Pure-function coverage for ve_treatment_planner's pathway_engine.py — the
one part of the dental-pathway prototype with real clinical-safety
consequence (see policies/dental_pathways/README.md), so it gets the same
"test the pure logic independently of Temporal/DB/HTTP" treatment
ve_orchestrator's policy_engine.py already gets in test_policy_engine.py."""

from pathlib import Path

import pytest

from ve_treatment_planner.pathway_engine import (
    PathwayError,
    _validate,
    entry_state,
    load_pathways,
    pathway_by_id,
    rank_transitions,
    valid_transitions,
)

FAKE_PATH = Path("test_pathway.yml")


def _base_pathway(**overrides) -> dict:
    pathway = {
        "version": 1,
        "pathway": "test_pathway",
        "title": "Test pathway",
        "status": "prototype",
        "states": [
            {"id": "a", "title": "A", "entry_codes": [], "terminal": False},
            {"id": "b", "title": "B", "entry_codes": [], "terminal": True},
        ],
        "transitions": [
            {"from": "a", "to": "b", "trigger": {"type": "procedure_performed", "codes": ["D1"]}, "priority": 1.0},
        ],
    }
    pathway.update(overrides)
    return pathway


# --- _validate ---------------------------------------------------------

def test_validate_accepts_well_formed_pathway():
    _validate(_base_pathway(), FAKE_PATH)  # should not raise


def test_validate_rejects_missing_top_level_field():
    pathway = _base_pathway()
    del pathway["status"]
    with pytest.raises(PathwayError, match="missing"):
        _validate(pathway, FAKE_PATH)


def test_validate_rejects_filename_pathway_id_mismatch():
    pathway = _base_pathway(pathway="something_else")
    with pytest.raises(PathwayError, match="filename"):
        _validate(pathway, FAKE_PATH)


def test_validate_rejects_unknown_status():
    pathway = _base_pathway(status="not_a_real_status")
    with pytest.raises(PathwayError, match="status"):
        _validate(pathway, FAKE_PATH)


def test_validate_rejects_duplicate_state_id():
    pathway = _base_pathway()
    pathway["states"].append({"id": "a", "title": "Duplicate A", "entry_codes": [], "terminal": True})
    with pytest.raises(PathwayError, match="duplicate state id"):
        _validate(pathway, FAKE_PATH)


def test_validate_requires_at_least_one_terminal_state():
    pathway = _base_pathway()
    pathway["states"] = [{"id": "a", "title": "A", "entry_codes": [], "terminal": False}]
    pathway["transitions"] = [{"from": "a", "to": "a", "trigger": {"type": "time_elapsed", "min_days": 1}, "priority": 1.0}]
    with pytest.raises(PathwayError, match="terminal"):
        _validate(pathway, FAKE_PATH)


def test_validate_rejects_transition_to_unknown_state():
    pathway = _base_pathway()
    pathway["transitions"][0]["to"] = "does_not_exist"
    with pytest.raises(PathwayError, match="unknown state"):
        _validate(pathway, FAKE_PATH)


def test_validate_rejects_unknown_trigger_type():
    pathway = _base_pathway()
    pathway["transitions"][0]["trigger"] = {"type": "psychic_prediction"}
    with pytest.raises(PathwayError, match="trigger type"):
        _validate(pathway, FAKE_PATH)


def test_validate_rejects_isolated_orphan_state_via_entry_point_count():
    pathway = _base_pathway()
    # 'c' has no incoming transition either, so it looks like a second
    # entry point — the real failure mode this catches: an orphan state
    # nobody's transitions actually connect to the rest of the graph.
    pathway["states"].append({"id": "c", "title": "Unreachable", "entry_codes": [], "terminal": True})
    with pytest.raises(PathwayError, match="exactly one entry state"):
        _validate(pathway, FAKE_PATH)


def test_validate_rejects_unreachable_disconnected_subgraph():
    pathway = _base_pathway()
    # 'x' and 'y' each have an incoming transition (from each other), so
    # neither is counted as an entry point — but the pair is still
    # disconnected from 'a', the pathway's only real entry. This is the
    # reachability BFS catching what the entry-point count check can't.
    pathway["states"].append({"id": "x", "title": "X", "entry_codes": [], "terminal": False})
    pathway["states"].append({"id": "y", "title": "Y", "entry_codes": [], "terminal": True})
    pathway["transitions"].append({"from": "x", "to": "y", "trigger": {"type": "time_elapsed", "min_days": 1}, "priority": 1.0})
    pathway["transitions"].append({"from": "y", "to": "x", "trigger": {"type": "time_elapsed", "min_days": 1}, "priority": 1.0})
    with pytest.raises(PathwayError, match="unreachable"):
        _validate(pathway, FAKE_PATH)


def test_validate_rejects_dead_end_non_terminal_state():
    pathway = _base_pathway()
    pathway["states"].append({"id": "c", "title": "Dead end", "entry_codes": [], "terminal": False})
    pathway["transitions"].append(
        {"from": "b", "to": "c", "trigger": {"type": "time_elapsed", "min_days": 1}, "priority": 1.0}
    )
    # 'c' is non-terminal and has no outgoing transition — a case could
    # enter it and then have nothing valid to suggest, ever.
    with pytest.raises(PathwayError, match="no outgoing transition"):
        _validate(pathway, FAKE_PATH)


def test_validate_rejects_graph_with_no_entry_point():
    pathway = _base_pathway()
    # Every state has an incoming transition — a cycle with no start.
    pathway["states"] = [
        {"id": "a", "title": "A", "entry_codes": [], "terminal": False},
        {"id": "b", "title": "B", "entry_codes": [], "terminal": True},
    ]
    pathway["transitions"] = [
        {"from": "a", "to": "b", "trigger": {"type": "time_elapsed", "min_days": 1}, "priority": 1.0},
        {"from": "b", "to": "a", "trigger": {"type": "time_elapsed", "min_days": 1}, "priority": 1.0},
    ]
    with pytest.raises(PathwayError, match="no entry state"):
        _validate(pathway, FAKE_PATH)


# --- load_pathways() against the real pilot pathway ---------------------

def test_real_pilot_pathway_loads_and_validates():
    load_pathways.cache_clear()
    pathways = load_pathways()
    ids = {p["pathway"] for p in pathways}
    assert "restorative_endodontic" in ids


def test_pathway_by_id_unknown_raises():
    load_pathways.cache_clear()
    with pytest.raises(PathwayError, match="Unknown pathway"):
        pathway_by_id("not_a_real_pathway")


def test_entry_state_of_real_pilot_pathway_is_exam_pending():
    load_pathways.cache_clear()
    pathway = pathway_by_id("restorative_endodontic")
    assert entry_state(pathway) == "exam_pending"


# --- valid_transitions / rank_transitions --------------------------------

def test_valid_transitions_procedure_performed_matches_any_overlapping_code():
    pathway = _base_pathway()
    pathway["transitions"][0]["trigger"] = {"type": "procedure_performed", "codes": ["D1", "D2"]}
    assert valid_transitions(pathway, "a", {"completed_cdt_codes": ["D2"]}) == pathway["transitions"]
    assert valid_transitions(pathway, "a", {"completed_cdt_codes": ["D9"]}) == []
    assert valid_transitions(pathway, "a", {}) == []


def test_valid_transitions_diagnosis_confirmed():
    pathway = _base_pathway()
    pathway["transitions"][0]["trigger"] = {"type": "diagnosis_confirmed", "code": "deep_caries"}
    assert valid_transitions(pathway, "a", {"confirmed_diagnoses": ["deep_caries"]}) == pathway["transitions"]
    assert valid_transitions(pathway, "a", {"confirmed_diagnoses": ["shallow_caries"]}) == []


def test_valid_transitions_time_elapsed_respects_min_days():
    pathway = _base_pathway()
    pathway["transitions"][0]["trigger"] = {"type": "time_elapsed", "min_days": 180}
    assert valid_transitions(pathway, "a", {"days_in_state": 180}) == pathway["transitions"]
    assert valid_transitions(pathway, "a", {"days_in_state": 179}) == []
    assert valid_transitions(pathway, "a", {"days_in_state": None}) == []
    assert valid_transitions(pathway, "a", {}) == []


def test_valid_transitions_guard_overrides_trigger_satisfaction():
    pathway = _base_pathway()
    pathway["transitions"][0]["trigger"] = {"type": "procedure_performed", "codes": ["D1"]}
    pathway["transitions"][0]["guard"] = {"time_elapsed_min_days": 14}
    facts_trigger_only = {"completed_cdt_codes": ["D1"], "days_in_state": 5}
    assert valid_transitions(pathway, "a", facts_trigger_only) == []
    facts_both_satisfied = {"completed_cdt_codes": ["D1"], "days_in_state": 14}
    assert valid_transitions(pathway, "a", facts_both_satisfied) == pathway["transitions"]


def test_valid_transitions_filters_to_current_state_only():
    pathway = _base_pathway()
    pathway["states"].append({"id": "c", "title": "C", "entry_codes": [], "terminal": True})
    pathway["transitions"][0]["trigger"] = {"type": "time_elapsed", "min_days": 0}
    pathway["transitions"].append(
        {"from": "b", "to": "c", "trigger": {"type": "time_elapsed", "min_days": 0}, "priority": 1.0}
    )
    facts = {"days_in_state": 0}
    assert len(valid_transitions(pathway, "a", facts)) == 1
    assert valid_transitions(pathway, "a", facts)[0]["to"] == "b"


def test_rank_transitions_falls_back_to_static_priority():
    low = {"from": "a", "to": "x", "trigger": {}, "priority": 0.2}
    high = {"from": "a", "to": "y", "trigger": {}, "priority": 0.9}
    assert rank_transitions([low, high]) == [high, low]


def test_rank_transitions_uses_edge_scores_when_provided():
    low_priority_but_scored_higher = {"from": "a", "to": "x", "trigger": {}, "priority": 0.2}
    high_priority_but_scored_lower = {"from": "a", "to": "y", "trigger": {}, "priority": 0.9}
    edge_scores = {("a", "x"): 5.0, ("a", "y"): 1.0}
    ranked = rank_transitions([low_priority_but_scored_higher, high_priority_but_scored_lower], edge_scores)
    assert ranked == [low_priority_but_scored_higher, high_priority_but_scored_lower]


def test_rank_transitions_ties_break_deterministically_by_target_state():
    a = {"from": "start", "to": "b_state", "trigger": {}, "priority": 1.0}
    b = {"from": "start", "to": "a_state", "trigger": {}, "priority": 1.0}
    assert rank_transitions([a, b]) == [b, a]
