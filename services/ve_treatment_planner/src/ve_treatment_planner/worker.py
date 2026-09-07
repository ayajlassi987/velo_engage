"""Same shape as ve_orchestrator's worker.py — must run continuously, or
signals queue up but nothing advances until a worker is back online. Runs
on its own task queue ('velo-dental-task-queue') so this prototype never
competes with or interferes with the production daily-engagement worker."""

import asyncio
import logging
import os
from dotenv import load_dotenv

load_dotenv()

from temporalio.client import Client
from temporalio.worker import Worker

from ve_treatment_planner.workflows import TreatmentPathwayWorkflow
from ve_treatment_planner.activities import advance_case, apply_decision, initialize_case

logging.basicConfig(level=logging.INFO)


async def main():
    client = await Client.connect(
        os.getenv("TEMPORAL_ADDRESS", "localhost:7233"),
        namespace="default",
    )

    worker = Worker(
        client,
        task_queue="velo-dental-task-queue",
        workflows=[TreatmentPathwayWorkflow],
        activities=[initialize_case, advance_case, apply_decision],
    )

    print("Worker started — listening on 'velo-dental-task-queue' (prototype)")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
