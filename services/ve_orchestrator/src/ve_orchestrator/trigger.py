import asyncio
from datetime import date, datetime
from temporalio.client import Client
from ve_orchestrator.workflows import DailyEngagementWorkflow


async def main():
    client = await Client.connect("localhost:7233", namespace="default")

    run_date = date.today().isoformat()

    # Use timestamp in ID so each run is unique — avoids collision
    # with any previous failed workflow that had the same date
    workflow_id = f"daily-engagement-{run_date}-{int(datetime.utcnow().timestamp())}"

    result = await client.execute_workflow(
        DailyEngagementWorkflow.run,
        run_date,
        id=workflow_id,
        task_queue="velo-engage-task-queue",
    )
    print("Workflow result:", result)


if __name__ == "__main__":
    asyncio.run(main())
