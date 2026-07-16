"""
workflows.py — updated to match slim activity signatures (IDs only between steps).
"""

from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from ve_orchestrator.activities import (
        pull_epic_data,
        evaluate_rules,
        gate_consent,
        rank_and_assign_holdout,
        dispatch_treated_to_reach,
    )


@workflow.defn
class DailyEngagementWorkflow:
    @workflow.run
    async def run(self, run_date: str | None = None) -> dict:
        if run_date is None:
            # Scheduled runs (Temporal Schedule) invoke with no args; derive the
            # date deterministically from workflow time rather than wall-clock.
            run_date = workflow.now().date().isoformat()
        retry  = RetryPolicy(maximum_attempts=3)
        timeout = timedelta(minutes=10)

        # Best-effort refresh of real Epic data — never blocks the rest of the
        # pipeline (see pull_epic_data's own docstring for why this activity
        # swallows its own errors rather than raising).
        epic_pull_result = await workflow.execute_activity(
            pull_epic_data,
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        # Each activity returns IDs only — no large payloads crossing the 2MB limit
        opportunity_ids = await workflow.execute_activity(
            evaluate_rules,
            start_to_close_timeout=timeout,
            retry_policy=retry,
        )

        allowed_ids = await workflow.execute_activity(
            gate_consent,
            opportunity_ids,
            start_to_close_timeout=timeout,
            retry_policy=retry,
        )

        campaign_ids = await workflow.execute_activity(
            rank_and_assign_holdout,
            args=[allowed_ids, run_date],
            start_to_close_timeout=timeout,
            retry_policy=retry,
        )

        dispatched_count = await workflow.execute_activity(
            dispatch_treated_to_reach,
            campaign_ids,
            start_to_close_timeout=timeout,
            retry_policy=retry,
        )

        return {
            "run_date":            run_date,
            "epic_pull":           epic_pull_result,
            "opportunities_found": len(opportunity_ids),
            "passed_consent":      len(allowed_ids),
            "campaigns_created":   len(campaign_ids),
            "dispatched":          dispatched_count,
        }