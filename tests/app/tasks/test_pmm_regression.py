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

"""Regression tests for SEP-1009.

PMM annotation must not touch ORM attributes after the originating
session has closed.
"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import undefer
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.pmm import _background_tasks, schedule_annotation
from app.tasks.crud import TaskHistoryManager, TaskManager
from app.tasks.models import (
    TaskExecutionRequest,
    TaskHistory,
    TaskHistoryStatusEnum,
    TaskWrite,
)
from tests.app.factories import TaskFactory


class TestScheduleAnnotationDetachedInstance:
    """Regression suite for SEP-1009."""

    @pytest.mark.asyncio
    async def test_safe_after_session_close(self, session: AsyncSession):
        """Assert the background task does not touch the ORM after close.

        Reproduce the production caller pattern: fetch a real
        ``TaskHistory`` with ``undefer(TaskHistory.execution_request)``
        so the deferred column is loaded, schedule an annotation, close
        the session, then drain the background tasks.

        With the fix, the primitives are snapshotted synchronously
        before ``asyncio.create_task`` and the background coroutine
        never touches the ORM. Without the fix, the background task
        accesses ``queue_item.execution_request.meta`` after the
        session has closed and expired the attribute, raising
        ``DetachedInstanceError`` (sync driver) or
        ``sqlalchemy.exc.MissingGreenlet`` (asyncpg) — the production
        failure mode captured in the SEP-1009 sep.log traceback.
        """
        task = await TaskManager.create(
            session,
            TaskWrite.model_validate(TaskFactory.build(name="backup_data")),
        )
        history = TaskHistory(
            task_id=task.id,
            task=task,
            execution_request=TaskExecutionRequest(
                task="backup_data",
                target="node-1",
                meta={"_service_names": ["svc1"]},
            ),
            status=TaskHistoryStatusEnum.RUNNING,
        )
        saved = await TaskHistoryManager.save(session, history)

        fetched = await TaskHistoryManager.get_or_404(
            session,
            query_options=[undefer(TaskHistory.execution_request)],
            id=saved.id,
        )

        _background_tasks.clear()
        with patch(
            "app.core.pmm.create_pmm_annotation", new_callable=AsyncMock
        ) as mock_create:
            schedule_annotation(fetched, "STARTED")
            session.sync_session.expire(fetched)
            await session.close()

            for bg_task in list(_background_tasks):
                await bg_task

        mock_create.assert_awaited_once_with(
            text="SEP backup_data - STARTED",
            node_name="node-1",
            tags=["sep", "backup_data", "started"],
            service_names=["svc1"],
        )
