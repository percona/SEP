"""Define database operations for the Tasks API."""

from collections.abc import Sequence
from datetime import datetime, UTC
from typing import Any

from sqlalchemy import func
from sqlalchemy.sql._typing import _ColumnExpressionArgument
from sqlalchemy_celery_beat import PeriodicTask
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.sql._expression_select_cls import Select, SelectOfScalar

from app.core.auth.exceptions import HTTPForbiddenException
from app.core.celery.crud import BasePeriodicTaskManager
from app.core.config import settings
from app.core.db.crud import BaseSQLModelManager
from app.tasks.models import (
    Task,
    TaskHistory,
    TaskHistoryStatusEnum,
)


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
        *,
        session: AsyncSession,
        owner: str | None = None,
    ) -> list[Task]:
        """List all active (non-deleted) tasks.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        :param owner: The owner of the tasks. If provided, only tasks for this owner
            will be listed.
        :type owner: str | None
        :return: A list of active tasks.
        :rtype: list[Task]
        """
        if owner == "*":
            return await cls.list(
                session,
                col(Task.deleted_at).is_(None),
                col(Task.owner).is_(None),
            )
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

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        :param name: The name of the task to retrieve.
        :type name: str
        :param is_template: Whether the task should be a template or not.
            Use None to not use the filter. Defaults to None.
        :type is_template: bool | None
        :return: The task with the given name.
        :rtype: Task
        :raises HTTPNotFoundException: If no task with the given name is found.
        """
        return await cls.get_or_404(session, name=name, is_template=is_template)

    @classmethod
    async def delete_by_name(cls, *, session: AsyncSession, name: str) -> Task:
        """Delete a task by its name, marking it as deleted.

        If the task is protected, a forbidden exception will be raised.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        :param name: The name of the task to delete.
        :type name: str
        :return: The deleted task.
        :rtype: Task
        :raises HTTPForbiddenException: If the task is protected and cannot be deleted.
        """
        task = await cls.retrieve_by_name(session=session, name=name)
        if task.protected:
            raise HTTPForbiddenException(
                f"Task {name} is protected and cannot be deleted.",
            )
        task.deleted_at = datetime.now(UTC)
        return await cls.save(session, task)


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


class PeriodicTaskManager(BasePeriodicTaskManager):
    """Manage periodic tasks operations for "execute_task_by_name" tasks.

    This class overrides `BasePeriodicTaskManager` to make sure the `task` is always
    `"app.tasks.celery.execute_task_by_name"` on save and select.

    :ivar Model: The SQLAlchemy class this manager is responsible for (`PeriodicTask`).
    :vartype Model: type[PeriodicTask]
    """

    @classmethod
    def _filter_query(
        cls,
        query: Select | SelectOfScalar,
        *whereclause: _ColumnExpressionArgument[bool],
        select_related: Sequence = (),
        **equal_filters: Any,
    ) -> Select | SelectOfScalar:
        equal_filters["task"] = "app.tasks.celery.execute_task_by_name"
        return super()._filter_query(
            query, *whereclause, select_related=select_related, **equal_filters
        )

    @classmethod
    async def save(
        cls,
        session: AsyncSession,
        instance: PeriodicTask,
        *,
        flag_modified_fields: Sequence[str] = (),
    ) -> PeriodicTask:
        """Save a PeriodicTask instance to the database.

        This method overrides `BasePeriodicTaskManager.save()` to make sure the
        associated `task` is always `"app.tasks.celery.execute_task_by_name"`.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param instance: The model instance to be saved.
        :type instance: PeriodicTask
        :param flag_modified_fields: Fields to be flagged as modified before saving.
        :type flag_modified_fields: Sequence[str]
        :return: The saved instance.
        :rtype: PeriodicTask
        :raises HTTPConflictException: If an integrity error occurs during commit.
        """
        instance.task = "app.tasks.celery.execute_task_by_name"
        return await super().save(
            session, instance, flag_modified_fields=flag_modified_fields
        )

    @classmethod
    async def list_by_task_names(
        cls, session: AsyncSession, *task_names: str
    ) -> list[PeriodicTask]:
        """List periodic tasks by the tasks names.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        :param task_names: The names of the tasks to list periodic tasks for.
        :type task_names: str
        :return: A list of periodic tasks for the specified task.
        :rtype: list[PeriodicTask]
        """
        if settings.CELERY.beat_dburi.startswith("postgresql"):
            where = func.json_extract_path_text(
                col(PeriodicTask.kwargs), "task_name"
            ).in_(task_names)
        else:
            where = func.json_extract(col(PeriodicTask.kwargs), "$.task_name").in_(
                task_names
            )
        return await super().list(session, where)
