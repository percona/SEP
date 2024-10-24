from http import HTTPStatus
from fastapi import HTTPException
from app.tasks.crud import TaskHistoryManager
from app.tasks.db import get_async_session_maker
from app.tasks.deps import get_executor
from app.tasks.models import TaskBackendEnum, TaskHistory, TaskHistoryStatusEnum


async def process_queue_item(queue_id: int) -> None:
    """Process an item from the history table."""
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

        match task.backend:
            case TaskBackendEnum.NOMAD:
                executor = get_executor()
            case _:
                raise HTTPException(status_code=HTTPStatus.BAD_REQUEST)

        await executor.run(session, queue_item)
