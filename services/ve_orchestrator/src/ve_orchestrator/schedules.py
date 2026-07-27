"""Creates one Temporal Schedule per clinic for DailyEngagementWorkflow.

Real gap found while scoping multi-clinic productization (see
PROJECT_STATUS.md): the existing `daily-engagement-schedule` was created
once by hand via `temporal schedule create` — not reproducible in code, and
with no record of the exact invocation used, impossible to safely extend to
a second clinic without risking a mismatched spec. This script replaces
that with an idempotent, IaC-managed equivalent: one schedule per active
clinic in Postgres' `clinics` table, safe to re-run (skips a clinic whose
schedule already exists rather than erroring or duplicating it).
"""

import argparse
import asyncio
import os

import psycopg2
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from ve_orchestrator.workflows import DailyEngagementWorkflow

TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "temporal:7233")
# Matches the original hand-created schedule's time (02:00 UTC daily).
CRON_EXPRESSION = os.getenv("SCHEDULE_CRON", "0 2 * * *")


def _active_clinic_ids() -> list[str]:
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "velodb"),
        user=os.getenv("DB_USER", "velo"),
        password=os.getenv("DB_PASSWORD", "velo_secret"),
    )
    cur = conn.cursor()
    cur.execute("SELECT clinic_id FROM clinics WHERE active ORDER BY clinic_id")
    clinic_ids = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return clinic_ids


async def ensure_schedule(client: Client, clinic_id: str) -> None:
    schedule_id = f"daily-engagement-schedule-{clinic_id}"
    try:
        await client.create_schedule(
            schedule_id,
            Schedule(
                action=ScheduleActionStartWorkflow(
                    DailyEngagementWorkflow.run,
                    args=[None, clinic_id],
                    id=f"daily-engagement-{clinic_id}",
                    task_queue="velo-engage-task-queue",
                ),
                spec=ScheduleSpec(cron_expressions=[CRON_EXPRESSION]),
                # Same overlap discipline as the original hand-created
                # schedule — a concurrent trigger while a run is still in
                # progress is dropped, not queued, so a slow day never
                # causes a pile-up of backlogged runs.
                policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
            ),
        )
        print(f"Created schedule: {schedule_id}")
    except ScheduleAlreadyRunningError:
        print(f"Schedule already exists, skipped: {schedule_id}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--clinic-id",
        help="Create a schedule for just this one clinic instead of every active clinic in Postgres",
    )
    args = parser.parse_args()

    client = await Client.connect(TEMPORAL_ADDRESS, namespace="default")
    clinic_ids = [args.clinic_id] if args.clinic_id else _active_clinic_ids()
    for clinic_id in clinic_ids:
        await ensure_schedule(client, clinic_id)


if __name__ == "__main__":
    asyncio.run(main())
