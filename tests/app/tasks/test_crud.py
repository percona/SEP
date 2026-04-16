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

"""Define tests for the Tasks CRUD managers."""

import pytest
import pytest_asyncio
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth.exceptions import HTTPForbiddenException
from app.core.db.crud import DEFAULT_PAGINATION_LIMIT, DEFAULT_PAGINATION_OFFSET
from app.core.exceptions import HTTPConflictException, HTTPNotFoundException
from app.tasks.crud import DispatchLockManager, TaskHistoryManager, TaskManager
from app.tasks.models import (
    DispatchLock,
    Task,
    TaskBackendEnum,
    TaskHistory,
    TaskHistoryStatusEnum,
    TaskOwner,
    TaskWrite,
)
from tests.app.factories import TaskFactory

HISTORY_FIXTURE_COUNT = 3
PAGINATED_TASK_COUNT = 2
PAGINATED_CUSTOM_TASK_COUNT = 3


async def _create_task(
    session: AsyncSession,
    *,
    name: str = "test-task",
    owner: TaskOwner = TaskOwner.ANY,
    is_template: bool = False,
    protected: bool = False,
    backend: TaskBackendEnum = TaskBackendEnum.NOMAD,
    data: dict | None = None,
) -> Task:
    """Create and persist a task with the given attributes.

    :param session: The async database session.
    :type session: AsyncSession
    :param name: The task name.
    :type name: str
    :param owner: The task owner.
    :type owner: TaskOwner
    :param is_template: Whether the task is a template.
    :type is_template: bool
    :param protected: Whether the task is protected.
    :type protected: bool
    :param backend: The task backend.
    :type backend: TaskBackendEnum
    :param data: The task data payload.
    :type data: dict | None
    :return: The persisted task.
    :rtype: Task
    """
    task_data = TaskFactory.build(
        name=name,
        owner=owner,
        is_template=is_template,
        protected=protected,
        backend=backend,
        data=data if data is not None else {"job": "test"},
    )
    return await TaskManager.create(session, TaskWrite.model_validate(task_data))


async def _create_task_history(
    session: AsyncSession,
    task: Task,
    *,
    status: TaskHistoryStatusEnum = TaskHistoryStatusEnum.SUCCESS,
    snippet_filename: str | None = None,
) -> TaskHistory:
    """Create and persist a task history record.

    :param session: The async database session.
    :type session: AsyncSession
    :param task: The parent task.
    :type task: Task
    :param status: The history status.
    :type status: TaskHistoryStatusEnum
    :param snippet_filename: Optional snippet filename in meta.
    :type snippet_filename: str | None
    :return: The persisted task history.
    :rtype: TaskHistory
    """
    meta = {}
    if snippet_filename:
        meta["_snippet_filename"] = snippet_filename
    history = TaskHistory(
        task_id=task.id,
        status=status,
        execution_request={
            "task": task.name,
            "target": "localhost",
            "meta": meta,
            "tracking": {"allocation_id": None, "evaluation_id": None},
        },
    )
    return await TaskHistoryManager.save(session, history)


# ---------------------------------------------------------------------------
# TaskManager.list_active
# ---------------------------------------------------------------------------


class TestTaskManagerListActive:
    """Test TaskManager.list_active."""

    @pytest.mark.asyncio
    async def test_returns_only_non_deleted_tasks(self, session: AsyncSession) -> None:
        """Assert only active (non-deleted) tasks are returned."""
        task = await _create_task(session, name="active-task")
        await _create_task(session, name="to-delete")
        await TaskManager.delete_by_name(session, "to-delete")

        result = await TaskManager.list_active(session)

        assert len(result) == 1
        assert result[0].id == task.id

    @pytest.mark.asyncio
    async def test_with_owner_filter(self, session: AsyncSession) -> None:
        """Assert owner filter restricts returned tasks."""
        await _create_task(session, name="backup-task", owner=TaskOwner.BACKUPS)
        await _create_task(session, name="alter-task", owner=TaskOwner.ALTERS)

        result = await TaskManager.list_active(session, owner=TaskOwner.BACKUPS)

        assert len(result) == 1
        assert result[0].name == "backup-task"

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty_list(self, session: AsyncSession) -> None:
        """Assert empty database returns an empty list."""
        result = await TaskManager.list_active(session)

        assert result == []

    @pytest.mark.asyncio
    async def test_with_target_filter(self, session: AsyncSession) -> None:
        """Assert target filter restricts returned tasks by data.meta.target."""
        await _create_task(
            session,
            name="host1-task",
            data={"meta": {"target": "host1"}},
        )
        await _create_task(
            session,
            name="host2-task",
            data={"meta": {"target": "host2"}},
        )

        result = await TaskManager.list_active(session, target="host1")

        assert len(result) == 1
        assert result[0].name == "host1-task"


# ---------------------------------------------------------------------------
# TaskManager.retrieve_by_name
# ---------------------------------------------------------------------------


class TestTaskManagerRetrieveByName:
    """Test TaskManager.retrieve_by_name."""

    @pytest.mark.asyncio
    async def test_existing_active_task(self, session: AsyncSession) -> None:
        """Assert an existing active task is returned."""
        task = await _create_task(session, name="my-task")

        result = await TaskManager.retrieve_by_name(session, "my-task")

        assert result.id == task.id

    @pytest.mark.asyncio
    async def test_non_existing_name_raises_404(self, session: AsyncSession) -> None:
        """Assert HTTPNotFoundException is raised for a missing task."""
        with pytest.raises(HTTPNotFoundException):
            await TaskManager.retrieve_by_name(session, "no-such-task")

    @pytest.mark.asyncio
    async def test_is_template_filter(self, session: AsyncSession) -> None:
        """Assert is_template filter returns only templates."""
        await _create_task(session, name="regular-task", is_template=False)
        template = await _create_task(session, name="template-task", is_template=True)

        result = await TaskManager.retrieve_by_name(
            session, "template-task", is_template=True
        )
        assert result.id == template.id

        with pytest.raises(HTTPNotFoundException):
            await TaskManager.retrieve_by_name(
                session, "regular-task", is_template=True
            )

    @pytest.mark.asyncio
    async def test_is_active_true_returns_only_active(
        self, session: AsyncSession
    ) -> None:
        """Assert is_active=True returns only non-deleted tasks."""
        task = await _create_task(session, name="alive-task")

        result = await TaskManager.retrieve_by_name(
            session, "alive-task", is_active=True
        )
        assert result.id == task.id

    @pytest.mark.asyncio
    async def test_is_active_false_returns_only_deleted(
        self, session: AsyncSession
    ) -> None:
        """Assert is_active=False returns only deleted tasks."""
        task = await _create_task(session, name="doomed-task")
        deleted = await TaskManager.delete_by_name(session, "doomed-task")

        result = await TaskManager.retrieve_by_name(
            session, deleted.name, is_active=False
        )
        assert result.id == task.id

    @pytest.mark.asyncio
    async def test_is_active_none_returns_both(self, session: AsyncSession) -> None:
        """Assert is_active=None returns both active and deleted tasks."""
        task = await _create_task(session, name="any-task")

        result = await TaskManager.retrieve_by_name(session, "any-task", is_active=None)
        assert result.id == task.id


# ---------------------------------------------------------------------------
# TaskManager.delete_by_name
# ---------------------------------------------------------------------------


class TestTaskManagerDeleteByName:
    """Test TaskManager.delete_by_name."""

    @pytest.mark.asyncio
    async def test_soft_deletes_unprotected_task(self, session: AsyncSession) -> None:
        """Assert an active, unprotected task is soft-deleted."""
        await _create_task(session, name="deletable-task")

        result = await TaskManager.delete_by_name(session, "deletable-task")

        assert result.deleted_at is not None
        assert result.name.startswith("deletable-task-")

    @pytest.mark.asyncio
    async def test_protected_task_raises_403(self, session: AsyncSession) -> None:
        """Assert deleting a protected task raises HTTPForbiddenException."""
        await _create_task(session, name="protected-task", protected=True)

        with pytest.raises(HTTPForbiddenException):
            await TaskManager.delete_by_name(session, "protected-task")

    @pytest.mark.asyncio
    async def test_running_task_raises_409(self, session: AsyncSession) -> None:
        """Assert deleting a task with running history raises HTTPConflictException."""
        task = await _create_task(session, name="running-task")
        await _create_task_history(session, task, status=TaskHistoryStatusEnum.RUNNING)

        with pytest.raises(HTTPConflictException):
            await TaskManager.delete_by_name(session, "running-task")

    @pytest.mark.asyncio
    async def test_pending_task_raises_409(self, session: AsyncSession) -> None:
        """Assert deleting a task with pending history raises HTTPConflictException."""
        task = await _create_task(session, name="pending-task")
        await _create_task_history(session, task, status=TaskHistoryStatusEnum.PENDING)

        with pytest.raises(HTTPConflictException):
            await TaskManager.delete_by_name(session, "pending-task")

    @pytest.mark.asyncio
    async def test_non_existing_task_raises_404(self, session: AsyncSession) -> None:
        """Assert deleting a non-existing task raises HTTPNotFoundException."""
        with pytest.raises(HTTPNotFoundException):
            await TaskManager.delete_by_name(session, "ghost-task")


# ---------------------------------------------------------------------------
# TaskManager.delete_unattached_system_tasks
# ---------------------------------------------------------------------------


class TestTaskManagerDeleteUnattachedSystemTasks:
    """Test TaskManager.delete_unattached_system_tasks."""

    @pytest.mark.asyncio
    async def test_deletes_unattached_protected_tasks(
        self, session: AsyncSession
    ) -> None:
        """Assert unattached protected tasks without history or proxy refs are deleted."""
        unattached = await _create_task(session, name="orphan-system", protected=True)

        await TaskManager.delete_unattached_system_tasks(session, [])

        remaining = await TaskManager.list(session)
        remaining_ids = [t.id for t in remaining]
        assert unattached.id not in remaining_ids

    @pytest.mark.asyncio
    async def test_keeps_tasks_with_history(self, session: AsyncSession) -> None:
        """Assert tasks with history are not deleted."""
        task = await _create_task(session, name="has-history", protected=True)
        await _create_task_history(session, task)

        await TaskManager.delete_unattached_system_tasks(session, [])

        remaining = await TaskManager.list(session)
        assert any(t.id == task.id for t in remaining)

    @pytest.mark.asyncio
    async def test_keeps_tasks_referenced_by_proxy(self, session: AsyncSession) -> None:
        """Assert tasks referenced by a proxy task are not deleted."""
        target = await _create_task(session, name="target-task", protected=True)
        await _create_task(
            session,
            name="proxy-task",
            backend=TaskBackendEnum.PROXY,
            data={"task": "target-task"},
            protected=False,
        )

        await TaskManager.delete_unattached_system_tasks(session, [])

        remaining = await TaskManager.list(session)
        assert any(t.id == target.id for t in remaining)

    @pytest.mark.asyncio
    async def test_keeps_excluded_tasks(self, session: AsyncSession) -> None:
        """Assert tasks in the exclude list are not deleted."""
        task = await _create_task(session, name="excluded-task", protected=True)

        await TaskManager.delete_unattached_system_tasks(session, ["excluded-task"])

        remaining = await TaskManager.list(session)
        assert any(t.id == task.id for t in remaining)

    @pytest.mark.asyncio
    async def test_skips_unprotected_tasks(self, session: AsyncSession) -> None:
        """Assert unprotected tasks are not deleted by this method."""
        task = await _create_task(session, name="unprotected-task", protected=False)

        await TaskManager.delete_unattached_system_tasks(session, [])

        remaining = await TaskManager.list(session)
        assert any(t.id == task.id for t in remaining)


# ---------------------------------------------------------------------------
# TaskManager.get_root_task
# ---------------------------------------------------------------------------


class TestTaskManagerGetRootTask:
    """Test TaskManager.get_root_task."""

    @pytest.mark.asyncio
    async def test_proxy_backend_returns_target_task(
        self, session: AsyncSession
    ) -> None:
        """Assert proxy task resolves to its target task."""
        target = await _create_task(session, name="real-task")
        proxy = await _create_task(
            session,
            name="proxy-ref",
            backend=TaskBackendEnum.PROXY,
            data={"task": "real-task"},
        )

        result = await TaskManager.get_root_task(session, proxy)

        assert result.id == target.id

    @pytest.mark.asyncio
    async def test_nomad_backend_returns_same_task(self, session: AsyncSession) -> None:
        """Assert a NOMAD task returns itself as the root task."""
        task = await _create_task(session, name="nomad-task")

        result = await TaskManager.get_root_task(session, task)

        assert result.id == task.id


# ---------------------------------------------------------------------------
# TaskHistoryManager.list_by_task_name
# ---------------------------------------------------------------------------


class TestTaskHistoryManagerListByTaskName:
    """Test TaskHistoryManager.list_by_task_name."""

    @pytest_asyncio.fixture
    async def task_with_histories(self, session: AsyncSession) -> Task:
        """Create a task with multiple history records.

        :param session: The async database session.
        :type session: AsyncSession
        :return: The created task.
        :rtype: Task
        """
        task = await _create_task(session, name="history-task")
        await _create_task_history(session, task, status=TaskHistoryStatusEnum.SUCCESS)
        await _create_task_history(session, task, status=TaskHistoryStatusEnum.FAILED)
        await _create_task_history(session, task, status=TaskHistoryStatusEnum.RUNNING)
        return task

    @pytest.mark.asyncio
    async def test_returns_histories_for_task(
        self, session: AsyncSession, task_with_histories: Task
    ) -> None:
        """Assert all histories for a task are returned."""
        result = await TaskHistoryManager.list_by_task_name(
            session=session, task_name="history-task"
        )

        assert len(result) == HISTORY_FIXTURE_COUNT

    @pytest.mark.asyncio
    async def test_with_status_filter(
        self, session: AsyncSession, task_with_histories: Task
    ) -> None:
        """Assert status filter returns only matching histories."""
        result = await TaskHistoryManager.list_by_task_name(
            session=session,
            task_name="history-task",
            status=TaskHistoryStatusEnum.RUNNING,
        )

        assert len(result) == 1
        assert result[0].status == TaskHistoryStatusEnum.RUNNING

    @pytest.mark.asyncio
    async def test_with_select_related_task(
        self, session: AsyncSession, task_with_histories: Task
    ) -> None:
        """Assert select_related_task=True loads the task relationship."""
        result = await TaskHistoryManager.list_by_task_name(
            session=session,
            task_name="history-task",
            select_related_task=True,
        )

        assert len(result) > 0
        assert result[0].task is not None
        assert result[0].task.name == "history-task"

    @pytest.mark.asyncio
    async def test_with_snippet_filename(self, session: AsyncSession) -> None:
        """Assert snippet_filename filter restricts results."""
        task = await _create_task(session, name="snippet-task")
        await _create_task_history(session, task, snippet_filename="config.yaml")
        await _create_task_history(session, task, snippet_filename="other.yaml")

        result = await TaskHistoryManager.list_by_task_name(
            session=session,
            task_name="snippet-task",
            snippet_filename="config.yaml",
        )

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_empty_result(self, session: AsyncSession) -> None:
        """Assert empty list is returned for a task with no history."""
        await _create_task(session, name="no-history-task")

        result = await TaskHistoryManager.list_by_task_name(
            session=session, task_name="no-history-task"
        )

        assert result == []


# ---------------------------------------------------------------------------
# TaskManager.list_active_paginated
# ---------------------------------------------------------------------------


class TestTaskManagerListActivePaginated:
    """Test TaskManager.list_active_paginated."""

    @pytest.mark.asyncio
    async def test_returns_paginated_response(self, session: AsyncSession) -> None:
        """Assert paginated response contains items, total, offset, and limit."""
        await _create_task(session, name="pag-task-1")
        await _create_task(session, name="pag-task-2")

        result = await TaskManager.list_active_paginated(session)

        assert result.total == PAGINATED_TASK_COUNT
        assert result.offset == DEFAULT_PAGINATION_OFFSET
        assert result.limit == DEFAULT_PAGINATION_LIMIT
        assert len(result.items) == PAGINATED_TASK_COUNT

    @pytest.mark.asyncio
    async def test_with_custom_offset_and_limit(self, session: AsyncSession) -> None:
        """Assert custom offset and limit restrict returned items."""
        for i in range(3):
            await _create_task(session, name=f"pag-custom-{i}")

        result = await TaskManager.list_active_paginated(session, offset=0, limit=1)

        assert result.total == PAGINATED_CUSTOM_TASK_COUNT
        assert len(result.items) == 1
        assert result.limit == 1

    @pytest.mark.asyncio
    async def test_with_owner_filter(self, session: AsyncSession) -> None:
        """Assert owner filter works with pagination."""
        await _create_task(session, name="pag-backup", owner=TaskOwner.BACKUPS)
        await _create_task(session, name="pag-alter", owner=TaskOwner.ALTERS)

        result = await TaskManager.list_active_paginated(
            session, owner=TaskOwner.BACKUPS
        )

        assert result.total == 1
        assert result.items[0].name == "pag-backup"

    @pytest.mark.asyncio
    async def test_excludes_deleted_tasks(self, session: AsyncSession) -> None:
        """Assert deleted tasks are excluded from paginated results."""
        await _create_task(session, name="pag-active")
        await _create_task(session, name="pag-deleted")
        await TaskManager.delete_by_name(session, "pag-deleted")

        result = await TaskManager.list_active_paginated(session)

        assert result.total == 1
        assert result.items[0].name == "pag-active"

    @pytest.mark.asyncio
    async def test_empty_db_returns_zero_total(self, session: AsyncSession) -> None:
        """Assert empty database returns total of zero."""
        result = await TaskManager.list_active_paginated(session)

        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_offset_beyond_total(self, session: AsyncSession) -> None:
        """Assert offset beyond total returns empty items with correct total."""
        await _create_task(session, name="pag-beyond")

        result = await TaskManager.list_active_paginated(session, offset=999)

        assert result.total == 1
        assert result.items == []


# ---------------------------------------------------------------------------
# TaskHistoryManager.list_by_task_name_paginated
# ---------------------------------------------------------------------------


class TestTaskHistoryManagerListByTaskNamePaginated:
    """Test TaskHistoryManager.list_by_task_name_paginated."""

    @pytest_asyncio.fixture
    async def task_with_histories(self, session: AsyncSession) -> Task:
        """Create a task with multiple history records.

        :param session: The async database session.
        :type session: AsyncSession
        :return: The created task.
        :rtype: Task
        """
        task = await _create_task(session, name="pag-history-task")
        await _create_task_history(session, task, status=TaskHistoryStatusEnum.SUCCESS)
        await _create_task_history(session, task, status=TaskHistoryStatusEnum.FAILED)
        await _create_task_history(session, task, status=TaskHistoryStatusEnum.RUNNING)
        return task

    @pytest.mark.asyncio
    async def test_returns_paginated_response(
        self, session: AsyncSession, task_with_histories: Task
    ) -> None:
        """Assert paginated response has correct envelope fields."""
        result = await TaskHistoryManager.list_by_task_name_paginated(
            session=session, task_name="pag-history-task"
        )

        assert result.total == HISTORY_FIXTURE_COUNT
        assert result.offset == DEFAULT_PAGINATION_OFFSET
        assert result.limit == DEFAULT_PAGINATION_LIMIT
        assert len(result.items) == HISTORY_FIXTURE_COUNT

    @pytest.mark.asyncio
    async def test_with_custom_limit(
        self, session: AsyncSession, task_with_histories: Task
    ) -> None:
        """Assert custom limit restricts returned items."""
        result = await TaskHistoryManager.list_by_task_name_paginated(
            session=session, task_name="pag-history-task", limit=1
        )

        assert result.total == HISTORY_FIXTURE_COUNT
        assert len(result.items) == 1

    @pytest.mark.asyncio
    async def test_with_status_filter(
        self, session: AsyncSession, task_with_histories: Task
    ) -> None:
        """Assert status filter restricts paginated results."""
        result = await TaskHistoryManager.list_by_task_name_paginated(
            session=session,
            task_name="pag-history-task",
            status=TaskHistoryStatusEnum.RUNNING,
        )

        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].status == TaskHistoryStatusEnum.RUNNING

    @pytest.mark.asyncio
    async def test_empty_result(self, session: AsyncSession) -> None:
        """Assert empty paginated response for task with no history."""
        await _create_task(session, name="pag-empty-task")

        result = await TaskHistoryManager.list_by_task_name_paginated(
            session=session, task_name="pag-empty-task"
        )

        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_offset_beyond_total(
        self, session: AsyncSession, task_with_histories: Task
    ) -> None:
        """Assert offset beyond total returns empty items with correct total."""
        result = await TaskHistoryManager.list_by_task_name_paginated(
            session=session, task_name="pag-history-task", offset=999
        )

        assert result.total == HISTORY_FIXTURE_COUNT
        assert result.items == []

    @pytest.mark.asyncio
    async def test_with_snippet_filename(self, session: AsyncSession) -> None:
        """Assert snippet_filename filter works with pagination."""
        task = await _create_task(session, name="pag-snippet-task")
        await _create_task_history(session, task, snippet_filename="config.yaml")
        await _create_task_history(session, task, snippet_filename="other.yaml")

        result = await TaskHistoryManager.list_by_task_name_paginated(
            session=session,
            task_name="pag-snippet-task",
            snippet_filename="config.yaml",
        )

        assert result.total == 1
        assert len(result.items) == 1


# ---------------------------------------------------------------------------
# DispatchLockManager
# ---------------------------------------------------------------------------


class TestDispatchLockManager:
    """Test DispatchLockManager."""

    @pytest.mark.asyncio
    async def test_create_lock(self, session: AsyncSession) -> None:
        """Assert a dispatch lock can be created."""
        lock = DispatchLock(name="my-lock")
        saved = await DispatchLockManager.save(session, lock)

        assert saved.id is not None
        assert saved.name == "my-lock"

    @pytest.mark.asyncio
    async def test_duplicate_lock_raises_conflict(self, session: AsyncSession) -> None:
        """Assert creating a duplicate lock name raises HTTPConflictException."""
        lock1 = DispatchLock(name="unique-lock")
        await DispatchLockManager.save(session, lock1)

        lock2 = DispatchLock(name="unique-lock")
        with pytest.raises(HTTPConflictException):
            await DispatchLockManager.save(session, lock2)

    @pytest.mark.asyncio
    async def test_delete_lock(self, session: AsyncSession) -> None:
        """Assert a dispatch lock can be deleted."""
        lock = DispatchLock(name="temp-lock")
        saved = await DispatchLockManager.save(session, lock)

        await DispatchLockManager.delete(session, saved)

        remaining = await DispatchLockManager.list(session)
        assert len(remaining) == 0
