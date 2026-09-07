"""Load and evaluate dental treatment-pathway graphs stored as YAML data —
the dental analogue of ve_orchestrator's policy_engine.py, same "clinical/
business logic is data, not code" philosophy applied to a state machine
instead of a flat rule list.

Every function here is pure (no I/O, no Temporal, no DB) so the graph
logic — the one part of this feature with real clinical-safety
consequence — can be fully unit tested without spinning up Temporal, a
database, or a dental PMS. workflows.py/activities.py call these functions
from inside Temporal activities; they never reimplement this logic
themselves.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REQUIRED_TOP_LEVEL = {"version", "pathway", "title", "status", "states", "transitions"}
REQUIRED_STATE = {"id", "title", "entry_codes", "terminal"}
REQUIRED_TRANSITION = {"from", "to", "trigger", "priority"}
VALID_TRIGGER_TYPES = {"procedure_performed", "diagnosis_confirmed", "time_elapsed"}
VALID_STATUSES = {"prototype", "clinician_reviewed"}


class PathwayError(ValueError):
    pass


def pathway_directory() -> Path:
    configured = os.getenv("DENTAL_PATHWAY_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[4] / "policies" / "dental_pathways"


def _validate(pathway: dict, path: Path) -> None:
    missing = REQUIRED_TOP_LEVEL - pathway.keys()
    if missing:
        raise PathwayError(f"{path.name}: missing {', '.join(sorted(missing))}")
    if pathway["version"] != 1:
        raise PathwayError(f"{path.name}: unsupported pathway version")
    if pathway["pathway"] != path.stem:
        raise PathwayError(f"{path.name}: filename and 'pathway' id must match")
    if pathway["status"] not in VALID_STATUSES:
        raise PathwayError(f"{path.name}: status must be one of {sorted(VALID_STATUSES)}")

    states = pathway["states"]
    if not states:
        raise PathwayError(f"{path.name}: must define at least one state")
    state_ids = []
    for state in states:
        missing_fields = REQUIRED_STATE - state.keys()
        if missing_fields:
            raise PathwayError(f"{path.name}: state missing {', '.join(sorted(missing_fields))}")
        state_ids.append(state["id"])
    if len(state_ids) != len(set(state_ids)):
        raise PathwayError(f"{path.name}: duplicate state id")
    if not any(s["terminal"] for s in states):
        raise PathwayError(f"{path.name}: pathway must define at least one terminal state")

    state_id_set = set(state_ids)
    transitions = pathway["transitions"]
    if not transitions:
        raise PathwayError(f"{path.name}: must define at least one transition")
    for t in transitions:
        missing_fields = REQUIRED_TRANSITION - t.keys()
        if missing_fields:
            raise PathwayError(f"{path.name}: transition missing {', '.join(sorted(missing_fields))}")
        if t["from"] not in state_id_set:
            raise PathwayError(f"{path.name}: transition 'from' references unknown state {t['from']!r}")
        if t["to"] not in state_id_set:
            raise PathwayError(f"{path.name}: transition 'to' references unknown state {t['to']!r}")
        trigger_type = t["trigger"].get("type")
        if trigger_type not in VALID_TRIGGER_TYPES:
            raise PathwayError(f"{path.name}: unknown trigger type {trigger_type!r}")

    # Reachability: every state must be reachable from at least one entry
    # point (a state with no incoming transition). A state nobody can ever
    # reach is either a typo or a design gap — either way, a real patient
    # should never end up "stuck" in an undocumented dead end, so this
    # fails loudly at load time rather than silently at runtime.
    has_incoming = {t["to"] for t in transitions}
    entry_points = state_id_set - has_incoming
    if not entry_points:
        raise PathwayError(f"{path.name}: no entry state found (every state has an incoming transition — a cycle with no start)")
    if len(entry_points) > 1:
        # A state with no incoming transition looks identical to a real
        # entry point unless there's exactly one of them — two or more
        # means either genuinely ambiguous "where does a new case start,"
        # or (the more common real mistake) an isolated orphan state
        # nobody's transitions actually connect to the rest of the graph.
        # entry_state() elsewhere already assumes exactly one; enforcing
        # it here at load time is what actually catches an orphan state,
        # since an isolated node with no incoming edge would otherwise
        # count itself as "reachable" by definition and pass silently.
        raise PathwayError(
            f"{path.name}: expected exactly one entry state (no incoming transition), found {sorted(entry_points)} "
            "— an isolated/orphan state, or a genuinely ambiguous multi-entry pathway, needs to be resolved"
        )

    reachable = set(entry_points)
    frontier = list(entry_points)
    outgoing: dict[str, list[str]] = {}
    for t in transitions:
        outgoing.setdefault(t["from"], []).append(t["to"])
    while frontier:
        current = frontier.pop()
        for nxt in outgoing.get(current, []):
            if nxt not in reachable:
                reachable.add(nxt)
                frontier.append(nxt)
    unreachable = state_id_set - reachable
    if unreachable:
        raise PathwayError(f"{path.name}: unreachable state(s): {', '.join(sorted(unreachable))}")

    # Every non-terminal state needs a way forward, or a case can enter it
    # and then have nothing valid to suggest ever again.
    non_terminal_ids = {s["id"] for s in states if not s["terminal"]}
    dead_ends = non_terminal_ids - set(outgoing.keys())
    if dead_ends:
        raise PathwayError(f"{path.name}: non-terminal state(s) with no outgoing transition: {', '.join(sorted(dead_ends))}")


@lru_cache(maxsize=1)
def load_pathways() -> tuple[dict, ...]:
    directory = pathway_directory()
    if not directory.is_dir():
        raise PathwayError(f"Dental pathway directory does not exist: {directory}")
    pathways = []
    ids = set()
    for path in sorted(directory.glob("*.yml")):
        pathway = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(pathway, dict):
            raise PathwayError(f"{path.name}: pathway must be a YAML object")
        _validate(pathway, path)
        if pathway["pathway"] in ids:
            raise PathwayError(f"Duplicate pathway id: {pathway['pathway']}")
        ids.add(pathway["pathway"])
        pathways.append(pathway)
    return tuple(pathways)


def pathway_by_id(pathway_id: str) -> dict:
    for pathway in load_pathways():
        if pathway["pathway"] == pathway_id:
            return pathway
    raise PathwayError(f"Unknown pathway: {pathway_id}")


def entry_state(pathway: dict) -> str:
    """The state a brand-new case starts in — the pathway's only state with
    no incoming transition. _validate() already guarantees exactly this
    invariant holds (at least one entry point exists); pathway authoring
    for this prototype assumes exactly one, since every pilot pathway has a
    single natural starting point (e.g. exam_pending)."""
    has_incoming = {t["to"] for t in pathway["transitions"]}
    state_ids = [s["id"] for s in pathway["states"]]
    entries = [s for s in state_ids if s not in has_incoming]
    if len(entries) != 1:
        raise PathwayError(
            f"{pathway['pathway']}: expected exactly one entry state, found {entries} — "
            "resolve which one a new case should start in before using entry_state()"
        )
    return entries[0]


def _trigger_satisfied(trigger: dict, facts: dict[str, Any]) -> bool:
    trigger_type = trigger["type"]
    if trigger_type == "procedure_performed":
        performed = set(facts.get("completed_cdt_codes", []))
        return bool(performed.intersection(trigger.get("codes", [])))
    if trigger_type == "diagnosis_confirmed":
        return trigger.get("code") in facts.get("confirmed_diagnoses", [])
    if trigger_type == "time_elapsed":
        days_in_state = facts.get("days_in_state")
        return days_in_state is not None and days_in_state >= trigger.get("min_days", 0)
    return False


def _guard_satisfied(guard: dict | None, facts: dict[str, Any]) -> bool:
    if not guard:
        return True
    min_days = guard.get("time_elapsed_min_days")
    if min_days is not None:
        days_in_state = facts.get("days_in_state")
        if days_in_state is None or days_in_state < min_days:
            return False
    return True


def valid_transitions(pathway: dict, current_state: str, facts: dict[str, Any]) -> list[dict]:
    """Every transition out of current_state whose trigger and guard are
    satisfied by facts. `facts` is the only place real-world data enters
    this pure function — expected keys: completed_cdt_codes (list[str]),
    confirmed_diagnoses (list[str]), days_in_state (int | None)."""
    return [
        t for t in pathway["transitions"]
        if t["from"] == current_state
        and _trigger_satisfied(t["trigger"], facts)
        and _guard_satisfied(t.get("guard"), facts)
    ]


def rank_transitions(transitions: list[dict], edge_scores: dict[tuple[str, str], float] | None = None) -> list[dict]:
    """Orders valid transitions best-first. `edge_scores` is the hook point
    for a real ranker (frequency table or CatBoost, per the design
    discussion) keyed by (from, to) — when absent (today, prototype-only),
    falls back to each transition's static YAML `priority`. Ties broken by
    `to` for a deterministic order, since tests and callers should never
    see nondeterministic ordering from equal-priority ties."""
    def score(t: dict) -> float:
        if edge_scores is not None:
            key = (t["from"], t["to"])
            if key in edge_scores:
                return edge_scores[key]
        return t["priority"]

    return sorted(transitions, key=lambda t: (-score(t), t["to"]))
