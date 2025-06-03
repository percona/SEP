"""Define database operations for the Tasks API."""

import logging

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth.exceptions import HTTPForbiddenException
from app.core.db.crud import BaseSQLModelManager
from app.core.exceptions import HTTPConflictException
from app.core.utils.date_time import utc_now
from app.tasks.models import (
    DispatchLock,
    Task,
    TaskBackendEnum,
    TaskHistory,
    TaskHistoryStatusEnum,
    TaskOwner,
)

logger = logging.getLogger(__name__)


class TaskManager(BaseSQLModelManager):
    """Manage task operations, including retrieval, listing, and deletion.

    This class provides methods to interact with `Task` models in the database,
    such as listing active tasks, retrieving tasks by name, and deleting tasks.

    :ivar Model: The SQLModel class this manager is responsible for (`Task`).
    :vartype Model: type[Task]
    """

    Model = Task

    @classmethod
    async def list_active(
        cls,
        session: AsyncSession,
        owner: TaskOwner | None = None,
    ) -> list[Task]:
        """List all active (non-deleted) tasks.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        :param owner: The owner of the tasks. If provided, only tasks for this owner
            will be listed.
        :type owner: TaskOwner | None
        :return: A list of active tasks.
        :rtype: list[Task]
        """
        return await cls.list(session, col(Task.deleted_at).is_(None), owner=owner)

    @classmethod
    async def retrieve_by_name(
        cls,
        session: AsyncSession,
        name: str,
        *,
        is_template: bool | None = None,
        is_active: bool | None = None,
    ) -> Task:
        """Retrieve a task by its name, raising a 404 error if not found.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        :param name: The name of the task to retrieve.
        :type name: str
        :param is_template: Whether the task should be a template or not.
            Use None to not use the filter. Defaults to None.
        :type is_template: bool | None
        :param is_active: Whether to retrieve only active tasks (not deleted).
            If None (default), both active and deleted tasks will be considered.
        :type is_active: bool | None
        :return: The task with the given name.
        :rtype: Task
        :raises HTTPNotFoundException: If no task with the given name is found.
        """
        if is_active is None:
            return await cls.get_or_404(session, name=name, is_template=is_template)
        where = (
            col(Task.deleted_at).is_(None)
            if is_active
            else col(Task.deleted_at).isnot(None)
        )
        return await cls.get_or_404(session, where, name=name, is_template=is_template)

    @classmethod
    async def delete_by_name(cls, session: AsyncSession, name: str) -> Task:
        """Delete a task by its name, marking it as deleted.

        If the task is protected, a forbidden exception will be raised.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        :param name: The name of the task to delete.
        :type name: str
        :return: The deleted task.
        :rtype: Task
        :raises HTTPForbiddenException: If the task is protected and cannot be deleted.
        :raises HTTPConflictException: If the task is currently running or pending.
        """
        task = await cls.retrieve_by_name(session=session, name=name, is_active=True)
        if task.protected:
            raise HTTPForbiddenException(
                f"Task {name} is protected and cannot be deleted.",
            )
        # TODO(yan): Implement proper locking mechanism for deletion
        # SEP-393
        if await TaskHistoryManager.list_by_task_name(
            session=session, task_name=name, status=TaskHistoryStatusEnum.RUNNING
        ):
            raise HTTPConflictException(
                f"Task {name} is currently running and cannot be deleted."
            )
        if await TaskHistoryManager.list_by_task_name(
            session=session, task_name=name, status=TaskHistoryStatusEnum.PENDING
        ):
            raise HTTPConflictException(
                f"Task {name} is currently pending and cannot be deleted."
            )
        task.deleted_at = utc_now()
        task.name = f"{task.name}-{task.deleted_at.strftime('%Y%m%d%H%M%S')}"
        return await cls.save(session, task)

    @classmethod
    async def get_root_task(cls, session: AsyncSession, task: Task) -> Task:
        """Get the root task for a given task.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        :param task: The task for which to find the root task.
        :type task: Task
        :return: The root task.
        :rtype: Task
        """
        if task.backend == TaskBackendEnum.PROXY:
            return await cls.retrieve_by_name(session=session, name=task.data["task"])
        return task


class TaskHistoryManager(BaseSQLModelManager):
    """Manage task history operations, including listing task histories by task name.

    :ivar Model: The SQLModel class this manager is responsible for (`TaskHistory`).
    :vartype Model: type[TaskHistory]
    """

    Model = TaskHistory

    @classmethod
    async def list_by_task_name(
        cls,
        *,
        session: AsyncSession,
        task_name: str,
        status: TaskHistoryStatusEnum | None = None,
        select_related_task: bool = False,
    ) -> list[TaskHistory]:
        """List task histories by the task's name.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        :param task_name: The name of the task to list histories for.
        :type task_name: str
        :param status: The status of the task history. If provided, only histories
            with this status will be listed.
        :type status: TaskHistoryStatusEnum | None
        :param select_related_task: Whether to include the related task data in the
            result. Defaults to False.
        :type select_related_task: bool
        :return: A list of task histories for the specified task.
        :rtype: list[TaskHistory]
        """
        query = select(TaskHistory).join(Task)
        select_related = (TaskHistory.task,) if select_related_task else ()
        query = cls._filter_query(
            query,
            col(Task.name) == task_name,
            select_related=select_related,
            status=status,
        )
        result = await cls._exec(session, query)
        return list(result.all())


class DispatchLockManager(BaseSQLModelManager):
    """Manage dispatch lock operations.

    :ivar Model: The SQLModel class this manager is responsible for (`DispatchLock`).
    :vartype Model: type[DispatchLock]
    """

    Model = DispatchLock
