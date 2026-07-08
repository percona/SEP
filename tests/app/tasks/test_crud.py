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

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth.exceptions import HTTPForbiddenException
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.exceptions import HTTPConflictException, HTTPNotFoundException
from app.core.pagination import (
    DEFAULT_PAGINATION_LIMIT,
    DEFAULT_PAGINATION_OFFSET,
    Pagination,
)
from app.core.utils.date_time import utc_now
from app.tasks.crud import (
    DispatchLockManager,
    TaskHistoryLogManager,
    TaskHistoryManager,
    TaskManager,
)
from app.tasks.logs.log_writer import TaskHistoryLogWriter
from app.tasks.models import (
    DispatchLock,
    Task,
    TaskBackendEnum,
    TaskHistory,
    TaskHistoryLog,
    TaskHistoryStatusEnum,
    TaskLogType,
    TaskWrite,
)
from tests.app.factories import TaskFactory

HISTORY_FIXTURE_COUNT = 3
PAGINATED_TASK_COUNT = 2
PAGINATED_CUSTOM_TASK_COUNT = 3
PBM_CONFIG_BACKUP_TYPE = "pbm_config"
PARENT_FILTER_TASK_COUNT = 3
CHUNKS_AT_OR_BELOW_OFFSET = 2


async def _create_task(
    session: AsyncSession,
    *,
    name: str = "test-task",
    owner: str = "ANY",
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
    :type owner: str
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
    finished_at: datetime | None = None,
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
    :param finished_at: Optional completion timestamp for the history row.
    :type finished_at: datetime | None
    :return: The persisted task history.
    :rtype: TaskHistory
    """
    meta = {}
    if snippet_filename:
        meta["_snippet_filename"] = snippet_filename
    history = TaskHistory(
        task_id=task.id,
        status=status,
        finished_at=finished_at,
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
        await _create_task(session, name="backup-task", owner="BACKUPS")
        await _create_task(session, name="alter-task", owner="ALTERS")

        result = await TaskManager.list_active(session, owner="BACKUPS")

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

        result = await TaskManager.list_active_paginated(
            session, pagination=Pagination()
        )

        assert result.total == PAGINATED_TASK_COUNT
        assert result.offset == DEFAULT_PAGINATION_OFFSET
        assert result.limit == DEFAULT_PAGINATION_LIMIT
        assert len(result.items) == PAGINATED_TASK_COUNT

    @pytest.mark.asyncio
    async def test_with_custom_offset_and_limit(self, session: AsyncSession) -> None:
        """Assert custom offset and limit restrict returned items."""
        for i in range(3):
            await _create_task(session, name=f"pag-custom-{i}")

        result = await TaskManager.list_active_paginated(
            session, pagination=Pagination(offset=0, limit=1)
        )

        assert result.total == PAGINATED_CUSTOM_TASK_COUNT
        assert len(result.items) == 1
        assert result.limit == 1

    @pytest.mark.asyncio
    async def test_with_owner_filter(self, session: AsyncSession) -> None:
        """Assert owner filter works with pagination."""
        await _create_task(session, name="pag-backup", owner="BACKUPS")
        await _create_task(session, name="pag-alter", owner="ALTERS")

        result = await TaskManager.list_active_paginated(
            session, owner="BACKUPS", pagination=Pagination()
        )

        assert result.total == 1
        assert result.items[0].name == "pag-backup"

    @pytest.mark.asyncio
    async def test_excludes_deleted_tasks(self, session: AsyncSession) -> None:
        """Assert deleted tasks are excluded from paginated results."""
        await _create_task(session, name="pag-active")
        await _create_task(session, name="pag-deleted")
        await TaskManager.delete_by_name(session, "pag-deleted")

        result = await TaskManager.list_active_paginated(
            session, pagination=Pagination()
        )

        assert result.total == 1
        assert result.items[0].name == "pag-active"

    @pytest.mark.asyncio
    async def test_empty_db_returns_zero_total(self, session: AsyncSession) -> None:
        """Assert empty database returns total of zero."""
        result = await TaskManager.list_active_paginated(
            session, pagination=Pagination()
        )

        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_offset_beyond_total(self, session: AsyncSession) -> None:
        """Assert offset beyond total returns empty items with correct total."""
        await _create_task(session, name="pag-beyond")

        result = await TaskManager.list_active_paginated(
            session, pagination=Pagination(offset=999)
        )

        assert result.total == 1
        assert result.items == []

    @pytest.mark.asyncio
    async def test_with_parent_is_null_filter(self, session: AsyncSession) -> None:
        """Assert parent_is_null=True excludes tasks with a parent reference."""
        await _create_task(
            session,
            name="pag-parent",
            data={"backup_type": PBM_CONFIG_BACKUP_TYPE},
        )
        await _create_task(
            session,
            name="pag-child",
            data={
                "backup_type": "pbm_logical",
                "parent": "pag-parent",
            },
        )

        null_parents = await TaskManager.list_active_paginated(
            session, parent_is_null=True, pagination=Pagination()
        )
        non_null_parents = await TaskManager.list_active_paginated(
            session, parent_is_null=False, pagination=Pagination()
        )

        assert null_parents.total == 1
        assert null_parents.items[0].name == "pag-parent"
        assert non_null_parents.total == 1
        assert non_null_parents.items[0].name == "pag-child"

    @pytest.mark.asyncio
    async def test_with_backup_type_filter(self, session: AsyncSession) -> None:
        """Assert backup_type filters on data.backup_type as string."""
        await _create_task(
            session,
            name="pag-pbm-config",
            data={"backup_type": PBM_CONFIG_BACKUP_TYPE},
        )
        await _create_task(
            session,
            name="pag-pbm-logical",
            data={"backup_type": "pbm_logical", "parent": "pag-pbm-config"},
        )

        result = await TaskManager.list_active_paginated(
            session, backup_type=PBM_CONFIG_BACKUP_TYPE, pagination=Pagination()
        )

        assert result.total == 1
        assert result.items[0].name == "pag-pbm-config"

    @pytest.mark.asyncio
    async def test_with_self_parent_filter(self, session: AsyncSession) -> None:
        """Assert self_parent=True keeps only rows where data.parent == task.name."""
        await _create_task(
            session,
            name="pag-self-parent",
            data={"backup_type": "pbm_logical", "parent": "pag-self-parent"},
        )
        await _create_task(
            session,
            name="pag-config-parent",
            data={"backup_type": PBM_CONFIG_BACKUP_TYPE},
        )
        await _create_task(
            session,
            name="pag-child",
            data={"backup_type": "pbm_logical", "parent": "pag-config-parent"},
        )

        result = await TaskManager.list_active_paginated(
            session, self_parent=True, pagination=Pagination()
        )

        assert result.total == 1
        assert result.items[0].name == "pag-self-parent"

    @pytest.mark.asyncio
    async def test_parent_and_backup_type_filters_with_pagination(
        self, session: AsyncSession
    ) -> None:
        """Assert combined JSON filters paginate over the filtered set."""
        for index in range(PARENT_FILTER_TASK_COUNT):
            await _create_task(
                session,
                name=f"pag-filter-parent-{index}",
                data={"backup_type": PBM_CONFIG_BACKUP_TYPE},
            )
        await _create_task(
            session,
            name="pag-filter-child",
            data={
                "backup_type": "pbm_logical",
                "parent": "pag-filter-parent-0",
            },
        )

        result = await TaskManager.list_active_paginated(
            session,
            parent_is_null=True,
            backup_type=PBM_CONFIG_BACKUP_TYPE,
            pagination=Pagination(offset=1, limit=1),
        )

        assert result.total == PARENT_FILTER_TASK_COUNT
        assert result.offset == 1
        assert result.limit == 1
        assert len(result.items) == 1
        assert result.items[0].name in {
            "pag-filter-parent-0",
            "pag-filter-parent-1",
            "pag-filter-parent-2",
        }


# ---------------------------------------------------------------------------
# TaskHistoryManager.latest_status_by_task_names
# ---------------------------------------------------------------------------


class TestTaskHistoryManagerLatestStatusByTaskNames:
    """Test TaskHistoryManager.latest_status_by_task_names."""

    @pytest.mark.asyncio
    async def test_empty_names_returns_empty_mapping(
        self, session: AsyncSession
    ) -> None:
        """Assert an empty request yields an empty mapping."""
        result = await TaskHistoryManager.latest_status_by_task_names(session, [])

        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_latest_status_per_task(self, session: AsyncSession) -> None:
        """Assert newest non-null history status is returned for each task."""
        suffix = uuid4().hex[:8]
        task_a_name = f"latest-status-a-{suffix}"
        task_b_name = f"latest-status-b-{suffix}"
        missing_name = f"latest-status-missing-{suffix}"

        task_a = await _create_task(session, name=task_a_name)
        task_b = await _create_task(session, name=task_b_name)
        await _create_task_history(
            session, task_a, status=TaskHistoryStatusEnum.SUCCESS
        )
        await _create_task_history(
            session, task_a, status=TaskHistoryStatusEnum.RUNNING
        )
        await _create_task_history(session, task_b, status=TaskHistoryStatusEnum.FAILED)

        result = await TaskHistoryManager.latest_status_by_task_names(
            session,
            [task_a_name, task_b_name, missing_name],
        )

        assert result[task_a_name].status == TaskHistoryStatusEnum.RUNNING
        assert result[task_b_name].status == TaskHistoryStatusEnum.FAILED
        assert result[missing_name] is None

    @pytest.mark.asyncio
    async def test_deduplicates_duplicate_names(self, session: AsyncSession) -> None:
        """Assert duplicate names are resolved once while preserving order."""
        task = await _create_task(session, name="latest-status-dedupe")
        await _create_task_history(session, task, status=TaskHistoryStatusEnum.SUCCESS)

        result = await TaskHistoryManager.latest_status_by_task_names(
            session,
            ["latest-status-dedupe", "latest-status-dedupe"],
        )

        assert list(result.keys()) == ["latest-status-dedupe"]
        assert result["latest-status-dedupe"].status == TaskHistoryStatusEnum.SUCCESS

    @pytest.mark.asyncio
    async def test_latest_status_from_history_statuses_skips_nulls(self) -> None:
        """Assert null statuses are skipped when scanning newest-to-oldest."""
        result = TaskHistoryManager._latest_status_from_history_statuses(
            [None, TaskHistoryStatusEnum.SUCCESS, TaskHistoryStatusEnum.FAILED]
        )

        assert result == TaskHistoryStatusEnum.SUCCESS

    @pytest.mark.asyncio
    async def test_finished_at_is_max_across_rows(self, session: AsyncSession) -> None:
        """Assert finished_at is the max across rows while status is the newest.

        Models the in-progress re-run case: an earlier SUCCESS/FAILED pair has
        real finish times and the newest row is RUNNING with no finish time, so
        the projection reports RUNNING status but still the prior (max) finish.
        """
        task = await _create_task(session, name="latest-mixed")
        early = utc_now() - timedelta(hours=2)
        later = utc_now() - timedelta(hours=1)
        await _create_task_history(
            session, task, status=TaskHistoryStatusEnum.SUCCESS, finished_at=early
        )
        failed = await _create_task_history(
            session, task, status=TaskHistoryStatusEnum.FAILED, finished_at=later
        )
        await _create_task_history(
            session, task, status=TaskHistoryStatusEnum.RUNNING, finished_at=None
        )

        result = await TaskHistoryManager.latest_status_by_task_names(
            session, [task.name]
        )

        latest = result[task.name]
        assert latest is not None
        assert latest.status == TaskHistoryStatusEnum.RUNNING
        assert latest.finished_at == failed.finished_at

    @pytest.mark.asyncio
    async def test_only_running_never_finished_has_no_finish(
        self, session: AsyncSession
    ) -> None:
        """Assert a single unfinished RUNNING row yields status but no finish."""
        task = await _create_task(session, name="latest-running")
        await _create_task_history(
            session, task, status=TaskHistoryStatusEnum.RUNNING, finished_at=None
        )

        result = await TaskHistoryManager.latest_status_by_task_names(
            session, [task.name]
        )

        latest = result[task.name]
        assert latest is not None
        assert latest.status == TaskHistoryStatusEnum.RUNNING
        assert latest.finished_at is None

    @pytest.mark.asyncio
    async def test_failed_run_reports_finish(self, session: AsyncSession) -> None:
        """Assert a FAILED run still reports its finish time (it did run)."""
        task = await _create_task(session, name="latest-failed")
        finished = utc_now() - timedelta(minutes=30)
        row = await _create_task_history(
            session, task, status=TaskHistoryStatusEnum.FAILED, finished_at=finished
        )

        result = await TaskHistoryManager.latest_status_by_task_names(
            session, [task.name]
        )

        latest = result[task.name]
        assert latest is not None
        assert latest.status == TaskHistoryStatusEnum.FAILED
        assert latest.finished_at == row.finished_at


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
            session=session,
            task_name="pag-history-task",
            pagination=Pagination(),
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
            session=session,
            task_name="pag-history-task",
            pagination=Pagination(limit=1),
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
            pagination=Pagination(),
        )

        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].status == TaskHistoryStatusEnum.RUNNING

    @pytest.mark.asyncio
    async def test_empty_result(self, session: AsyncSession) -> None:
        """Assert empty paginated response for task with no history."""
        await _create_task(session, name="pag-empty-task")

        result = await TaskHistoryManager.list_by_task_name_paginated(
            session=session,
            task_name="pag-empty-task",
            pagination=Pagination(),
        )

        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_offset_beyond_total(
        self, session: AsyncSession, task_with_histories: Task
    ) -> None:
        """Assert offset beyond total returns empty items with correct total."""
        result = await TaskHistoryManager.list_by_task_name_paginated(
            session=session,
            task_name="pag-history-task",
            pagination=Pagination(offset=999),
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
            pagination=Pagination(),
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


# ---------------------------------------------------------------------------
# TaskHistoryLogManager.ids_with_chunks
# ---------------------------------------------------------------------------


async def _seed_task_history(
    session: AsyncSession, task: Task, name: str
) -> TaskHistory:
    """Persist and return a SUCCESS task history for ``task``.

    Helper for ``ids_with_chunks`` tests: each chunk-store row requires a
    real ``TaskHistory`` FK.
    """
    history = TaskHistory(
        task_id=task.id,
        status=TaskHistoryStatusEnum.SUCCESS,
        execution_request={
            "task": task.name,
            "target": name,
            "meta": {},
            "tracking": {"allocation_id": None, "evaluation_id": None},
        },
    )
    return await TaskHistoryManager.save(session, history)


async def _seed_chunk(
    session: AsyncSession, task_history_id: int, payload: bytes = b"hello"
) -> None:
    """Write a single chunk-store row for ``task_history_id`` via the writer."""
    await TaskHistoryLogWriter.append(
        session,
        task_history_id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=payload,
        force_flush=True,
        producer_offset_after=len(payload),
    )


class TestTaskHistoryLogManagerIdsWithChunks:
    """Test ``TaskHistoryLogManager.ids_with_chunks``."""

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty_set(self, session: AsyncSession) -> None:
        """Assert an empty input returns ``set()`` without querying the DB."""
        result = await TaskHistoryLogManager.ids_with_chunks(session, [])

        assert result == set()

    @pytest.mark.asyncio
    async def test_no_matches_returns_empty_set(self, session: AsyncSession) -> None:
        """Assert IDs with no chunks in the store come back as an empty set."""
        task = await _create_task(session)
        history = await _seed_task_history(session, task, "node-a")

        result = await TaskHistoryLogManager.ids_with_chunks(session, [history.id])

        assert result == set()

    @pytest.mark.asyncio
    async def test_returns_only_ids_with_chunks(self, session: AsyncSession) -> None:
        """Assert the subset with chunks is returned for a mixed input."""
        task = await _create_task(session)
        with_chunks_a = await _seed_task_history(session, task, "node-a")
        with_chunks_b = await _seed_task_history(session, task, "node-b")
        without_chunks = await _seed_task_history(session, task, "node-c")
        await _seed_chunk(session, with_chunks_a.id)
        await _seed_chunk(session, with_chunks_b.id)

        result = await TaskHistoryLogManager.ids_with_chunks(
            session,
            [with_chunks_a.id, with_chunks_b.id, without_chunks.id],
        )

        assert result == {with_chunks_a.id, with_chunks_b.id}

    @pytest.mark.asyncio
    async def test_deduplicates_multiple_chunk_rows_per_history(
        self, session: AsyncSession
    ) -> None:
        """Assert a history with multiple chunks is reported once (DISTINCT)."""
        task = await _create_task(session)
        history = await _seed_task_history(session, task, "node-a")
        await _seed_chunk(session, history.id, payload=b"first")
        await TaskHistoryLogWriter.append(
            session,
            history.id,
            source="run-script",
            stream=TaskLogType.STDERR,
            new_bytes=b"second",
            force_flush=True,
            producer_offset_after=6,
        )

        result = await TaskHistoryLogManager.ids_with_chunks(session, [history.id])

        assert result == {history.id}


# ---------------------------------------------------------------------------
# TaskHistoryLogManager.list_stream_keys / iter_chunks_reverse
# ---------------------------------------------------------------------------


class TestTaskHistoryLogManagerStreamKeysAndReverse:
    """Test ``list_stream_keys`` and ``iter_chunks_reverse``."""

    @pytest.mark.asyncio
    async def test_list_stream_keys_returns_distinct_pairs(
        self, session: AsyncSession
    ) -> None:
        """Assert distinct ``(source, stream)`` pairs are returned in order."""
        task = await _create_task(session)
        history = await _seed_task_history(session, task, "node-a")
        await _seed_chunk(session, history.id, payload=b"stdout-a")
        await TaskHistoryLogWriter.append(
            session,
            history.id,
            source="run-script",
            stream=TaskLogType.STDERR,
            new_bytes=b"stderr-a",
            force_flush=True,
            producer_offset_after=8,
        )
        await TaskHistoryLogWriter.append(
            session,
            history.id,
            source="prepare",
            stream=TaskLogType.STDOUT,
            new_bytes=b"stdout-b",
            force_flush=True,
            producer_offset_after=8,
        )

        keys = await TaskHistoryLogManager.list_stream_keys(session, history.id)

        assert keys == [
            ("prepare", TaskLogType.STDOUT),
            ("run-script", TaskLogType.STDERR),
            ("run-script", TaskLogType.STDOUT),
        ]

    @pytest.mark.asyncio
    async def test_list_stream_keys_source_filter(self, session: AsyncSession) -> None:
        """Assert ``source`` limits pairs to the matching step."""
        task = await _create_task(session)
        history = await _seed_task_history(session, task, "node-a")
        await _seed_chunk(session, history.id, payload=b"stdout-a")
        await TaskHistoryLogWriter.append(
            session,
            history.id,
            source="prepare",
            stream=TaskLogType.STDOUT,
            new_bytes=b"stdout-b",
            force_flush=True,
            producer_offset_after=8,
        )

        keys = await TaskHistoryLogManager.list_stream_keys(
            session, history.id, source="run-script"
        )

        assert keys == [("run-script", TaskLogType.STDOUT)]

    @pytest.mark.asyncio
    async def test_list_stream_keys_empty_when_no_chunks(
        self, session: AsyncSession
    ) -> None:
        """Assert an empty list is returned when no chunk rows exist."""
        task = await _create_task(session)
        history = await _seed_task_history(session, task, "node-a")

        keys = await TaskHistoryLogManager.list_stream_keys(session, history.id)

        assert keys == []

    @pytest.mark.asyncio
    async def test_iter_chunks_reverse_yields_newest_first_per_stream(
        self, session: AsyncSession
    ) -> None:
        """Assert chunks are yielded in descending ``start_offset`` order."""
        task = await _create_task(session)
        history = await _seed_task_history(session, task, "node-a")
        await TaskHistoryLogWriter.append(
            session,
            history.id,
            source="run-script",
            stream=TaskLogType.STDOUT,
            new_bytes=b"first",
            force_flush=True,
            producer_offset_after=5,
        )
        await TaskHistoryLogWriter.append(
            session,
            history.id,
            source="run-script",
            stream=TaskLogType.STDOUT,
            new_bytes=b"second",
            force_flush=True,
            producer_offset_after=11,
        )
        await TaskHistoryLogWriter.append(
            session,
            history.id,
            source="run-script",
            stream=TaskLogType.STDERR,
            new_bytes=b"err",
            force_flush=True,
            producer_offset_after=3,
        )

        chunks = [
            chunk
            async for chunk in TaskHistoryLogManager.iter_chunks_reverse(
                session,
                history.id,
                source="run-script",
                stream=TaskLogType.STDOUT,
            )
        ]

        assert [chunk.content for chunk in chunks] == ["second", "first"]
        assert [chunk.start_offset for chunk in chunks] == [5, 0]

    @pytest.mark.asyncio
    async def test_iter_chunks_reverse_orders_streams_before_offsets(
        self, session: AsyncSession
    ) -> None:
        """Assert global ordering is ``(source, stream, start_offset DESC)``."""
        task = await _create_task(session)
        history = await _seed_task_history(session, task, "node-a")
        await _seed_chunk(session, history.id, payload=b"stdout")
        await TaskHistoryLogWriter.append(
            session,
            history.id,
            source="run-script",
            stream=TaskLogType.STDERR,
            new_bytes=b"stderr",
            force_flush=True,
            producer_offset_after=6,
        )

        chunks = [
            chunk
            async for chunk in TaskHistoryLogManager.iter_chunks_reverse(
                session, history.id
            )
        ]

        assert [(chunk.source, chunk.stream, chunk.content) for chunk in chunks] == [
            ("run-script", TaskLogType.STDERR, "stderr"),
            ("run-script", TaskLogType.STDOUT, "stdout"),
        ]


class TestTaskHistoryLogManagerStderrTailChunks:
    """Test ``TaskHistoryLogManager.get_stderr_tail_chunks``."""

    async def _append_stderr(
        self,
        session: AsyncSession,
        task_history_id: int,
        payload: bytes,
        producer_offset_after: int,
    ) -> None:
        """Append a STDERR chunk via the writer."""
        await TaskHistoryLogWriter.append(
            session,
            task_history_id,
            source="run-script",
            stream=TaskLogType.STDERR,
            new_bytes=payload,
            force_flush=True,
            producer_offset_after=producer_offset_after,
        )

    @pytest.mark.asyncio
    async def test_returns_chunk_contents_newest_first(
        self, session: AsyncSession
    ) -> None:
        """Return STDERR chunk contents ordered newest-first by insertion id.

        Callers reconstruct chronological order by reversing; the manager only
        guarantees newest-first ordering of the raw chunk contents.
        """
        task = await _create_task(session)
        history = await _seed_task_history(session, task, "node-a")
        await self._append_stderr(session, history.id, b"first error", 11)
        await self._append_stderr(session, history.id, b"last error", 21)

        chunks = await TaskHistoryLogManager.get_stderr_tail_chunks(session, history.id)
        assert chunks == ["last error", "first error"]

    @pytest.mark.asyncio
    async def test_respects_limit(self, session: AsyncSession) -> None:
        """Return only the newest ``limit`` STDERR chunks."""
        task = await _create_task(session)
        history = await _seed_task_history(session, task, "node-a")
        await self._append_stderr(session, history.id, b"c1", 2)
        await self._append_stderr(session, history.id, b"c2", 4)
        await self._append_stderr(session, history.id, b"c3", 6)

        chunks = await TaskHistoryLogManager.get_stderr_tail_chunks(
            session, history.id, limit=2
        )
        assert chunks == ["c3", "c2"]

    @pytest.mark.asyncio
    async def test_ignores_stdout_chunks(self, session: AsyncSession) -> None:
        """Consider only STDERR chunks; ignore STDOUT."""
        task = await _create_task(session)
        history = await _seed_task_history(session, task, "node-a")
        await _seed_chunk(session, history.id, payload=b"stdout only")

        chunks = await TaskHistoryLogManager.get_stderr_tail_chunks(session, history.id)
        assert chunks == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_chunks(self, session: AsyncSession) -> None:
        """Return an empty list when the task history has no chunks at all."""
        task = await _create_task(session)
        history = await _seed_task_history(session, task, "node-a")

        chunks = await TaskHistoryLogManager.get_stderr_tail_chunks(session, history.id)
        assert chunks == []


async def _create_history_with_log(
    session: AsyncSession,
    task: Task,
    *,
    status: TaskHistoryStatusEnum,
    created_at: datetime,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    chunks: int = 1,
) -> TaskHistory:
    """Create a ``TaskHistory`` with explicit timestamps and ``chunks`` log rows.

    :param session: The async database session.
    :param task: The parent task.
    :param status: The execution status to assign.
    :param created_at: The ``created_at`` timestamp to force on the history row.
    :param started_at: The optional ``started_at`` timestamp.
    :param finished_at: The optional ``finished_at`` timestamp.
    :param chunks: The number of ``TaskHistoryLog`` rows to attach.
    :return: The persisted task history.
    """
    history = TaskHistory(
        task_id=task.id,
        status=status,
        created_at=created_at,
        started_at=started_at,
        finished_at=finished_at,
        execution_request={
            "task": task.name,
            "target": "localhost",
            "meta": {},
            "tracking": {"allocation_id": None, "evaluation_id": None},
        },
    )
    history = await TaskHistoryManager.save(session, history)
    for offset in range(chunks):
        session.add(
            TaskHistoryLog(
                task_history_id=history.id,
                source="run-python",
                stream=TaskLogType.STDOUT,
                start_offset=offset * 10,
                end_offset=offset * 10 + 10,
                content="x" * 10,
            )
        )
    await session.commit()
    return history


async def _count_logs(session: AsyncSession) -> int:
    """Return the total number of ``taskhistory_log`` rows."""
    result = await session.exec(select(col(TaskHistoryLog.id)))
    return len(result.all())


async def _count_histories(session: AsyncSession) -> int:
    """Return the total number of ``taskhistory`` rows."""
    result = await session.exec(select(col(TaskHistory.id)))
    return len(result.all())


AGED_CHUNKS = 2
BATCH_TOTAL_CHUNKS = 5
BATCH_LIMIT = 3
BATCH_REMAINDER = BATCH_TOTAL_CHUNKS - BATCH_LIMIT
PG_CHUNKS = 3
PG_LOCK_CHUNKS = 2


class TestTaskHistoryLogManagerDeleteAgedBatch:
    """Test ``TaskHistoryLogManager.delete_aged_batch``."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status",
        [
            TaskHistoryStatusEnum.SUCCESS,
            TaskHistoryStatusEnum.FAILED,
            TaskHistoryStatusEnum.STOPPED,
            TaskHistoryStatusEnum.LOST,
            TaskHistoryStatusEnum.STALE,
        ],
    )
    async def test_deletes_aged_non_active_logs(
        self, session: AsyncSession, status: TaskHistoryStatusEnum
    ) -> None:
        """Delete logs of aged, non-active executions and preserve the audit row."""
        task = await _create_task(session)
        old = utc_now() - timedelta(days=100)
        await _create_history_with_log(
            session,
            task,
            status=status,
            created_at=old,
            finished_at=old,
            chunks=AGED_CHUNKS,
        )
        cutoff = utc_now() - timedelta(days=90)

        deleted = await TaskHistoryLogManager.delete_aged_batch(
            session, cutoff=cutoff, batch_size=100
        )

        assert deleted == AGED_CHUNKS
        assert await _count_logs(session) == 0
        assert await _count_histories(session) == 1  # audit row preserved

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status",
        [TaskHistoryStatusEnum.PENDING, TaskHistoryStatusEnum.RUNNING],
    )
    async def test_skips_active_logs(
        self, session: AsyncSession, status: TaskHistoryStatusEnum
    ) -> None:
        """Never delete logs of PENDING/RUNNING executions, however old."""
        task = await _create_task(session)
        old = utc_now() - timedelta(days=100)
        await _create_history_with_log(
            session, task, status=status, created_at=old, chunks=AGED_CHUNKS
        )
        cutoff = utc_now() - timedelta(days=90)

        deleted = await TaskHistoryLogManager.delete_aged_batch(
            session, cutoff=cutoff, batch_size=100
        )

        assert deleted == 0
        assert await _count_logs(session) == AGED_CHUNKS

    @pytest.mark.asyncio
    async def test_skips_recent_logs(self, session: AsyncSession) -> None:
        """Keep logs whose effective completion is newer than the cutoff."""
        task = await _create_task(session)
        recent = utc_now() - timedelta(days=10)
        await _create_history_with_log(
            session,
            task,
            status=TaskHistoryStatusEnum.SUCCESS,
            created_at=recent,
            finished_at=recent,
        )
        cutoff = utc_now() - timedelta(days=90)

        deleted = await TaskHistoryLogManager.delete_aged_batch(
            session, cutoff=cutoff, batch_size=100
        )

        assert deleted == 0
        assert await _count_logs(session) == 1

    @pytest.mark.asyncio
    async def test_cutoff_boundary_is_strict(self, session: AsyncSession) -> None:
        """A row exactly at the cutoff is kept (strict ``<`` comparison)."""
        task = await _create_task(session)
        cutoff = utc_now() - timedelta(days=90)
        await _create_history_with_log(
            session,
            task,
            status=TaskHistoryStatusEnum.SUCCESS,
            created_at=cutoff,
            finished_at=cutoff,
        )

        deleted = await TaskHistoryLogManager.delete_aged_batch(
            session, cutoff=cutoff, batch_size=100
        )

        assert deleted == 0
        assert await _count_logs(session) == 1

    @pytest.mark.asyncio
    async def test_coalesce_falls_back_to_started_at(
        self, session: AsyncSession
    ) -> None:
        """With finished_at NULL, age is taken from started_at."""
        task = await _create_task(session)
        old = utc_now() - timedelta(days=100)
        await _create_history_with_log(
            session,
            task,
            status=TaskHistoryStatusEnum.SUCCESS,
            created_at=utc_now(),  # recent created_at must NOT save the row
            started_at=old,
        )
        cutoff = utc_now() - timedelta(days=90)

        deleted = await TaskHistoryLogManager.delete_aged_batch(
            session, cutoff=cutoff, batch_size=100
        )

        assert deleted == 1

    @pytest.mark.asyncio
    async def test_coalesce_falls_back_to_created_at(
        self, session: AsyncSession
    ) -> None:
        """With finished_at and started_at NULL, age is taken from created_at."""
        task = await _create_task(session)
        old = utc_now() - timedelta(days=100)
        await _create_history_with_log(
            session, task, status=TaskHistoryStatusEnum.SUCCESS, created_at=old
        )
        cutoff = utc_now() - timedelta(days=90)

        deleted = await TaskHistoryLogManager.delete_aged_batch(
            session, cutoff=cutoff, batch_size=100
        )

        assert deleted == 1

    @pytest.mark.asyncio
    async def test_batch_size_caps_rows_per_call(self, session: AsyncSession) -> None:
        """A single call deletes at most ``batch_size`` rows."""
        task = await _create_task(session)
        old = utc_now() - timedelta(days=100)
        await _create_history_with_log(
            session,
            task,
            status=TaskHistoryStatusEnum.SUCCESS,
            created_at=old,
            finished_at=old,
            chunks=BATCH_TOTAL_CHUNKS,
        )
        cutoff = utc_now() - timedelta(days=90)

        deleted = await TaskHistoryLogManager.delete_aged_batch(
            session, cutoff=cutoff, batch_size=BATCH_LIMIT
        )

        assert deleted == BATCH_LIMIT
        assert await _count_logs(session) == BATCH_REMAINDER

    @pytest.mark.asyncio
    async def test_empty_table_returns_zero(self, session: AsyncSession) -> None:
        """Return 0 when there is nothing to delete."""
        cutoff = utc_now() - timedelta(days=90)
        deleted = await TaskHistoryLogManager.delete_aged_batch(
            session, cutoff=cutoff, batch_size=100
        )
        assert deleted == 0

    @pytest.mark.postgres
    @pytest.mark.asyncio
    async def test_deletes_on_real_postgres(
        self, postgres_session: AsyncSession
    ) -> None:
        """The FOR UPDATE SKIP LOCKED batched delete runs and deletes on real PG."""
        task = await _create_task(postgres_session)
        old = utc_now() - timedelta(days=100)
        await _create_history_with_log(
            postgres_session,
            task,
            status=TaskHistoryStatusEnum.LOST,
            created_at=old,
            finished_at=old,
            chunks=PG_CHUNKS,
        )
        cutoff = utc_now() - timedelta(days=90)

        deleted = await TaskHistoryLogManager.delete_aged_batch(
            postgres_session, cutoff=cutoff, batch_size=100
        )

        assert deleted == PG_CHUNKS
        assert await _count_logs(postgres_session) == 0
        assert await _count_histories(postgres_session) == 1

    @pytest.mark.postgres
    @pytest.mark.asyncio
    async def test_skip_locked_skips_rows_locked_by_another_session(
        self, postgres_engine: AsyncEngine, postgres_session: AsyncSession
    ) -> None:
        """Rows locked by a concurrent transaction are skipped, not blocked on."""
        task = await _create_task(postgres_session)
        old = utc_now() - timedelta(days=100)
        await _create_history_with_log(
            postgres_session,
            task,
            status=TaskHistoryStatusEnum.SUCCESS,
            created_at=old,
            finished_at=old,
            chunks=PG_LOCK_CHUNKS,
        )
        cutoff = utc_now() - timedelta(days=90)

        # Session A locks every log row and holds the transaction open.
        locker_maker = get_async_session_maker_from_engine(postgres_engine)
        async with locker_maker() as locker:
            await locker.exec(
                select(col(TaskHistoryLog.id)).with_for_update(skip_locked=True)
            )
            # Session B must skip the locked rows rather than block/deadlock.
            deleted = await TaskHistoryLogManager.delete_aged_batch(
                postgres_session, cutoff=cutoff, batch_size=100
            )
            assert deleted == 0
            await locker.rollback()

        # With the lock released, the rows are now deletable.
        deleted = await TaskHistoryLogManager.delete_aged_batch(
            postgres_session, cutoff=cutoff, batch_size=100
        )
        assert deleted == PG_LOCK_CHUNKS


# ---------------------------------------------------------------------------
# TaskHistoryLogManager.delete_chunks_below_offset
# ---------------------------------------------------------------------------


async def _insert_log_chunk(
    session: AsyncSession,
    task_history_id: int,
    *,
    start: int,
    end: int,
    source: str = "run-script",
    stream: TaskLogType = TaskLogType.STDOUT,
) -> None:
    """Insert a chunk row spanning ``[start, end)`` for the given stream."""
    await TaskHistoryLogManager.insert_chunk_idempotent(
        session,
        task_history_id=task_history_id,
        source=source,
        stream=stream,
        start_offset=start,
        chunk=b"x" * (end - start),
        now=utc_now(),
    )


async def _stream_end_offsets(
    session: AsyncSession,
    task_history_id: int,
    *,
    source: str = "run-script",
    stream: TaskLogType = TaskLogType.STDOUT,
) -> list[int]:
    """Return the ``end_offset`` of each chunk for a stream, ascending."""
    result = await session.exec(
        select(TaskHistoryLog)
        .where(
            col(TaskHistoryLog.task_history_id) == task_history_id,
            col(TaskHistoryLog.source) == source,
            col(TaskHistoryLog.stream) == stream,
        )
        .order_by(col(TaskHistoryLog.end_offset))
    )
    return [chunk.end_offset for chunk in result.all()]


class TestTaskHistoryLogManagerDeleteChunksBelowOffset:
    """Test ``TaskHistoryLogManager.delete_chunks_below_offset``."""

    @pytest.mark.asyncio
    async def test_deletes_chunks_at_or_below_offset_inclusive(
        self, session: AsyncSession
    ) -> None:
        """Assert ``end_offset <= max_end_offset`` rows are deleted (boundary)."""
        task = await _create_task(session)
        history = await _seed_task_history(session, task, "node-a")
        for start in (0, 100, 200, 300):
            await _insert_log_chunk(session, history.id, start=start, end=start + 100)
        await session.commit()

        deleted = await TaskHistoryLogManager.delete_chunks_below_offset(
            session,
            task_history_id=history.id,
            source="run-script",
            stream=TaskLogType.STDOUT,
            max_end_offset=200,
            max_rows=100,
        )
        await session.commit()

        assert deleted == CHUNKS_AT_OR_BELOW_OFFSET
        assert await _stream_end_offsets(session, history.id) == [300, 400]

    @pytest.mark.asyncio
    async def test_respects_max_rows_oldest_first(self, session: AsyncSession) -> None:
        """Assert at most ``max_rows`` chunks are deleted, oldest first."""
        task = await _create_task(session)
        history = await _seed_task_history(session, task, "node-a")
        for start in (0, 100, 200, 300):
            await _insert_log_chunk(session, history.id, start=start, end=start + 100)
        await session.commit()

        max_rows = 2
        deleted = await TaskHistoryLogManager.delete_chunks_below_offset(
            session,
            task_history_id=history.id,
            source="run-script",
            stream=TaskLogType.STDOUT,
            max_end_offset=1000,
            max_rows=max_rows,
        )
        await session.commit()

        assert deleted == max_rows
        assert await _stream_end_offsets(session, history.id) == [300, 400]

    @pytest.mark.asyncio
    async def test_no_match_returns_zero(self, session: AsyncSession) -> None:
        """Assert a delete that matches nothing returns ``0`` and removes nothing."""
        task = await _create_task(session)
        history = await _seed_task_history(session, task, "node-a")
        for start in (0, 100, 200):
            await _insert_log_chunk(session, history.id, start=start, end=start + 100)
        await session.commit()

        deleted = await TaskHistoryLogManager.delete_chunks_below_offset(
            session,
            task_history_id=history.id,
            source="run-script",
            stream=TaskLogType.STDOUT,
            max_end_offset=50,
            max_rows=10,
        )
        await session.commit()

        assert deleted == 0
        assert await _stream_end_offsets(session, history.id) == [100, 200, 300]

    @pytest.mark.asyncio
    async def test_only_targets_matching_stream(self, session: AsyncSession) -> None:
        """Assert chunks of other ``(source, stream)`` tuples are left untouched."""
        task = await _create_task(session)
        history = await _seed_task_history(session, task, "node-a")
        await _insert_log_chunk(session, history.id, start=0, end=100)
        await _insert_log_chunk(
            session, history.id, start=0, end=100, stream=TaskLogType.STDERR
        )
        await _insert_log_chunk(session, history.id, start=0, end=100, source="prepare")
        await session.commit()

        deleted = await TaskHistoryLogManager.delete_chunks_below_offset(
            session,
            task_history_id=history.id,
            source="run-script",
            stream=TaskLogType.STDOUT,
            max_end_offset=100,
            max_rows=10,
        )
        await session.commit()

        assert deleted == 1
        assert await _stream_end_offsets(session, history.id) == []
        assert await _stream_end_offsets(
            session, history.id, stream=TaskLogType.STDERR
        ) == [100]
        assert await _stream_end_offsets(session, history.id, source="prepare") == [100]

    @pytest.mark.asyncio
    async def test_does_not_commit(self, session: AsyncSession) -> None:
        """Assert the helper stages the delete without committing it.

        The caller owns the transaction, so a ``rollback`` after the call must
        restore every staged-for-deletion row.
        """
        task = await _create_task(session)
        history = await _seed_task_history(session, task, "node-a")
        history_id = history.id
        for start in (0, 100, 200, 300):
            await _insert_log_chunk(session, history_id, start=start, end=start + 100)
        await session.commit()

        deleted = await TaskHistoryLogManager.delete_chunks_below_offset(
            session,
            task_history_id=history_id,
            source="run-script",
            stream=TaskLogType.STDOUT,
            max_end_offset=200,
            max_rows=100,
        )
        assert deleted == CHUNKS_AT_OR_BELOW_OFFSET
        await session.rollback()

        assert await _stream_end_offsets(session, history_id) == [100, 200, 300, 400]

    @pytest.mark.asyncio
    async def test_bounded_delete_on_postgres(
        self, postgres_session: AsyncSession
    ) -> None:
        """Assert the PK-IN-subquery delete behaves identically on real PostgreSQL."""
        task = await _create_task(postgres_session)
        history = await _seed_task_history(postgres_session, task, "node-a")
        for start in (0, 100, 200, 300):
            await _insert_log_chunk(
                postgres_session, history.id, start=start, end=start + 100
            )
        await postgres_session.commit()

        deleted = await TaskHistoryLogManager.delete_chunks_below_offset(
            postgres_session,
            task_history_id=history.id,
            source="run-script",
            stream=TaskLogType.STDOUT,
            max_end_offset=200,
            max_rows=1,
        )
        await postgres_session.commit()

        assert deleted == 1
        assert await _stream_end_offsets(postgres_session, history.id) == [
            200,
            300,
            400,
        ]
