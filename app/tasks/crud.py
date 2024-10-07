"""Define database operations for the Tasks API."""

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
    """Manage task operations, including retrieval, listing, and deletion.

    This class provides methods to interact with `Task` models in the database,
    such as listing active tasks, retrieving tasks by name, and deleting tasks.

    Attributes
    ----------
    Model : Type[Task]
        The SQLModel class this manager is responsible for (`Task`).

    """

    Model = Task

    @classmethod
    async def list_active(
        cls,
        *,
        session: AsyncSession,
        owner: str | None = None,
    ) -> list[Task]:
        """List all active (non-deleted) tasks.

        Parameters
        ----------
        session : AsyncSession
            The SQLAlchemy asynchronous session to use for query execution.
        owner : str or None, optional
            The owner of the tasks. If provided, only tasks for this owner will
            be listed.

        Returns
        -------
        list[Task]
            A list of active tasks.

        """
        return await cls.list(session, col(Task.deleted_at).is_(None), owner=owner)

    @classmethod
    async def retrieve_by_name(
        cls,
        *,
        session: AsyncSession,
        name: str,
        is_template: bool | None = None,
    ) -> Task:
        """Retrieve a task by its name, raising a 404 error if not found.

        Parameters
        ----------
        session : AsyncSession
            The SQLAlchemy asynchronous session to use for query execution.
        name : str
            The name of the task to retrieve.
        is_template : bool or None, optional
            Whether the task should be a template or not.
            Use None to not use the filter. Defaults to None.

        Returns
        -------
        Task
            The task with the given name.

        Raises
        ------
        HTTPNotFoundException
            If no task with the given name is found.

        """
        return await cls.get_or_404(session, name=name, is_template=is_template)

    @classmethod
    async def delete_by_name(cls, *, session: AsyncSession, name: str) -> Task:
        """Delete a task by its name, marking it as deleted.

        If the task is protected, a forbidden exception will be raised.

        Parameters
        ----------
        session : AsyncSession
            The SQLAlchemy asynchronous session to use for query execution.
        name : str
            The name of the task to delete.

        Returns
        -------
        Task
            The deleted task.

        Raises
        ------
        HTTPForbiddenException
            If the task is protected and cannot be deleted.

        """
        task = await cls.retrieve_by_name(session=session, name=name)
        if task.protected:
            raise HTTPForbiddenException(
                f"Task {name} is protected and cannot be deleted.",
            )
        task.deleted_at = datetime.now(UTC)
        return await cls.save(session, task)


class TaskHistoryManager(BaseManager):
    """Manage task history operations, including listing task histories by task name.

    This class provides methods to interact with `TaskHistory` models in the database,
    such as querying histories for a specific task.

    Attributes
    ----------
    Model : Type[TaskHistory]
        The SQLModel class this manager is responsible for (`TaskHistory`).

    """

    Model = TaskHistory

    @classmethod
    async def list_by_task_name(
        cls,
        *,
        session: AsyncSession,
        task_name: str,
        select_related_task: bool = False,
    ) -> list[TaskHistory]:
        """List task histories by the task's name.

        Parameters
        ----------
        session : AsyncSession
            The SQLAlchemy asynchronous session to use for query execution.
        task_name : str
            The name of the task to list histories for.
        select_related_task : bool, optional
            Whether to include the related task data in the result. Defaults to False.

        Returns
        -------
        list[TaskHistory]
            A list of task histories for the specified task.

        """
        query = select(TaskHistory).join(Task)
        select_related = (TaskHistory.task,) if select_related_task else ()
        query = cls._filter_query(
            query,
            col(Task.name) == task_name,
            select_related=select_related,
        )
        result = await cls._exec(session, query)
        return list(result.all())
