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

"""Define tests for the CeleryExecutor."""

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.tasks.crud import TaskHistoryManager, TaskManager
from app.tasks.execution.executors.celery.models import CeleryExecutor
from app.tasks.models import (
    Task,
    TaskBackendEnum,
    TaskExecutionRequest,
    TaskHistory,
    TaskHistoryStatusEnum,
    TaskWrite,
)
from tests.app.factories import TaskFactory


@pytest.fixture
def executor() -> CeleryExecutor:
    """Return a CeleryExecutor instance."""
    return CeleryExecutor()


@pytest_asyncio.fixture
async def celery_task(session) -> Task:
    """Return a persisted CELERY backend task."""
    return await TaskManager.create(
        session,
        TaskWrite.model_validate(
            TaskFactory.build(
                name="celery-task",
                backend=TaskBackendEnum.CELERY,
                data={
                    "callable": "tests.app.tasks.execution.executors.celery.test_models.sample_callable",
                    "target": "local",
                },
            )
        ),
    )


@pytest_asyncio.fixture
async def celery_queue_item(session, celery_task) -> TaskHistory:
    """Return a pending TaskHistory for the celery_task fixture."""
    history = TaskHistory(
        task_id=celery_task.id,
        task=celery_task,
        execution_request=TaskExecutionRequest(
            task=celery_task.name,
            target="local",
            meta={},
            tracking={"evaluation_id": ""},
        ),
        status=TaskHistoryStatusEnum.PENDING,
        executed_by="test-user",
    )
    saved = await TaskHistoryManager.save(session, history)
    return await TaskHistoryManager.get_or_404(
        session, select_related=(TaskHistory.task,), id=saved.id
    )


async def sample_callable() -> str:
    """Return a sample result for testing."""
    return "sync completed"


class TestCeleryExecutorGetHosts:
    """Test CeleryExecutor.get_hosts."""

    def test_returns_local_host(self, executor) -> None:
        """Assert get_hosts returns a local host entry."""
        hosts = executor.get_hosts()
        assert "local" in hosts
        assert hosts["local"] == "localhost"


class TestCeleryExecutorValidateJob:
    """Test CeleryExecutor.validate_job."""

    @pytest.mark.asyncio
    async def test_valid_callable_path(self, executor) -> None:
        """Assert a valid callable path passes validation."""
        job = {
            "callable": "tests.app.tasks.execution.executors.celery.test_models.sample_callable"
        }
        result = await executor.validate_job(job)
        assert result == job

    @pytest.mark.asyncio
    async def test_missing_callable_raises(self, executor) -> None:
        """Assert missing callable key raises ValueError."""
        with pytest.raises(ValueError, match="callable"):
            await executor.validate_job({})

    @pytest.mark.asyncio
    async def test_non_importable_callable_raises(self, executor) -> None:
        """Assert a non-importable callable path raises ValueError."""
        job = {"callable": "nonexistent.module.func"}
        with pytest.raises(ValueError, match="import"):
            await executor.validate_job(job)


class TestCeleryExecutorDispatchTask:
    """Test CeleryExecutor.dispatch_task."""

    @pytest.mark.asyncio
    async def test_successful_dispatch(
        self, executor, session, celery_queue_item
    ) -> None:
        """Assert successful dispatch updates status to SUCCESS."""
        with patch.object(
            executor,
            "_run_callable",
            new_callable=AsyncMock,
            return_value="done",
        ):
            result = await executor.dispatch_task(session, celery_queue_item)
        assert result.status == TaskHistoryStatusEnum.SUCCESS
        assert result.started_at is not None
        assert result.finished_at is not None

    @pytest.mark.asyncio
    async def test_failed_dispatch(self, executor, session, celery_queue_item) -> None:
        """Assert failed callable updates status to FAILED."""
        with patch.object(
            executor,
            "_run_callable",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            result = await executor.dispatch_task(session, celery_queue_item)
        assert result.status == TaskHistoryStatusEnum.FAILED
        assert result.finished_at is not None

    @pytest.mark.asyncio
    async def test_dispatch_stores_logs(
        self, executor, session, celery_queue_item
    ) -> None:
        """Assert dispatch stores captured logs in tracking."""
        with patch.object(
            executor,
            "_run_callable",
            new_callable=AsyncMock,
            return_value="output data",
        ):
            result = await executor.dispatch_task(session, celery_queue_item)
        task_logs = result.execution_request.tracking.get("task_logs", {})
        assert task_logs


class TestCeleryExecutorSyncTaskHistory:
    """Test CeleryExecutor._sync_task_history."""

    @pytest.mark.asyncio
    async def test_returns_unchanged(self, executor) -> None:
        """Assert _sync_task_history returns the queue_item unchanged."""
        queue_item = TaskHistory(
            task_id=1,
            execution_request=TaskExecutionRequest(
                task="test", target="local", tracking={}
            ),
            status=TaskHistoryStatusEnum.SUCCESS,
        )
        result = await executor._sync_task_history(queue_item)
        assert result is queue_item


class TestCeleryExecutorStopTask:
    """Test CeleryExecutor._stop_task."""

    @pytest.mark.asyncio
    async def test_stop_is_noop(self, executor) -> None:
        """Assert _stop_task does not raise."""
        queue_item = TaskHistory(
            task_id=1,
            execution_request=TaskExecutionRequest(
                task="test", target="local", tracking={}
            ),
            status=TaskHistoryStatusEnum.RUNNING,
        )
        await executor._stop_task(queue_item)


class TestCeleryExecutorStreamLogs:
    """Test CeleryExecutor.stream_logs."""

    @pytest.mark.asyncio
    async def test_streams_stored_logs(self, executor) -> None:
        """Assert stream_logs yields from stored task_logs."""
        queue_item = TaskHistory(
            task_id=1,
            execution_request=TaskExecutionRequest(
                task="test",
                target="local",
                tracking={
                    "task_logs": {"execution": {"stdout": "hello world", "stderr": ""}}
                },
            ),
            status=TaskHistoryStatusEnum.SUCCESS,
        )
        logs = [log async for log in executor.stream_logs(queue_item)]
        assert len(logs) > 0
        stdout_logs = [entry for entry in logs if entry.type == "stdout" and entry.msg]
        assert any("hello world" in entry.msg for entry in stdout_logs)


class TestCeleryExecutorUnsupportedOps:
    """Test CeleryExecutor unsupported operations."""

    @pytest.mark.asyncio
    async def test_stream_file_raises(self, executor) -> None:
        """Assert stream_file raises NotImplementedError."""
        queue_item = TaskHistory(
            task_id=1,
            execution_request=TaskExecutionRequest(
                task="test", target="local", tracking={}
            ),
            status=TaskHistoryStatusEnum.SUCCESS,
        )
        with pytest.raises(NotImplementedError):
            await executor.stream_file(queue_item, "/path").__anext__()

    @pytest.mark.asyncio
    async def test_list_files_raises(self, executor) -> None:
        """Assert list_files raises NotImplementedError."""
        queue_item = TaskHistory(
            task_id=1,
            execution_request=TaskExecutionRequest(
                task="test", target="local", tracking={}
            ),
            status=TaskHistoryStatusEnum.SUCCESS,
        )
        with pytest.raises(NotImplementedError):
            await executor.list_files(queue_item, "/path")
