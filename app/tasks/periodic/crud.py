"""Define database operations for periodic tasks in the Tasks app."""

import logging
from collections.abc import Sequence
from typing import Any

from sqlalchemy import CursorResult
from sqlalchemy.sql._typing import ColumnExpressionArgument
from sqlalchemy_celery_beat import PeriodicTask
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.sql._expression_select_cls import Select, SelectOfScalar

from app.core.celery.crud import BasePeriodicTaskManager
from app.core.config import settings
from app.core.db.utils import func_json_extract
from app.core.utils.date_time import utc_now
from app.tasks.periodic.config import periodic_tasks_settings, PeriodicTaskAction

logger = logging.getLogger(__name__)


class PeriodicTaskManager(BasePeriodicTaskManager):
    """Manage periodic tasks operations for "execute_task_by_name" tasks.

    This class overrides `BasePeriodicTaskManager` to make sure the `task` is always
    `"app.tasks.celery.execute_task_by_name"` on save and select.

    :ivar Model: The SQLAlchemy class this manager is responsible for (`PeriodicTask`).
    :vartype Model: type[PeriodicTask]
    """

    @classmethod
    async def _perform_action_where(
        cls,
        session: AsyncSession,
        action: PeriodicTaskAction,
        *whereclause: ColumnExpressionArgument[bool],
        **equal_filters: Any,
    ) -> CursorResult | None:
        if action == PeriodicTaskAction.NOTHING:
            return None
        if action == PeriodicTaskAction.DELETE:
            return await cls.delete_where(session, *whereclause, **equal_filters)
        if action == PeriodicTaskAction.DISABLE:
            equal_filters["enabled"] = True
            return await cls.update_where(
                session, {"enabled": False}, *whereclause, **equal_filters
            )
        raise ValueError(f"Unknown action {action!r}")

    @classmethod
    def _filter_query(
        cls,
        query: Select | SelectOfScalar,
        *whereclause: ColumnExpressionArgument[bool],
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
        cls,
        session: AsyncSession,
        *task_names: str,
        **equal_filters: Any,
    ) -> list[PeriodicTask]:
        """List periodic tasks by the tasks names.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        :param task_names: The names of the tasks to list periodic tasks for.
        :type task_names: str
        :param equal_filters: Additional filters as column=value pairs; ignored if value is None.
        :type equal_filters: Any
        :return: A list of periodic tasks for the specified task.
        :rtype: list[PeriodicTask]
        """
        return await super().list(
            session, cls.build_where_clause_by_task_names(*task_names), **equal_filters
        )

    @classmethod
    async def process_expired(cls, session: AsyncSession) -> None:
        """Perform periodic_tasks_settings.ON_EXPIRE to expired periodic tasks.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        """
        action = periodic_tasks_settings.ON_EXPIRE
        result = await cls._perform_action_where(
            session, action, PeriodicTask.expires <= utc_now()
        )
        if result is not None:
            if result.rowcount:
                logger.info(
                    "%s %s expired periodic tasks",
                    f"{action.capitalize()}d",
                    result.rowcount,
                )
            else:
                logger.debug(
                    "ON_EXPIRE is %s but no expired periodic task found", action
                )

    @classmethod
    async def perform_action_by_task_names(
        cls, session: AsyncSession, action: PeriodicTaskAction, *task_names: str
    ) -> None:
        """Perform a PeriodicTaskAction to tasks with the specified names.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        :param action: The periodic action to perform.
        :type action: PeriodicTaskAction
        :param task_names: The names of the tasks to filter the periodic tasks
            to perform the actions.
        :type task_names: str
        """
        await cls.perform_action_where(
            session, action, cls.build_where_clause_by_task_names(*task_names)
        )

    @classmethod
    async def perform_action_where(
        cls,
        session: AsyncSession,
        action: PeriodicTaskAction,
        *whereclause: ColumnExpressionArgument[bool],
        **equal_filters: Any,
    ) -> None:
        """Perform a PeriodicTaskAction to tasks that match the specified filters.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        :param action: The periodic action to perform.
        :type action: PeriodicTaskAction
        :param whereclause: SQL expressions for the `where` clause of the query.
        :type whereclause: ColumnExpressionArgument[bool]
        :param equal_filters: Keyword arguments representing column names and their
            respective filter values.
        :type equal_filters: Any
        """
        result = await cls._perform_action_where(
            session, action, *whereclause, **equal_filters
        )
        if action == PeriodicTaskAction.NOTHING:
            logger.debug("action is NOTHING")
        elif result is not None:
            if result.rowcount:
                logger.info(
                    "%s %s periodic tasks", f"{action.capitalize()}d", result.rowcount
                )
            else:
                logger.debug(
                    "action is %r but no task found with specified filters", action
                )

    @staticmethod
    def build_where_clause_by_task_names(
        *task_names: str,
    ) -> ColumnExpressionArgument[bool]:
        """Build and return a WHERE clause that matches periodic tasks by task names.

        :param task_names: The names of the tasks to filter the periodic tasks.
        :type task_names: str
        """
        return func_json_extract(
            settings.CELERY.beat_dburi, PeriodicTask.kwargs, "task_name"
        ).in_(task_names)
