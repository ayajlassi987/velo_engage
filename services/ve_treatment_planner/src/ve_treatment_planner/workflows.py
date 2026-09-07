"""TreatmentPathwayWorkflow — one long-running Temporal workflow instance
per patient-case (per tooth/diagnosis, not per patient — see pathway_engine
and the design discussion this service implements). Temporal workflows are
durable state machines already; this workflow *is* the state machine
instance for one case, rather than a bespoke engine re-implementing what
Temporal already provides (durable state, timers, full audit history via
Temporal's own event log).

Same shape as ve_orchestrator's DailyEngagementWorkflow: the workflow body
only calls activities, never touches the DB or pathway_engine directly —
determinism requires that. See activities.py for the actual logic.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from ve_treatment_planner.activities import advance_case, apply_decision, initialize_case


@workflow.defn
class TreatmentPathwayWorkflow:
    def __init__(self) -> None:
        self._case_id: str | None = None
        self._pathway_id: str | None = None
        self._patient_id: str | None = None
        self._clinic_id: str | None = None
        self._tooth: str | None = None
        self._current_state: str | None = None
        self._suggested_next_states: list[dict] = []
        self._pending_decision = False
        self._pending_event = False
        self._pending_decision_input: tuple[str, bool, str | None] | None = None
        self._closed = False

    @workflow.run
    async def run(self, case_id: str, pathway_id: str, patient_id: str, clinic_id: str, tooth: str | None = None) -> dict:
        self._case_id, self._pathway_id = case_id, pathway_id
        self._patient_id, self._clinic_id, self._tooth = patient_id, clinic_id, tooth
        retry = RetryPolicy(maximum_attempts=3)
        timeout = timedelta(minutes=5)

        init = await workflow.execute_activity(
            initialize_case,
            args=[case_id, pathway_id, patient_id, clinic_id, tooth, workflow.info().workflow_id],
            start_to_close_timeout=timeout,
            retry_policy=retry,
        )
        self._current_state, self._closed = init["current_state"], init["terminal"]

        while not self._closed:
            await workflow.wait_condition(
                lambda: self._pending_event or self._pending_decision_input is not None or self._closed
            )
            if self._closed:
                break

            if self._pending_decision_input is not None:
                chosen_state, accepted, override_reason = self._pending_decision_input
                self._pending_decision_input = None
                result = await workflow.execute_activity(
                    apply_decision,
                    args=[case_id, pathway_id, chosen_state, accepted, override_reason],
                    start_to_close_timeout=timeout,
                    retry_policy=retry,
                )
                self._current_state = result["current_state"]
                self._closed = result["terminal"]
                self._pending_decision = False
                self._suggested_next_states = []
                # Known prototype limitation: a transition that becomes
                # immediately valid on entry to the new state (e.g. a
                # time_elapsed trigger with min_days: 0) isn't picked up
                # until the next record_event signal — this loop doesn't
                # re-run advance_case proactively after applying a
                # decision. Acceptable for a prototype pathway; revisit if
                # a real pathway ever needs a same-instant chained move.
                continue

            self._pending_event = False
            result = await workflow.execute_activity(
                advance_case,
                args=[case_id, pathway_id, patient_id, clinic_id, tooth],
                start_to_close_timeout=timeout,
                retry_policy=retry,
            )
            self._current_state = result["current_state"]
            self._closed = result["terminal"]
            self._pending_decision = result["pending_decision"]
            self._suggested_next_states = result["suggested_next_states"]

        return {"case_id": case_id, "final_state": self._current_state}

    @workflow.signal
    def record_event(self) -> None:
        """Fired when ve_connect_dental observes new procedure/appointment
        data for this case (or, in the batch-fallback trigger mode
        discussed in the design — see ARCHITECTURE-adjacent conversation —
        during ve_orchestrator's own daily refresh). Carries no payload:
        advance_case() re-reads dental_procedure_history itself rather than
        trusting whatever the signal sender happened to pass, so a signal
        is just a wake-up, not a data transport."""
        self._pending_event = True

    @workflow.signal
    def record_decision(self, chosen_state: str, accepted: bool, override_reason: str | None = None) -> None:
        """A clinician's accept/override action on a pending suggestion,
        sent by the console. Ignored if nothing is actually pending —
        avoids a stale/duplicate console click silently corrupting state
        that already moved on."""
        if self._pending_decision:
            self._pending_decision_input = (chosen_state, accepted, override_reason)

    @workflow.signal
    def close_pathway(self) -> None:
        self._closed = True

    @workflow.query
    def get_current_state(self) -> dict:
        return {
            "case_id": self._case_id,
            "pathway_id": self._pathway_id,
            "current_state": self._current_state,
            "pending_decision": self._pending_decision,
            "suggested_next_states": self._suggested_next_states,
            "closed": self._closed,
        }
