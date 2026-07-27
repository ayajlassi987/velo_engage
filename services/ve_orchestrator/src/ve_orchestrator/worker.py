"""
The worker connects to Temporal's server and polls for work. It must be
running continuously — if it's down, scheduled workflows queue up but
don't execute until a worker comes back online.
"""

import asyncio
import logging
import os
from dotenv import load_dotenv

load_dotenv()

from temporalio.client import Client
from temporalio.worker import Worker

from ve_orchestrator.workflows import DailyEngagementWorkflow
from ve_orchestrator.activities import (
    pull_epic_data,
    refresh_historical_features,
    evaluate_rules,
    gate_consent,
    rank_and_assign_holdout,
    dispatch_treated_to_reach,
)

logging.basicConfig(level=logging.INFO)


async def main():
    client = await Client.connect(
        os.getenv("TEMPORAL_ADDRESS", "localhost:7233"),
        namespace="default",
    )

    worker = Worker(
        client,
        task_queue="velo-engage-task-queue",
        workflows=[DailyEngagementWorkflow],
        activities=[
            pull_epic_data,
            refresh_historical_features,
            evaluate_rules,
            gate_consent,
            rank_and_assign_holdout,
            dispatch_treated_to_reach,
        ],
    )

    print("Worker started — listening on 'velo-engage-task-queue'")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
