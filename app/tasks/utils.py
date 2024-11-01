"""Provide utility functions for processing task queue items."""

from http import HTTPStatus

from fastapi import HTTPException

from app.tasks.crud import TaskHistoryManager, TaskManager
from app.tasks.db import get_async_session_maker
from app.tasks.deps import get_executor
from app.tasks.models import TaskBackendEnum, TaskHistory, TaskHistoryStatusEnum


async def process_queue_item(queue_id: int) -> None:
    """Process an item from the history table.

    :param queue_id: The unique identifier of the queue item to process.
    :type queue_id: int
    :raises ValueError: If the `queue_id` does not correspond to a valid item.
    :raises DatabaseError: If there is an issue accessing the history table.
    """
    async_session = get_async_session_maker()
    async with async_session() as session:
        queue_item = await TaskHistoryManager.get_or_404(
            session,
            select_related=[TaskHistory.task],
            id=queue_id,
        )
        task = queue_item.task

        if queue_item.status != TaskHistoryStatusEnum.PENDING:
            raise HTTPException(status_code=HTTPStatus.EXPECTATION_FAILED)

        if task.backend == TaskBackendEnum.PROXY:
            task = await TaskManager.retrieve_by_name(
                session=session, name=task.data["task"]
            )

        match task.backend:
            case TaskBackendEnum.NOMAD:
                executor = get_executor()
            case _:
                raise HTTPException(status_code=HTTPStatus.BAD_REQUEST)
        await executor.run(session, queue_item, task)
