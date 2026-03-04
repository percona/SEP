"""Define tests for the app.tasks.execution.models module."""

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks.execution.models import BaseExecutor
from app.tasks.models import (
    FileMetadata,
    TaskHistory,
    TaskHistoryStatusEnum,
    TaskLog,
)


class ConcreteExecutor(BaseExecutor):
    """Provide a minimal concrete implementation of BaseExecutor for testing."""

    async def dispatch_task(
        self,
        session: Any,
        queue_item: TaskHistory,
        task: Any = None,
    ) -> TaskHistory:
        """Return the queue item unchanged."""
        return queue_item

    async def _stop_task(self, queue_item: TaskHistory) -> None:
        """Do nothing."""

    async def validate_job(self, job: dict[str, Any]) -> dict[str, Any]:
        """Return the job unchanged."""
        return job

    def get_hosts(self) -> dict[str, str]:
        """Return an empty host map."""
        return {}

    async def stream_logs(
        self,
        queue_item: TaskHistory,
        start_offsets: dict[str, dict[str, int]] | None = None,
    ) -> AsyncGenerator[TaskLog, None]:
        """Yield nothing."""
        return
        yield

    async def stream_file(
        self, queue_item: TaskHistory, path: str, chunk_size: int = 1024 * 1024
    ) -> AsyncGenerator[bytes, None]:
        """Yield nothing."""
        return
        yield

    async def list_files(
        self, queue_item: TaskHistory, path: str
    ) -> dict[str, FileMetadata]:
        """Return an empty file listing."""
        return {}

    async def _sync_task_history(self, queue_item: TaskHistory) -> TaskHistory:
        """Return the queue item unchanged."""
        return queue_item


@pytest.fixture
def executor() -> ConcreteExecutor:
    """Create a ConcreteExecutor instance."""
    return ConcreteExecutor()


class TestTransformPayload:
    """Test BaseExecutor.transform_payload."""

    @pytest.mark.asyncio
    async def test_calls_parse_then_validate(self, executor: ConcreteExecutor):
        """Assert transform_payload calls parse_payload then validate_job."""
        parsed = {"key": "value"}
        validated = {"key": "value", "validated": True}
        mock_parse = AsyncMock(return_value=parsed)
        mock_validate = AsyncMock(return_value=validated)

        with (
            patch.object(ConcreteExecutor, "parse_payload", mock_parse),
            patch.object(ConcreteExecutor, "validate_job", mock_validate),
        ):
            result = await executor.transform_payload('{"key": "value"}', "json")

        mock_parse.assert_awaited_once_with('{"key": "value"}', "json")
        mock_validate.assert_awaited_once_with(parsed)
        assert result == validated

    @pytest.mark.asyncio
    async def test_returns_validate_job_result(self, executor: ConcreteExecutor):
        """Assert transform_payload returns the result of validate_job."""
        expected = {"result": "validated"}

        with (
            patch.object(ConcreteExecutor, "parse_payload", AsyncMock(return_value={})),
            patch.object(
                ConcreteExecutor, "validate_job", AsyncMock(return_value=expected)
            ),
        ):
            result = await executor.transform_payload("{}", "json")

        assert result == expected


class TestParsePayload:
    """Test BaseExecutor.parse_payload."""

    @pytest.mark.asyncio
    async def test_delegates_to_utils_parse_payload(self, executor: ConcreteExecutor):
        """Assert parse_payload delegates to utils.parse_payload."""
        with patch(
            "app.tasks.execution.models.parse_payload",
            return_value={"parsed": True},
        ) as mock_parse:
            result = await executor.parse_payload('{"parsed": true}', "json")

        mock_parse.assert_called_once_with('{"parsed": true}', "json")
        assert result == {"parsed": True}


class TestStopTask:
    """Test BaseExecutor.stop_task."""

    @pytest.mark.asyncio
    async def test_sets_stopped_status_and_finished_at(
        self, executor: ConcreteExecutor
    ):
        """Assert stop_task sets status to STOPPED and sets finished_at."""
        queue_item = MagicMock(spec=TaskHistory)
        queue_item.task = MagicMock()
        queue_item.task.alert_on_fail = False
        session = AsyncMock()
        mock_stop = AsyncMock()
        mock_sync = AsyncMock(return_value=queue_item)

        with (
            patch.object(ConcreteExecutor, "_stop_task", mock_stop),
            patch.object(ConcreteExecutor, "_sync_task_history", mock_sync),
            patch(
                "app.tasks.execution.models.TaskHistoryManager.save",
                new_callable=AsyncMock,
                return_value=queue_item,
            ) as mock_save,
        ):
            result = await executor.stop_task(session, queue_item)

        mock_stop.assert_awaited_once_with(queue_item)
        assert queue_item.status == TaskHistoryStatusEnum.STOPPED
        assert queue_item.finished_at is not None
        mock_save.assert_awaited_once_with(session, queue_item)
        assert result is queue_item

    @pytest.mark.asyncio
    async def test_calls_sync_task_history(self, executor: ConcreteExecutor):
        """Assert stop_task calls sync_task_history before setting status."""
        queue_item = MagicMock(spec=TaskHistory)
        queue_item.task = MagicMock()
        queue_item.task.alert_on_fail = False
        session = AsyncMock()
        mock_sync = AsyncMock(return_value=queue_item)

        with (
            patch.object(ConcreteExecutor, "_stop_task", AsyncMock()),
            patch.object(ConcreteExecutor, "_sync_task_history", mock_sync),
            patch(
                "app.tasks.execution.models.TaskHistoryManager.save",
                new_callable=AsyncMock,
                return_value=queue_item,
            ),
        ):
            await executor.stop_task(session, queue_item)

        mock_sync.assert_awaited_once()


class TestSyncTaskHistory:
    """Test BaseExecutor.sync_task_history."""

    @pytest.mark.asyncio
    async def test_calls_internal_sync(self, executor: ConcreteExecutor):
        """Assert sync_task_history calls _sync_task_history."""
        queue_item = MagicMock(spec=TaskHistory)
        queue_item.task = MagicMock()
        queue_item.task.alert_on_fail = False
        mock_sync = AsyncMock(return_value=queue_item)

        with patch.object(ConcreteExecutor, "_sync_task_history", mock_sync):
            result = await executor.sync_task_history(queue_item)

        mock_sync.assert_awaited_once_with(queue_item)
        assert result is queue_item

    @pytest.mark.asyncio
    async def test_alerts_when_alert_on_fail_is_true(self, executor: ConcreteExecutor):
        """Assert alert_for_status is called when task.alert_on_fail is True."""
        queue_item = MagicMock(spec=TaskHistory)
        queue_item.task = MagicMock()
        queue_item.task.alert_on_fail = True
        queue_item.alert_for_status = AsyncMock()

        with patch.object(
            ConcreteExecutor, "_sync_task_history", AsyncMock(return_value=queue_item)
        ):
            await executor.sync_task_history(queue_item)

        queue_item.alert_for_status.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_does_not_alert_when_alert_on_fail_is_false(
        self, executor: ConcreteExecutor
    ):
        """Assert alert_for_status is not called when task.alert_on_fail is False."""
        queue_item = MagicMock(spec=TaskHistory)
        queue_item.task = MagicMock()
        queue_item.task.alert_on_fail = False
        queue_item.alert_for_status = AsyncMock()

        with patch.object(
            ConcreteExecutor, "_sync_task_history", AsyncMock(return_value=queue_item)
        ):
            await executor.sync_task_history(queue_item)

        queue_item.alert_for_status.assert_not_awaited()


_DEFAULT_WAIT_INTERVAL = 5


class TestDefaultWaitInterval:
    """Test BaseExecutor default configuration."""

    def test_default_wait_interval(self, executor: ConcreteExecutor):
        """Assert default wait_interval is 5 seconds."""
        assert executor.wait_interval == _DEFAULT_WAIT_INTERVAL
