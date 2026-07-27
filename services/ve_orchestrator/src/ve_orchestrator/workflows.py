"""
workflows.py — updated to match slim activity signatures (IDs only between steps).
"""

from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from ve_orchestrator.activities import (
        pull_epic_data,
        refresh_historical_features,
        evaluate_rules,
        gate_consent,
        rank_and_assign_holdout,
        dispatch_treated_to_reach,
    )


@workflow.defn
class DailyEngagementWorkflow:
    @workflow.run
    async def run(self, run_date: str | None = None, clinic_id: str | None = None) -> dict:
        if run_date is None:
            # Scheduled runs (Temporal Schedule) invoke with no args; derive the
            # date deterministically from workflow time rather than wall-clock.
            run_date = workflow.now().date().isoformat()
        retry  = RetryPolicy(maximum_attempts=3)
        timeout = timedelta(minutes=10)

        # Best-effort refresh of real Epic data — never blocks the rest of the
        # pipeline (see pull_epic_data's own docstring for why this activity
        # swallows its own errors rather than raising). Not clinic-scoped:
        # ve_connect's Epic OAuth credentials are a single global connection
        # today, not per-clinic (a real external registration step with Epic,
        # not something this refactor can complete on its own).
        epic_pull_result = await workflow.execute_activity(
            pull_epic_data,
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        # Recompute historical no-show features before evaluate_rules reads
        # patient_features (see refresh_historical_features's own docstring).
        # Not best-effort like pull_epic_data — a failure here means scoring
        # falls back to scorer.py's DEFAULTS for every patient, same as
        # before this activity existed, so letting the retry policy handle
        # transient DB errors is fine rather than swallowing them silently.
        await workflow.execute_activity(
            refresh_historical_features,
            args=[clinic_id],
            start_to_close_timeout=timeout,
            retry_policy=retry,
        )

        # evaluate_rules is the only activity that needs clinic_id directly —
        # it decides which clinic's patient population to evaluate. Every
        # activity downstream operates on the opportunity/campaign IDs it's
        # handed, reading each row's own clinic_id column from the DB rather
        # than filtering by a separate parameter, so they stay correctly
        # scoped without needing to know which clinic explicitly.
        opportunity_ids = await workflow.execute_activity(
            evaluate_rules,
            args=[clinic_id],
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
            "clinic_id":           clinic_id,
            "epic_pull":           epic_pull_result,
            "opportunities_found": len(opportunity_ids),
            "passed_consent":      len(allowed_ids),
            "campaigns_created":   len(campaign_ids),
            "dispatched":          dispatched_count,
        }