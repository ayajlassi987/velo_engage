"""STUB — LangGraph structural placeholder. See services/ve_agent/README.md.

Not deployed. The live pipeline runs on Temporal (ve_orchestrator), not this
graph. Every node below is a stand-in that logs what a real implementation
would do; none of them touch production data. This exists solely so the
architecture diagram's "VE Agent (LangGraph orchestrator)" module has a
concrete, runnable (if `langgraph` is installed) shape:

    trigger -> load_cohort -> run_detectors -> enrich_score -> dedupe
    -> guard_gate -> decide_nba -> assign_holdout -> dispatch_to_reach
    -> await_outcome -> record_label -> monitor
"""

from typing import TypedDict

from langgraph.graph import StateGraph, END


class EngagementState(TypedDict, total=False):
    run_date: str
    cohort_size: int
    opportunities: list[dict]
    scored: list[dict]
    deduped: list[dict]
    gated: list[dict]
    decided: list[dict]
    dispatched: int
    log: list[str]


def _note(state: EngagementState, message: str) -> EngagementState:
    state.setdefault("log", []).append(message)
    return state


def load_cohort(state: EngagementState) -> EngagementState:
    return _note(state, "STUB: would load the patient cohort from VE Store")


def run_detectors(state: EngagementState) -> EngagementState:
    # A real implementation would call the same policy_engine.py evaluator
    # (and, for family B, graph_client.py) that ve_orchestrator uses.
    return _note(state, "STUB: would run all 15 R/D opportunity detectors")


def enrich_score(state: EngagementState) -> EngagementState:
    # A real implementation would call ml/registry/scorer.py the same way
    # ve_orchestrator.activities.rank_and_assign_holdout does.
    return _note(state, "STUB: would enrich with propensity/value/urgency scores")


def dedupe(state: EngagementState) -> EngagementState:
    return _note(state, "STUB: would keep one primary opportunity per patient")


def guard_gate(state: EngagementState) -> EngagementState:
    return _note(state, "STUB: would apply consent, cooldown, and frequency caps")


def decide_nba(state: EngagementState) -> EngagementState:
    return _note(state, "STUB: would rank by expected value and pick channel/timing/offer")


def assign_holdout(state: EngagementState) -> EngagementState:
    return _note(state, "STUB: would assign the randomized treated/holdout split")


def dispatch_to_reach(state: EngagementState) -> EngagementState:
    return _note(state, "STUB: would publish treated campaigns to NATS for ve_reach")


def await_outcome(state: EngagementState) -> EngagementState:
    return _note(state, "STUB: would await delivery/reply/booking events from ve_measure")


def record_label(state: EngagementState) -> EngagementState:
    return _note(state, "STUB: would feed outcomes back as training labels")


def monitor(state: EngagementState) -> EngagementState:
    return _note(state, "STUB: would check drift/calibration and raise retrain triggers")


def build_graph():
    graph = StateGraph(EngagementState)
    graph.add_node("load_cohort", load_cohort)
    graph.add_node("run_detectors", run_detectors)
    graph.add_node("enrich_score", enrich_score)
    graph.add_node("dedupe", dedupe)
    graph.add_node("guard_gate", guard_gate)
    graph.add_node("decide_nba", decide_nba)
    graph.add_node("assign_holdout", assign_holdout)
    graph.add_node("dispatch_to_reach", dispatch_to_reach)
    graph.add_node("await_outcome", await_outcome)
    graph.add_node("record_label", record_label)
    graph.add_node("monitor", monitor)

    graph.set_entry_point("load_cohort")
    graph.add_edge("load_cohort", "run_detectors")
    graph.add_edge("run_detectors", "enrich_score")
    graph.add_edge("enrich_score", "dedupe")
    graph.add_edge("dedupe", "guard_gate")
    graph.add_edge("guard_gate", "decide_nba")
    graph.add_edge("decide_nba", "assign_holdout")
    graph.add_edge("assign_holdout", "dispatch_to_reach")
    graph.add_edge("dispatch_to_reach", "await_outcome")
    graph.add_edge("await_outcome", "record_label")
    graph.add_edge("record_label", "monitor")
    graph.add_edge("monitor", END)
    return graph.compile()


if __name__ == "__main__":
    compiled = build_graph()
    result = compiled.invoke({"run_date": "stub-run"})
    for line in result.get("log", []):
        print(line)
