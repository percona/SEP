# TODO: All logic here, raise exceptions
from datetime import datetime
from datetime import UTC

from sqlmodel import col
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth.exceptions import HTTPForbiddenException
from app.core.db.crud import BaseManager
from app.tasks.models import Task
from app.tasks.models import TaskHistory


class TaskManager(BaseManager):
    Model = Task

    @classmethod
    async def list_active(
        cls,
        *,
        session: AsyncSession,
        owner: str | None = None,
    ) -> list[Task]:
        return await cls.list(session, col(Task.deleted_at).is_(None), owner=owner)

    @classmethod
    async def retrieve_by_name(
        cls,
        *,
        session: AsyncSession,
        name: str,
        is_template: bool | None = None,
    ) -> Task:
        return await cls.get_or_404(session, name=name, is_template=is_template)

    @classmethod
    async def delete_by_name(cls, *, session: AsyncSession, name: str) -> Task:
        task = await cls.retrieve_by_name(session=session, name=name)
        if task.protected:
            raise HTTPForbiddenException(
                f"Task {name} is protected and cannot be deleted.",
            )
        task.deleted_at = datetime.now(UTC)
        return await cls.save(session, task)


class TaskHistoryManager(BaseManager):
    Model = TaskHistory

    @classmethod
    async def list_by_task_name(
        cls,
        *,
        session: AsyncSession,
        task_name: str,
        select_related_task: bool = False,
    ) -> list[TaskHistory]:
        query = select(TaskHistory).join(Task)
        select_related = (TaskHistory.task,) if select_related_task else ()
        query = cls._filter_query(
            query,
            col(Task.name) == task_name,
            select_related=select_related,
        )
        result = await cls._exec(session, query)
        return list(result.all())
