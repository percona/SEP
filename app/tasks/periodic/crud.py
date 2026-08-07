# Copyright (C) 2026 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Define database operations for periodic tasks in the Tasks app."""

import logging
from collections.abc import Sequence
from typing import Any

from sqlalchemy.sql._typing import _ColumnExpressionArgument, ColumnExpressionArgument
from sqlalchemy_celery_beat import PeriodicTask
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.sql._expression_select_cls import Select, SelectOfScalar

from app.core.celery.crud import BasePeriodicTaskManager
from app.core.config import settings
from app.core.db.utils import func_json_extract

logger = logging.getLogger(__name__)


class PeriodicTaskManager(BasePeriodicTaskManager):
    """Manage periodic tasks operations for "execute_task_by_name" tasks.

    This class overrides `BasePeriodicTaskManager` to make sure the `task` is always
    `"app.tasks.celery.execute_task_by_name"` on save and select.

    :ivar Model: The SQLAlchemy class this manager is responsible for (`PeriodicTask`).
    :vartype Model: type[PeriodicTask]
    :cvar ordering: The default ordering for listing periodic tasks. `PeriodicTask`
        is not a `BaseSQLModel`, so `BaseManager._get_ordering()` has no
        `created_at` fallback to offer and would leave SELECTs unordered, making
        offset pagination undefined. The primary key is unique, so ordering by it
        alone is total and needs no tie-breaker. Business-meaningful ordering is
        SEP-304.
    :vartype ordering: list[ColumnExpressionOrStrLabelArgument]
    """

    ordering = [col(PeriodicTask.id)]

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
