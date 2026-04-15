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

"""Define database operations for the Tasks API."""

import logging
from collections.abc import AsyncGenerator, Sequence
from datetime import datetime

from sqlalchemy import CursorResult, func, literal, update
from sqlalchemy.orm import aliased
from sqlmodel import and_, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth.exceptions import HTTPForbiddenException
from app.core.db.crud import (
    BaseManager,
    BaseSQLModelManager,
    DEFAULT_PAGINATION_LIMIT,
    DEFAULT_PAGINATION_OFFSET,
)
from app.core.db.utils import func_json_extract, idempotent_insert
from app.core.exceptions import HTTPConflictException
from app.core.models import PaginatedResponse
from app.core.utils.date_time import utc_now
from app.tasks.models import (
    DispatchLock,
    Task,
    TaskBackendEnum,
    TaskHistory,
    TaskHistoryLog,
    TaskHistoryLogState,
    TaskHistoryStatusEnum,
    TaskLogType,
    TaskOwner,
)

logger = logging.getLogger(__name__)


class TaskManager(BaseSQLModelManager):
    """Manage task operations, including retrieval, listing, and deletion.

    This class provides methods to interact with ``Task`` models in the database,
    such as listing active tasks, retrieving tasks by name, and deleting tasks.

    :ivar Model: The SQLModel class this manager is responsible for (``Task``).
    :vartype Model: type[Task]
    """

    Model = Task

    @classmethod
    async def list_active(
        cls,
        session: AsyncSession,
        owner: TaskOwner | None = None,
        target: str | None = None,
    ) -> list[Task]:
        """List all active (non-deleted) tasks.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        :param owner: The owner of the tasks. If provided, only tasks for this owner
            will be listed.
        :type owner: TaskOwner | None
        :param target: The execution target hostname. If provided, only tasks whose
            ``data["meta"]["target"]`` matches will be listed.
        :type target: str | None
        :return: A list of active tasks.
        :rtype: list[Task]
        """
        where = [col(Task.deleted_at).is_(None)]
        kwargs = {}
        if owner is not None:
            kwargs["owner"] = owner
        if target is not None:
            where.append(Task.data["meta"]["target"].as_string() == target)
        return await cls.list(session, *where, **kwargs)

    @classmethod
    async def list_active_paginated(
        cls,
        session: AsyncSession,
        owner: TaskOwner | None = None,
        target: str | None = None,
        offset: int = DEFAULT_PAGINATION_OFFSET,
        limit: int = DEFAULT_PAGINATION_LIMIT,
    ) -> PaginatedResponse[Task]:
        """Return a paginated response of active (non-deleted) tasks.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        :param owner: The owner of the tasks. If provided, only tasks for this owner
            will be listed.
        :type owner: TaskOwner | None
        :param target: The execution target hostname. If provided, only tasks whose
            ``data["meta"]["target"]`` matches will be listed.
        :type target: str | None
        :param offset: The zero-based starting offset for the query results.
        :type offset: int
        :param limit: The maximum number of records to return.
        :type limit: int
        :return: A paginated response containing active tasks and metadata.
        :rtype: PaginatedResponse[Task]
        """
        where = [col(Task.deleted_at).is_(None)]
        kwargs = {}
        if owner is not None:
            kwargs["owner"] = owner
        if target is not None:
            where.append(Task.data["meta"]["target"].as_string() == target)
        return await cls.list_paginated(
            session, *where, offset=offset, limit=limit, **kwargs
        )

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
    async def delete_unattached_system_tasks(
        cls, session: AsyncSession, exclude_task_names: Sequence[str]
    ) -> CursorResult:
        """Delete unattached system tasks that are not in the provided sequence.

        This method identifies system tasks that are not attached to any task history
        and are not in the provided sequence of task names. It then deletes these tasks.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        :param exclude_task_names: A sequence of task names to exclude from deletion.
        :type exclude_task_names: Sequence[str]
        :return: The result of the delete operation.
        :rtype: CursorResult
        """
        proxy_task = aliased(Task)
        query = (
            select(Task)
            .join(TaskHistory, isouter=True)
            .join(
                proxy_task,
                and_(
                    col(proxy_task.backend) == TaskBackendEnum.PROXY,
                    func_json_extract(session.get_bind().name, proxy_task.data, "task")
                    == col(Task.name),
                    col(proxy_task.id) != col(Task.id),
                ),
                isouter=True,
            )
        )
        query = TaskManager._filter_query(
            query,
            col(Task.name).not_in(exclude_task_names),
            col(Task.protected).is_(True),
            col(TaskHistory.task_id).is_(None),
            col(proxy_task.id).is_(None),
        )
        result = await TaskManager._exec(session, query)
        tasks_ids_to_delete = [task.id for task in result.unique().all()]
        return await TaskManager.delete_where(
            session, col(Task.id).in_(tasks_ids_to_delete)
        )

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

    :ivar Model: The SQLModel class this manager is responsible for (``TaskHistory``).
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
        snippet_filename: str | None = None,
        select_related_task: bool = False,
        offset: int | None = None,
        limit: int | None = None,
        query_options: Sequence = (),
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
        :param snippet_filename: If provided, filter task histories by the specified
            snippet filename in the task's metadata.
        :type snippet_filename: str | None
        :param offset: The zero-based starting offset, or ``None`` to skip offset.
        :type offset: int | None
        :param limit: The maximum number of records, or ``None`` for no limit.
        :type limit: int | None
        :param query_options: Additional SQLAlchemy query options to apply.
        :type query_options: Sequence
        :return: A list of task histories for the specified task.
        :rtype: list[TaskHistory]
        """
        query = select(TaskHistory).join(Task)
        clauses = [col(Task.name) == task_name]
        if snippet_filename:
            clauses.append(
                func_json_extract(
                    session.get_bind().name,
                    col(TaskHistory.execution_request),
                    "meta",
                    "_snippet_filename",
                )
                == snippet_filename
            )
        select_related = (TaskHistory.task,) if select_related_task else ()
        query = cls._filter_query(
            query,
            *clauses,
            select_related=select_related,
            query_options=query_options,
            status=status,
        )
        ordering = cls._get_ordering()
        if ordering:
            query = query.order_by(*ordering)
        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        result = await cls._exec(session, query)
        return list(result.all())

    @classmethod
    async def list_by_task_name_paginated(
        cls,
        *,
        session: AsyncSession,
        task_name: str,
        status: TaskHistoryStatusEnum | None = None,
        snippet_filename: str | None = None,
        select_related_task: bool = False,
        offset: int = DEFAULT_PAGINATION_OFFSET,
        limit: int = DEFAULT_PAGINATION_LIMIT,
        query_options: Sequence = (),
    ) -> PaginatedResponse[TaskHistory]:
        """Return a paginated response of task histories by the task's name.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        :param task_name: The name of the task to list histories for.
        :type task_name: str
        :param status: The status of the task history. If provided, only histories
            with this status will be listed.
        :type status: TaskHistoryStatusEnum | None
        :param snippet_filename: If provided, filter task histories by the specified
            snippet filename in the task's metadata.
        :type snippet_filename: str | None
        :param select_related_task: Whether to include the related task data in the
            result. Defaults to False.
        :type select_related_task: bool
        :param offset: The zero-based starting offset for the query results.
        :type offset: int
        :param limit: The maximum number of records to return.
        :type limit: int
        :param query_options: Additional SQLAlchemy query options to apply.
        :type query_options: Sequence
        :return: A paginated response containing task histories and metadata.
        :rtype: PaginatedResponse[TaskHistory]
        """
        cls._validate_pagination(offset, limit)
        count_query = select(func.count()).select_from(TaskHistory).join(Task)
        count_clauses = [col(Task.name) == task_name]
        if snippet_filename:
            count_clauses.append(
                func_json_extract(
                    session.get_bind().name,
                    col(TaskHistory.execution_request),
                    "meta",
                    "_snippet_filename",
                )
                == snippet_filename
            )
        count_query = cls._filter_query(count_query, *count_clauses, status=status)
        total = await session.scalar(count_query) or 0
        items = await cls.list_by_task_name(
            session=session,
            task_name=task_name,
            status=status,
            snippet_filename=snippet_filename,
            select_related_task=select_related_task,
            offset=offset,
            limit=limit,
            query_options=query_options,
        )
        return PaginatedResponse(
            items=items,
            total=total,
            offset=offset,
            limit=limit,
        )


class TaskHistoryLogManager(BaseSQLModelManager):
    """Manage append-only task history log chunk operations.

    :ivar Model: The SQLModel class this manager is responsible for
        (``TaskHistoryLog``).
    :vartype Model: type[TaskHistoryLog]
    """

    Model = TaskHistoryLog
    ordering = None

    @classmethod
    async def exists_for_task(cls, session: AsyncSession, task_history_id: int) -> bool:
        """Return ``True`` when at least one chunk exists for the task history.

        Uses a ``SELECT 1 ... LIMIT 1`` short-circuit query so the database
        can stop scanning as soon as it finds the first matching row instead
        of counting every chunk.

        :param session: The SQLAlchemy asynchronous session to use for query
            execution.
        :type session: AsyncSession
        :param task_history_id: The ``TaskHistory`` identifier.
        :type task_history_id: int
        :return: Whether any chunk rows exist for the task history.
        :rtype: bool
        """
        query = (
            select(literal(1))
            .where(col(TaskHistoryLog.task_history_id) == task_history_id)
            .limit(1)
        )
        result = await session.execute(query)
        return result.first() is not None

    @classmethod
    async def list_chunks_for_task(
        cls,
        session: AsyncSession,
        task_history_id: int,
    ) -> list[TaskHistoryLog]:
        """Return every chunk row for a task history eagerly, ordered for readback.

        Eager helper intended for tests and one-shot admin tooling; the
        streaming :meth:`iter_chunks` remains the API for production readers.
        Rows are returned in ``(source, stream, start_offset)`` order.

        :param session: The SQLAlchemy asynchronous session to use for query
            execution.
        :type session: AsyncSession
        :param task_history_id: The ``TaskHistory`` identifier.
        :type task_history_id: int
        :return: A list of chunk rows for the task history, oldest first.
        :rtype: list[TaskHistoryLog]
        """
        query = (
            select(TaskHistoryLog)
            .where(col(TaskHistoryLog.task_history_id) == task_history_id)
            .order_by(
                col(TaskHistoryLog.source),
                col(TaskHistoryLog.stream),
                col(TaskHistoryLog.start_offset),
            )
        )
        result = await cls._exec(session, query)
        return list(result.all())

    @classmethod
    async def iter_chunks(
        cls,
        session: AsyncSession,
        task_history_id: int,
        *,
        source: str | None = None,
    ) -> AsyncGenerator[TaskHistoryLog, None]:
        """Yield chunk rows in ``(source, stream, start_offset)`` order.

        :param session: The SQLAlchemy asynchronous session to use for query
            execution.
        :type session: AsyncSession
        :param task_history_id: The ``TaskHistory`` identifier.
        :type task_history_id: int
        :param source: Optional step filter; when set, only chunks for the given
            source are yielded.
        :type source: str | None
        :return: An async generator yielding matching ``TaskHistoryLog`` chunk
            rows, oldest first.
        :rtype: AsyncGenerator[TaskHistoryLog, None]
        """
        query = select(TaskHistoryLog).where(
            col(TaskHistoryLog.task_history_id) == task_history_id,
        )
        if source is not None:
            query = query.where(col(TaskHistoryLog.source) == source)
        query = query.order_by(
            col(TaskHistoryLog.source),
            col(TaskHistoryLog.stream),
            col(TaskHistoryLog.start_offset),
        ).execution_options(yield_per=50)
        result = await session.stream(query)
        async for row in result.scalars():
            yield row

    @classmethod
    async def insert_chunk_idempotent(
        cls,
        session: AsyncSession,
        *,
        task_history_id: int,
        source: str,
        stream: TaskLogType,
        start_offset: int,
        chunk: bytes,
        now: datetime,
    ) -> None:
        """Insert a log chunk row, dropping duplicates on conflict.

        Uses the dialect-specific ``INSERT ... ON CONFLICT DO NOTHING`` helper
        so the call is safe to retry — duplicate
        ``(task_history_id, source, stream, start_offset)`` keys are dropped by
        the database without raising.

        :param session: The SQLAlchemy asynchronous session to use for query
            execution.
        :type session: AsyncSession
        :param task_history_id: The ``TaskHistory`` identifier.
        :type task_history_id: int
        :param source: The execution step name.
        :type source: str
        :param stream: The log stream (stdout or stderr).
        :type stream: TaskLogType
        :param start_offset: The user-facing byte offset at which the chunk
            starts.
        :type start_offset: int
        :param chunk: The raw bytes to persist.
        :type chunk: bytes
        :param now: The insertion timestamp used for ``created_at``.
        :type now: datetime
        """
        stmt = idempotent_insert(session.get_bind().name, TaskHistoryLog).values(
            task_history_id=task_history_id,
            source=source,
            stream=stream,
            start_offset=start_offset,
            end_offset=start_offset + len(chunk),
            content=chunk.decode("utf-8", errors="replace"),
            created_at=now,
        )
        await session.execute(stmt)


class TaskHistoryLogStateManager(BaseManager):
    """Manage per-stream log staging state rows.

    :ivar Model: The SQLModel class this manager is responsible for
        (``TaskHistoryLogState``).
    :vartype Model: type[TaskHistoryLogState]
    """

    Model = TaskHistoryLogState

    @classmethod
    async def get_for_stream(
        cls,
        session: AsyncSession,
        task_history_id: int,
        source: str,
        stream: TaskLogType,
    ) -> TaskHistoryLogState | None:
        """Return the state row for a single ``(task_history_id, source, stream)`` tuple.

        :param session: The SQLAlchemy asynchronous session to use for query
            execution.
        :type session: AsyncSession
        :param task_history_id: The ``TaskHistory`` identifier.
        :type task_history_id: int
        :param source: The execution step name.
        :type source: str
        :param stream: The log stream (stdout or stderr).
        :type stream: TaskLogType
        :return: The existing state row, or ``None`` when it does not exist yet.
        :rtype: TaskHistoryLogState | None
        """
        query = select(TaskHistoryLogState).where(
            col(TaskHistoryLogState.task_history_id) == task_history_id,
            col(TaskHistoryLogState.source) == source,
            col(TaskHistoryLogState.stream) == stream,
        )
        result = await cls._exec(session, query)
        return result.first()

    @classmethod
    def build_default(
        cls,
        task_history_id: int,
        source: str,
        stream: TaskLogType,
    ) -> TaskHistoryLogState:
        """Return a transient zero-offset state row with an empty staging buffer.

        The returned instance is detached and has ``version=0``; callers use it
        as the starting point for an INSERT when no row exists yet.

        :param task_history_id: The ``TaskHistory`` identifier.
        :type task_history_id: int
        :param source: The execution step name.
        :type source: str
        :param stream: The log stream (stdout or stderr).
        :type stream: TaskLogType
        :return: A transient ``TaskHistoryLogState`` instance with default values.
        :rtype: TaskHistoryLogState
        """
        return TaskHistoryLogState(
            task_history_id=task_history_id,
            source=source,
            stream=stream,
            persisted_offset=0,
            producer_offset=0,
            staging=b"",
            staging_updated_at=utc_now(),
            version=0,
        )

    @classmethod
    async def list_for_task(
        cls, session: AsyncSession, task_history_id: int
    ) -> list[TaskHistoryLogState]:
        """Return every state row attached to the given task history.

        :param session: The SQLAlchemy asynchronous session to use for query
            execution.
        :type session: AsyncSession
        :param task_history_id: The ``TaskHistory`` identifier.
        :type task_history_id: int
        :return: A list of state rows for the task history.
        :rtype: list[TaskHistoryLogState]
        """
        query = select(TaskHistoryLogState).where(
            col(TaskHistoryLogState.task_history_id) == task_history_id,
        )
        result = await cls._exec(session, query)
        return list(result.all())

    @classmethod
    async def reset_producer_offsets(
        cls, session: AsyncSession, task_history_id: int
    ) -> None:
        """Set ``producer_offset`` to ``0`` for every stream of a task history.

        Called when Nomad reschedules a task to a follow-up allocation: the
        new allocation's log file starts at byte 0, so any cached
        ``producer_offset`` from the previous allocation must be cleared in
        the database before the writer dedups based on it. Bumps ``version``
        so concurrent writers re-read the row.

        :param session: The SQLAlchemy asynchronous session.
        :type session: AsyncSession
        :param task_history_id: The ``TaskHistory`` identifier whose state
            rows should be reset.
        :type task_history_id: int
        """
        stmt = (
            update(TaskHistoryLogState)
            .where(col(TaskHistoryLogState.task_history_id) == task_history_id)
            .values(
                producer_offset=0,
                version=col(TaskHistoryLogState.version) + 1,
                updated_at=utc_now(),
            )
        )
        await session.execute(stmt)

    @classmethod
    async def insert_row_idempotent(
        cls,
        session: AsyncSession,
        *,
        task_history_id: int,
        source: str,
        stream: TaskLogType,
        persisted_offset: int,
        producer_offset: int,
        staging: bytes,
        version: int,
        now: datetime,
    ) -> bool:
        """Insert a new state row, returning ``True`` on a successful insert.

        Uses ``INSERT ... ON CONFLICT DO NOTHING`` so a concurrent writer that
        already created the row causes this call to return ``False`` instead of
        raising.

        :param session: The SQLAlchemy asynchronous session to use for query
            execution.
        :type session: AsyncSession
        :param task_history_id: The ``TaskHistory`` identifier.
        :type task_history_id: int
        :param source: The execution step name.
        :type source: str
        :param stream: The log stream (stdout or stderr).
        :type stream: TaskLogType
        :param persisted_offset: The user-facing byte offset already persisted.
        :type persisted_offset: int
        :param producer_offset: The producer-relative byte offset already
            consumed from the current allocation.
        :type producer_offset: int
        :param staging: Bytes pending flush to the chunk store.
        :type staging: bytes
        :param version: The initial optimistic-locking version counter.
        :type version: int
        :param now: The insertion timestamp used for audit columns.
        :type now: datetime
        :return: ``True`` when a row was inserted; ``False`` when the row
            already existed.
        :rtype: bool
        """
        stmt = idempotent_insert(session.get_bind().name, TaskHistoryLogState).values(
            task_history_id=task_history_id,
            source=source,
            stream=stream,
            persisted_offset=persisted_offset,
            producer_offset=producer_offset,
            staging=staging,
            staging_updated_at=now,
            version=version,
            created_at=now,
        )
        result = await session.execute(stmt)
        return bool(result.rowcount == 1)

    @classmethod
    async def update_row_if_version(
        cls,
        session: AsyncSession,
        *,
        task_history_id: int,
        source: str,
        stream: TaskLogType,
        old_version: int,
        new_version: int,
        persisted_offset: int,
        producer_offset: int,
        staging: bytes,
        now: datetime,
    ) -> bool:
        """Update a state row conditioned on the old version and return whether we won.

        Implements optimistic locking: the update matches only when the row's
        ``version`` column still equals ``old_version``. A concurrent writer
        that already bumped the version causes ``rowcount`` to be ``0`` and this
        method returns ``False`` so the caller can retry.

        :param session: The SQLAlchemy asynchronous session to use for query
            execution.
        :type session: AsyncSession
        :param task_history_id: The ``TaskHistory`` identifier.
        :type task_history_id: int
        :param source: The execution step name.
        :type source: str
        :param stream: The log stream (stdout or stderr).
        :type stream: TaskLogType
        :param old_version: The version the caller read from the state row.
        :type old_version: int
        :param new_version: The bumped version to write.
        :type new_version: int
        :param persisted_offset: The updated user-facing persisted offset.
        :type persisted_offset: int
        :param producer_offset: The updated producer-relative offset.
        :type producer_offset: int
        :param staging: The updated staging bytes buffer.
        :type staging: bytes
        :param now: The update timestamp used for the audit columns.
        :type now: datetime
        :return: ``True`` when exactly one row was updated; ``False`` when the
            optimistic-locking guard prevented the write.
        :rtype: bool
        """
        stmt = (
            update(TaskHistoryLogState)
            .where(
                col(TaskHistoryLogState.task_history_id) == task_history_id,
                col(TaskHistoryLogState.source) == source,
                col(TaskHistoryLogState.stream) == stream,
                col(TaskHistoryLogState.version) == old_version,
            )
            .values(
                persisted_offset=persisted_offset,
                producer_offset=producer_offset,
                staging=staging,
                staging_updated_at=now,
                version=new_version,
                updated_at=now,
            )
        )
        result = await session.execute(stmt)
        return bool(result.rowcount == 1)


class DispatchLockManager(BaseSQLModelManager):
    """Manage dispatch lock operations.

    :ivar Model: The SQLModel class this manager is responsible for (``DispatchLock``).
    :vartype Model: type[DispatchLock]
    """

    Model = DispatchLock
