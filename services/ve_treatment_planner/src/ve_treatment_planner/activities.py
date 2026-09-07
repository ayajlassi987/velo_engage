"""Temporal activities for TreatmentPathwayWorkflow. Mirrors ve_orchestrator/
activities.py's own discipline: activities pass only IDs/plain dicts, each
one re-fetches what it needs from Postgres directly rather than trusting
workflow-held state, and all the actual decision logic lives in
pathway_engine.py (pure functions, independently unit tested) — these
activities are thin DB + pathway_engine glue, not where the clinical logic
itself is decided.

PROTOTYPE — see policies/dental_pathways/README.md. Nothing here enforces
the "clinician_reviewed-only in production" rule yet; that's a real gap to
close before any real clinic sees this (see initialize_case's docstring).
"""

import os
import sys
import uuid
from datetime import date
from pathlib import Path

import psycopg2
import psycopg2.extras
from temporalio import activity

from ve_treatment_planner.pathway_engine import (
    entry_state,
    pathway_by_id,
    rank_transitions,
    valid_transitions,
)

for _candidate in (
    Path(__file__).resolve().parents[4] if len(Path(__file__).resolve().parents) > 4 else None,
    Path("/app"),
):
    if _candidate and (_candidate / "libs").is_dir():
        sys.path.insert(0, str(_candidate))
        break
from libs.ve_clients.vault_client import get_secret


def _db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"), port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "velodb"), user=get_secret("postgres", "user", "DB_USER") or "velo",
        password=get_secret("postgres", "password", "DB_PASSWORD") or "velo_secret",
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


@activity.defn
async def initialize_case(
    case_id: str, pathway_id: str, patient_id: str, clinic_id: str, tooth: str | None, workflow_id: str,
) -> dict:
    """Creates patient_treatment_state's row for a new case if one doesn't
    already exist, or returns the existing one (idempotent — a workflow
    retry or a re-run against an already-initialized case must not reset
    real state back to the pathway's entry point).

    NOT YET ENFORCED, real gap: this should refuse to initialize a case
    against a pathway whose status isn't 'clinician_reviewed', outside of
    an explicit local/test override — see policies/dental_pathways/
    README.md. Left open in this prototype since there is currently no
    clinician-reviewed pathway to test against at all; close this before
    any real clinic rollout.
    """
    pathway = pathway_by_id(pathway_id)
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_state, closed FROM patient_treatment_state WHERE case_id = %s", (case_id,))
            existing = cur.fetchone()
            if existing:
                return {"current_state": existing["current_state"], "terminal": existing["closed"]}

            start_state = entry_state(pathway)
            cur.execute(
                """
                INSERT INTO patient_treatment_state
                    (case_id, patient_id, clinic_id, pathway_id, tooth, current_state, workflow_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (case_id, patient_id, clinic_id, pathway_id, tooth, start_state, workflow_id),
            )
        conn.commit()
        return {"current_state": start_state, "terminal": False}
    finally:
        conn.close()


def _gather_facts(conn, case_id: str, clinic_id: str, patient_id: str, tooth: str | None) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT entered_current_state_at FROM patient_treatment_state WHERE case_id = %s",
            (case_id,),
        )
        row = cur.fetchone()
        entered_at = row["entered_current_state_at"] if row else None

        # Only procedures recorded since this case entered its current
        # state count toward a transition — an old, already-considered
        # procedure shouldn't re-fire a trigger it already satisfied.
        cur.execute(
            """
            SELECT cdt_code FROM dental_procedure_history
            WHERE clinic_id = %s AND patient_id = %s AND status = 'complete'
              AND (%s::timestamptz IS NULL OR procedure_date >= %s::timestamptz)
              AND (%s::text IS NULL OR tooth = %s)
            """,
            (clinic_id, patient_id, entered_at, entered_at, tooth, tooth),
        )
        completed_codes = [r["cdt_code"] for r in cur.fetchall()]

    days_in_state = (date.today() - entered_at.date()).days if entered_at else None
    return {
        # No diagnosis source exists yet in this prototype (OpenDental's
        # diagnosis/problem-list equivalent isn't pulled by
        # ve_connect_dental today) — diagnosis_confirmed transitions are
        # unreachable via this activity until that's built. Documented gap,
        # not a silent one: see ve_connect_dental's README.md scope notes.
        "confirmed_diagnoses": [],
        "completed_cdt_codes": completed_codes,
        "days_in_state": days_in_state,
    }


@activity.defn
async def advance_case(case_id: str, pathway_id: str, patient_id: str, clinic_id: str, tooth: str | None) -> dict:
    """Recomputes valid transitions from the case's current state. A single
    unambiguous valid transition is applied automatically (the rule graph
    already made that decision, nothing for a human to weigh in on). More
    than one valid transition is left un-applied and recorded as a pending
    suggestion — advisory only, resolved by apply_decision() once a
    clinician accepts or overrides it via the console. This is the one
    place the "advisory, never autonomous" requirement is actually
    enforced in code."""
    pathway = pathway_by_id(pathway_id)
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_state, closed FROM patient_treatment_state WHERE case_id = %s", (case_id,))
            row = cur.fetchone()
        if row is None:
            raise ValueError(f"advance_case called before initialize_case for {case_id}")
        if row["closed"]:
            return {"current_state": row["current_state"], "terminal": True, "pending_decision": False, "suggested_next_states": []}

        facts = _gather_facts(conn, case_id, clinic_id, patient_id, tooth)
        options = rank_transitions(valid_transitions(pathway, row["current_state"], facts))

        if not options:
            return {
                "current_state": row["current_state"], "terminal": False,
                "pending_decision": False, "suggested_next_states": [],
            }

        state_by_id = {s["id"]: s for s in pathway["states"]}

        if len(options) == 1:
            chosen = options[0]
            new_state = chosen["to"]
            terminal = state_by_id[new_state]["terminal"]
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE patient_treatment_state
                    SET current_state = %s, entered_current_state_at = now(), updated_at = now(),
                        suggested_next_states = NULL, closed = %s
                    WHERE case_id = %s
                    """,
                    (new_state, terminal, case_id),
                )
                cur.execute(
                    """
                    INSERT INTO treatment_transition_log
                        (log_id, case_id, from_state, to_state, suggested_state, accepted)
                    VALUES (%s, %s, %s, %s, %s, NULL)
                    """,
                    (f"ttl_{uuid.uuid4().hex}", case_id, row["current_state"], new_state, new_state),
                )
            conn.commit()
            return {"current_state": new_state, "terminal": terminal, "pending_decision": False, "suggested_next_states": []}

        # Ambiguous — record the ranked options, apply nothing, wait for a
        # clinician's decision via apply_decision().
        suggested = [{"to": o["to"], "priority": o["priority"]} for o in options]
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE patient_treatment_state SET suggested_next_states = %s, updated_at = now() WHERE case_id = %s",
                (psycopg2.extras.Json(suggested), case_id),
            )
            cur.execute(
                """
                INSERT INTO treatment_transition_log
                    (log_id, case_id, from_state, to_state, suggested_state, accepted)
                VALUES (%s, %s, %s, NULL, %s, NULL)
                """,
                (f"ttl_{uuid.uuid4().hex}", case_id, row["current_state"], suggested[0]["to"]),
            )
        conn.commit()
        return {"current_state": row["current_state"], "terminal": False, "pending_decision": True, "suggested_next_states": suggested}
    finally:
        conn.close()


@activity.defn
async def apply_decision(case_id: str, pathway_id: str, chosen_state: str, accepted: bool, override_reason: str | None) -> dict:
    """Resolves a pending suggestion left by advance_case(). `accepted`
    records whether chosen_state matches the top-ranked suggestion
    (True) or the clinician picked a different valid option (False —
    override_reason is required in that case by main.py's request
    validation, not here, so this activity stays a pure DB write)."""
    pathway = pathway_by_id(pathway_id)
    state_by_id = {s["id"]: s for s in pathway["states"]}
    if chosen_state not in state_by_id:
        raise ValueError(f"{chosen_state!r} is not a state in pathway {pathway_id!r}")

    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_state FROM patient_treatment_state WHERE case_id = %s", (case_id,))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"apply_decision called for unknown case {case_id}")

            terminal = state_by_id[chosen_state]["terminal"]
            cur.execute(
                """
                UPDATE patient_treatment_state
                SET current_state = %s, entered_current_state_at = now(), updated_at = now(),
                    suggested_next_states = NULL, closed = %s
                WHERE case_id = %s
                """,
                (chosen_state, terminal, case_id),
            )
            cur.execute(
                """
                INSERT INTO treatment_transition_log
                    (log_id, case_id, from_state, to_state, suggested_state, accepted, override_reason)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (f"ttl_{uuid.uuid4().hex}", case_id, row["current_state"], chosen_state, chosen_state, accepted, override_reason),
            )
        conn.commit()
        return {"current_state": chosen_state, "terminal": terminal}
    finally:
        conn.close()
