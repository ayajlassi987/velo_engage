import argparse
import asyncio
from datetime import date, datetime
from temporalio.client import Client
from ve_orchestrator.workflows import DailyEngagementWorkflow


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clinic-id", default=None, help="Defaults to the workflow's own single-clinic fallback if omitted")
    args = parser.parse_args()

    client = await Client.connect("localhost:7233", namespace="default")

    run_date = date.today().isoformat()

    # Use timestamp in ID so each run is unique — avoids collision
    # with any previous failed workflow that had the same date
    workflow_id = f"daily-engagement-{run_date}-{int(datetime.utcnow().timestamp())}"

    result = await client.execute_workflow(
        DailyEngagementWorkflow.run,
        args=[run_date, args.clinic_id],
        id=workflow_id,
        task_queue="velo-engage-task-queue",
    )
    print("Workflow result:", result)


if __name__ == "__main__":
    asyncio.run(main())
