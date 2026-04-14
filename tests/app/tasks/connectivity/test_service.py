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

"""Test the connectivity check service function."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.tasks.connectivity.models import (
    ConnectivityCheckWrite,
    ConnectivityServiceType,
)
from app.tasks.connectivity.service import (
    _parse_check_result,
    check_connectivity,
    POLL_INTERVAL,
)
from app.tasks.execution.models import BaseExecutor
from app.tasks.models import (
    TaskHistory,
    TaskHistoryStatusEnum,
    TaskLogType,
)

MOCK_TASK_HISTORY_ID = 42


def _make_task(name: str = "run-python") -> MagicMock:
    """Build a mock Task with the given name."""
    task = MagicMock()
    task.id = 1
    task.name = name
    task.backend = "nomad"
    task.alert_on_fail = False
    return task


def _make_request(
    service_type: ConnectivityServiceType = ConnectivityServiceType.MYSQL,
    timeout: int = 30,
) -> ConnectivityCheckWrite:
    """Build a ConnectivityCheckWrite request."""
    return ConnectivityCheckWrite(
        target="node1",
        host="db-host",
        port=3306,
        service_type=service_type,
        timeout=timeout,
    )


def _make_task_history(
    task_history_status: TaskHistoryStatusEnum = TaskHistoryStatusEnum.SUCCESS,
    stdout: str = "",
    stderr: str = "",
) -> TaskHistory:
    """Build a TaskHistory with in-memory logs."""
    task = _make_task()
    history = MagicMock()
    history.id = MOCK_TASK_HISTORY_ID
    history.status = task_history_status
    history.task = task

    logs = {}
    if stdout or stderr:
        log_data = {}
        if stdout:
            log_data[TaskLogType.STDOUT] = stdout
        if stderr:
            log_data[TaskLogType.STDERR] = stderr
        logs["run-script"] = log_data

    history.task_logs = logs

    def iter_logs_impl(start_offsets=None, chunk_size=65536, step=None):
        from itertools import product

        from app.tasks.models import TaskLog, TaskLogType

        task_logs = logs
        if step is not None:
            task_logs = {step: task_logs.get(step, {})}
        for (cur_step, log), log_type in product(task_logs.items(), TaskLogType):
            msg = log.get(log_type) or ""
            for chunk_start in range(0, len(msg), chunk_size):
                chunk_end = chunk_start + chunk_size
                yield TaskLog(
                    step=cur_step,
                    type=log_type,
                    msg=msg[chunk_start:chunk_end],
                    offset=chunk_end,
                )

    history.iter_logs = iter_logs_impl
    return history


@pytest.mark.asyncio
class TestCheckConnectivity:
    """Test the check_connectivity service function."""

    @pytest.mark.parametrize(
        "service_type",
        list(ConnectivityServiceType),
        ids=[st.value for st in ConnectivityServiceType],
    )
    async def test_success(self, service_type):
        """Verify successful connectivity check for each service type."""
        session = AsyncMock(spec=AsyncSession)
        task = _make_task()
        request = _make_request(service_type=service_type)

        completed_history = _make_task_history(
            task_history_status=TaskHistoryStatusEnum.SUCCESS,
            stdout=json.dumps({"success": True}),
        )

        mock_executor = AsyncMock(spec=BaseExecutor)

        async def mock_dispatch(queue_item, sess):
            queue_item.id = MOCK_TASK_HISTORY_ID
            queue_item.status = TaskHistoryStatusEnum.RUNNING
            return queue_item

        async def mock_sync(queue_item):
            return completed_history

        mock_executor.sync_task_history = mock_sync

        with (
            patch(
                "app.tasks.connectivity.service.get_executable_task_by_name",
                new=AsyncMock(return_value=task),
            ),
            patch(
                "app.tasks.connectivity.service.dispatch_queue_item",
                side_effect=mock_dispatch,
            ),
            patch(
                "app.tasks.connectivity.service.get_executor_for_task",
                return_value=mock_executor,
            ),
            patch(
                "app.tasks.connectivity.service.TaskHistoryManager.save",
                new=AsyncMock(return_value=completed_history),
            ),
            patch("app.tasks.connectivity.service.asyncio.sleep", new=AsyncMock()),
        ):
            result = await check_connectivity(session, request)

        assert result.success is True
        assert result.error is None
        assert result.task_history_id == MOCK_TASK_HISTORY_ID

    async def test_failure_connection_refused(self):
        """Verify failed check when the database connection is refused."""
        session = AsyncMock(spec=AsyncSession)
        task = _make_task()
        request = _make_request()

        completed_history = _make_task_history(
            task_history_status=TaskHistoryStatusEnum.SUCCESS,
            stdout=json.dumps({"success": False, "error": "Connection refused"}),
        )

        mock_executor = AsyncMock(spec=BaseExecutor)

        async def mock_dispatch(queue_item, sess):
            queue_item.id = MOCK_TASK_HISTORY_ID
            queue_item.status = TaskHistoryStatusEnum.RUNNING
            return queue_item

        async def mock_sync(queue_item):
            return completed_history

        mock_executor.sync_task_history = mock_sync

        with (
            patch(
                "app.tasks.connectivity.service.get_executable_task_by_name",
                new=AsyncMock(return_value=task),
            ),
            patch(
                "app.tasks.connectivity.service.dispatch_queue_item",
                side_effect=mock_dispatch,
            ),
            patch(
                "app.tasks.connectivity.service.get_executor_for_task",
                return_value=mock_executor,
            ),
            patch(
                "app.tasks.connectivity.service.TaskHistoryManager.save",
                new=AsyncMock(return_value=completed_history),
            ),
            patch("app.tasks.connectivity.service.asyncio.sleep", new=AsyncMock()),
        ):
            result = await check_connectivity(session, request)

        assert result.success is False
        assert result.error == "Connection refused"

    async def test_failure_task_failed_status(self):
        """Verify handling when the Nomad task itself fails."""
        session = AsyncMock(spec=AsyncSession)
        task = _make_task()
        request = _make_request()

        completed_history = _make_task_history(
            task_history_status=TaskHistoryStatusEnum.FAILED,
            stderr="ImportError: No module named 'pymysql'",
        )

        mock_executor = AsyncMock(spec=BaseExecutor)

        async def mock_dispatch(queue_item, sess):
            queue_item.id = MOCK_TASK_HISTORY_ID
            queue_item.status = TaskHistoryStatusEnum.RUNNING
            return queue_item

        async def mock_sync(queue_item):
            return completed_history

        mock_executor.sync_task_history = mock_sync

        with (
            patch(
                "app.tasks.connectivity.service.get_executable_task_by_name",
                new=AsyncMock(return_value=task),
            ),
            patch(
                "app.tasks.connectivity.service.dispatch_queue_item",
                side_effect=mock_dispatch,
            ),
            patch(
                "app.tasks.connectivity.service.get_executor_for_task",
                return_value=mock_executor,
            ),
            patch(
                "app.tasks.connectivity.service.TaskHistoryManager.save",
                new=AsyncMock(return_value=completed_history),
            ),
            patch("app.tasks.connectivity.service.asyncio.sleep", new=AsyncMock()),
        ):
            result = await check_connectivity(session, request)

        assert result.success is False
        assert "No module named" in result.error

    async def test_timeout(self):
        """Verify timeout when the task stays running past the deadline."""
        session = AsyncMock(spec=AsyncSession)
        task = _make_task()
        request = _make_request(timeout=POLL_INTERVAL)

        mock_executor = AsyncMock(spec=BaseExecutor)

        async def mock_dispatch(queue_item, sess):
            queue_item.id = MOCK_TASK_HISTORY_ID
            queue_item.status = TaskHistoryStatusEnum.RUNNING
            return queue_item

        async def mock_sync(queue_item):
            return queue_item

        mock_executor.sync_task_history = mock_sync

        with (
            patch(
                "app.tasks.connectivity.service.get_executable_task_by_name",
                new=AsyncMock(return_value=task),
            ),
            patch(
                "app.tasks.connectivity.service.dispatch_queue_item",
                side_effect=mock_dispatch,
            ),
            patch(
                "app.tasks.connectivity.service.get_executor_for_task",
                return_value=mock_executor,
            ),
            patch(
                "app.tasks.connectivity.service.TaskHistoryManager.save",
                new=AsyncMock(),
            ),
            patch("app.tasks.connectivity.service.asyncio.sleep", new=AsyncMock()),
        ):
            result = await check_connectivity(session, request)

        assert result.success is False
        assert "timed out" in result.error

    async def test_malformed_stdout(self):
        """Verify handling when task output is not valid JSON."""
        session = AsyncMock(spec=AsyncSession)
        task = _make_task()
        request = _make_request()

        completed_history = _make_task_history(
            task_history_status=TaskHistoryStatusEnum.SUCCESS,
            stdout="not valid json",
        )

        mock_executor = AsyncMock(spec=BaseExecutor)

        async def mock_dispatch(queue_item, sess):
            queue_item.id = MOCK_TASK_HISTORY_ID
            queue_item.status = TaskHistoryStatusEnum.RUNNING
            return queue_item

        async def mock_sync(queue_item):
            return completed_history

        mock_executor.sync_task_history = mock_sync

        with (
            patch(
                "app.tasks.connectivity.service.get_executable_task_by_name",
                new=AsyncMock(return_value=task),
            ),
            patch(
                "app.tasks.connectivity.service.dispatch_queue_item",
                side_effect=mock_dispatch,
            ),
            patch(
                "app.tasks.connectivity.service.get_executor_for_task",
                return_value=mock_executor,
            ),
            patch(
                "app.tasks.connectivity.service.TaskHistoryManager.save",
                new=AsyncMock(return_value=completed_history),
            ),
            patch("app.tasks.connectivity.service.asyncio.sleep", new=AsyncMock()),
        ):
            result = await check_connectivity(session, request)

        assert result.success is False
        assert result.error == "Failed to parse connectivity check output"

    async def test_failure_logs_arrive_after_status_transition(self):
        """Verify stderr logs are captured when they land after status change.

        Reproduces a Nomad race where ``sync_task_history`` transitions the
        task to ``FAILED`` on one call with empty logs, and only on a
        subsequent sync returns the populated stderr. The service must
        perform a final sync before parsing so the real error is surfaced
        instead of the generic ``"Task failed"``.
        """
        session = AsyncMock(spec=AsyncSession)
        task = _make_task()
        request = _make_request()

        failed_empty_history = _make_task_history(
            task_history_status=TaskHistoryStatusEnum.FAILED,
        )
        failed_with_stderr_history = _make_task_history(
            task_history_status=TaskHistoryStatusEnum.FAILED,
            stderr="Traceback: JSONDecodeError: Expecting value",
        )

        mock_executor = AsyncMock(spec=BaseExecutor)

        async def mock_dispatch(queue_item, sess):
            queue_item.id = MOCK_TASK_HISTORY_ID
            queue_item.status = TaskHistoryStatusEnum.RUNNING
            return queue_item

        sync_results = iter([failed_empty_history, failed_with_stderr_history])

        async def mock_sync(queue_item):
            return next(sync_results)

        mock_executor.sync_task_history = mock_sync

        with (
            patch(
                "app.tasks.connectivity.service.get_executable_task_by_name",
                new=AsyncMock(return_value=task),
            ),
            patch(
                "app.tasks.connectivity.service.dispatch_queue_item",
                side_effect=mock_dispatch,
            ),
            patch(
                "app.tasks.connectivity.service.get_executor_for_task",
                return_value=mock_executor,
            ),
            patch(
                "app.tasks.connectivity.service.TaskHistoryManager.save",
                new=AsyncMock(),
            ),
            patch("app.tasks.connectivity.service.asyncio.sleep", new=AsyncMock()),
        ):
            result = await check_connectivity(session, request)

        assert result.success is False
        assert "JSONDecodeError" in result.error

    async def test_success_logs_arrive_after_status_transition(self):
        """Verify stdout is captured when it lands after status change.

        Same Nomad race as the FAILED case but for the happy path: the first
        sync transitions to ``SUCCESS`` with empty stdout, and only the next
        sync returns the JSON result. Without a final sync the service would
        wrongly report ``"Failed to parse connectivity check output"``.
        """
        session = AsyncMock(spec=AsyncSession)
        task = _make_task()
        request = _make_request()

        success_empty_history = _make_task_history(
            task_history_status=TaskHistoryStatusEnum.SUCCESS,
        )
        success_with_stdout_history = _make_task_history(
            task_history_status=TaskHistoryStatusEnum.SUCCESS,
            stdout=json.dumps({"success": True}),
        )

        mock_executor = AsyncMock(spec=BaseExecutor)

        async def mock_dispatch(queue_item, sess):
            queue_item.id = MOCK_TASK_HISTORY_ID
            queue_item.status = TaskHistoryStatusEnum.RUNNING
            return queue_item

        sync_results = iter([success_empty_history, success_with_stdout_history])

        async def mock_sync(queue_item):
            return next(sync_results)

        mock_executor.sync_task_history = mock_sync

        with (
            patch(
                "app.tasks.connectivity.service.get_executable_task_by_name",
                new=AsyncMock(return_value=task),
            ),
            patch(
                "app.tasks.connectivity.service.dispatch_queue_item",
                side_effect=mock_dispatch,
            ),
            patch(
                "app.tasks.connectivity.service.get_executor_for_task",
                return_value=mock_executor,
            ),
            patch(
                "app.tasks.connectivity.service.TaskHistoryManager.save",
                new=AsyncMock(),
            ),
            patch("app.tasks.connectivity.service.asyncio.sleep", new=AsyncMock()),
        ):
            result = await check_connectivity(session, request)

        assert result.success is True
        assert result.error is None
        assert result.task_history_id == MOCK_TASK_HISTORY_ID

    async def test_task_stays_pending(self):
        """Verify timeout when the task never transitions from pending."""
        session = AsyncMock(spec=AsyncSession)
        task = _make_task()
        request = _make_request(timeout=POLL_INTERVAL)

        async def mock_dispatch(queue_item, sess):
            queue_item.id = MOCK_TASK_HISTORY_ID
            queue_item.status = TaskHistoryStatusEnum.PENDING
            return queue_item

        mock_executor = AsyncMock(spec=BaseExecutor)

        async def mock_sync(queue_item):
            return queue_item

        mock_executor.sync_task_history = mock_sync

        with (
            patch(
                "app.tasks.connectivity.service.get_executable_task_by_name",
                new=AsyncMock(return_value=task),
            ),
            patch(
                "app.tasks.connectivity.service.dispatch_queue_item",
                side_effect=mock_dispatch,
            ),
            patch(
                "app.tasks.connectivity.service.get_executor_for_task",
                return_value=mock_executor,
            ),
            patch(
                "app.tasks.connectivity.service.TaskHistoryManager.save",
                new=AsyncMock(),
            ),
            patch("app.tasks.connectivity.service.asyncio.sleep", new=AsyncMock()),
        ):
            result = await check_connectivity(session, request)

        assert result.success is False
        assert "timed out" in result.error


class TestParseCheckResult:
    """Test the _parse_check_result helper."""

    def test_success_result(self):
        """Verify successful result parsed from stdout JSON."""
        history = _make_task_history(
            task_history_status=TaskHistoryStatusEnum.SUCCESS,
            stdout=json.dumps({"success": True}),
        )
        result = _parse_check_result(history)
        assert result.success is True
        assert result.error is None

    def test_failure_result_with_error(self):
        """Verify failure result with error message from stdout JSON."""
        history = _make_task_history(
            task_history_status=TaskHistoryStatusEnum.SUCCESS,
            stdout=json.dumps({"success": False, "error": "Access denied"}),
        )
        result = _parse_check_result(history)
        assert result.success is False
        assert result.error == "Access denied"

    def test_failed_status_with_stderr(self):
        """Verify stderr is returned as error when task status is FAILED."""
        history = _make_task_history(
            task_history_status=TaskHistoryStatusEnum.FAILED,
            stderr="Traceback: module not found",
        )
        result = _parse_check_result(history)
        assert result.success is False
        assert "module not found" in result.error

    def test_failed_status_without_stderr(self):
        """Verify default error message when FAILED task has no stderr."""
        history = _make_task_history(
            task_history_status=TaskHistoryStatusEnum.FAILED,
        )
        result = _parse_check_result(history)
        assert result.success is False
        assert result.error == "Task failed"

    def test_empty_stdout(self):
        """Verify parse error when stdout is empty."""
        history = _make_task_history(
            task_history_status=TaskHistoryStatusEnum.SUCCESS,
            stdout="",
        )
        result = _parse_check_result(history)
        assert result.success is False
        assert result.error == "Failed to parse connectivity check output"

    def test_malformed_json(self):
        """Verify parse error when stdout contains invalid JSON."""
        history = _make_task_history(
            task_history_status=TaskHistoryStatusEnum.SUCCESS,
            stdout="{{invalid json",
        )
        result = _parse_check_result(history)
        assert result.success is False
        assert result.error == "Failed to parse connectivity check output"
