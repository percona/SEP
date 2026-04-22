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

"""Define regression tests for PMM task annotations (SEP-1009, SEP-1021)."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import undefer
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.pmm import _background_tasks, schedule_annotation
from app.tasks.crud import TaskHistoryManager, TaskManager
from app.tasks.models import (
    TaskExecutionRequest,
    TaskHistory,
    TaskHistoryStatusEnum,
    TaskWrite,
)
from tests.app.factories import TaskFactory
from tests.app.tasks.execution.test_models import ConcreteExecutor


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


class _SuccessAfterRunExecutor(ConcreteExecutor):
    """Minimal executor that marks the task history as SUCCESS in _sync_task_history."""

    async def _sync_task_history(
        self,
        queue_item: TaskHistory,
        writer_session: AsyncSession | None = None,
    ) -> TaskHistory:
        queue_item.status = TaskHistoryStatusEnum.SUCCESS
        return queue_item


class TestSyncTaskHistoryPmmRegressionSep1021:
    """Test terminal PMM on a detached TaskHistory with a separate writer session."""

    @pytest.mark.asyncio
    async def test_detached_item_terminal_pmm_with_writer_session(
        self, session: AsyncSession
    ) -> None:
        """Assert schedule_annotation survives the load→writer session boundary.

        Reproduce the SEP-1021 production flow: ``sync_queue_item`` loads the
        ``TaskHistory`` with ``undefer(TaskHistory.execution_request)`` in a
        reader session, closes that session, then calls
        ``executor.sync_task_history(queue_item, writer_session=...)`` inside
        a fresh writer session. Without the fix, ``schedule_annotation``
        reads the deferred column through the attribute getter across the
        session boundary and raises ``MissingGreenlet`` on async drivers,
        aborting ``sync_task_history`` before chain dispatch is reached.

        Patch ``create_pmm_annotation`` (the HTTP boundary) so the real
        ``schedule_annotation`` — and therefore ``execution_request_for_pmm_snapshot``
        — run, and assert the background annotation fires with the
        primitives captured from the detached instance.
        """
        task = await TaskManager.create(
            session,
            TaskWrite.model_validate(TaskFactory.build(name="sep1021-pmm-chain")),
        )
        history = TaskHistory(
            task_id=task.id,
            task=task,
            execution_request=TaskExecutionRequest(
                task=task.name,
                target="node-z",
                meta={"_service_names": ["svc1"]},
                tracking={},
            ),
            status=TaskHistoryStatusEnum.RUNNING,
        )
        saved = await TaskHistoryManager.save(session, history)
        await session.commit()

        engine = session.bind
        if engine is None:
            raise RuntimeError("expected AsyncSession.bind to be set")
        maker = get_async_session_maker_from_engine(engine)
        async with maker() as load_session:
            loaded = await TaskHistoryManager.get_or_404(
                load_session,
                select_related=[TaskHistory.task],
                query_options=[undefer(TaskHistory.execution_request)],
                id=saved.id,
            )

        _background_tasks.clear()
        async with maker() as writer_session:
            executor = _SuccessAfterRunExecutor()
            with patch(
                "app.core.pmm.create_pmm_annotation", new_callable=AsyncMock
            ) as mock_create:
                await executor.sync_task_history(loaded, writer_session=writer_session)
                for bg_task in list(_background_tasks):
                    await bg_task

        assert loaded.status == TaskHistoryStatusEnum.SUCCESS
        mock_create.assert_awaited_once_with(
            text=f"SEP {task.name} - COMPLETED",
            node_name="node-z",
            tags=["sep", task.name, "completed"],
            service_names=["svc1"],
        )
