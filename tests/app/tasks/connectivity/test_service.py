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
from itertools import product
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlmodel.ext.asyncio.session import AsyncSession

from app.tasks.connectivity.models import (
    ConnectivityCheckWrite,
    ConnectivityServiceType,
)
from app.tasks.connectivity.service import (
    _cached_check_connectivity,
    _parse_check_result,
    check_connectivity,
    check_connectivity_with_cache,
    POLL_INTERVAL,
)
from app.tasks.crud import TaskHistoryManager, TaskManager
from app.tasks.execution.models import BaseExecutor
from app.tasks.models import (
    Task,
    TaskBackendEnum,
    TaskHistory,
    TaskHistoryStatusEnum,
    TaskLog,
    TaskLogType,
    TaskWrite,
)
from tests.app.factories import TaskFactory

MOCK_TASK_HISTORY_ID = 42
EXPECTED_INDEPENDENT_CALL_COUNT = 2


@pytest.fixture(autouse=True)
def _clear_connectivity_cache():
    """Clear the ``alru_cache`` before and after every test in this module."""
    _cached_check_connectivity.cache_clear()
    yield
    _cached_check_connectivity.cache_clear()


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

    def iter_logs_impl(_start_offsets=None, chunk_size=65536, step=None):
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

        async def mock_dispatch(queue_item, _session):
            queue_item.id = MOCK_TASK_HISTORY_ID
            queue_item.status = TaskHistoryStatusEnum.RUNNING
            return queue_item

        async def mock_sync(_queue_item):
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
            patch(
                "app.tasks.connectivity.service.TaskHistoryManager.get_or_404",
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

        async def mock_dispatch(queue_item, _session):
            queue_item.id = MOCK_TASK_HISTORY_ID
            queue_item.status = TaskHistoryStatusEnum.RUNNING
            return queue_item

        async def mock_sync(_queue_item):
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
            patch(
                "app.tasks.connectivity.service.TaskHistoryManager.get_or_404",
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

        async def mock_dispatch(queue_item, _session):
            queue_item.id = MOCK_TASK_HISTORY_ID
            queue_item.status = TaskHistoryStatusEnum.RUNNING
            return queue_item

        async def mock_sync(_queue_item):
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
            patch(
                "app.tasks.connectivity.service.TaskHistoryManager.get_or_404",
                new=AsyncMock(return_value=completed_history),
            ),
            patch("app.tasks.connectivity.service.asyncio.sleep", new=AsyncMock()),
        ):
            result = await check_connectivity(session, request)

        assert result.success is False
        assert result.error is not None
        assert "No module named" in result.error

    async def test_timeout(self):
        """Verify timeout when the task stays running past the deadline."""
        session = AsyncMock(spec=AsyncSession)
        task = _make_task()
        request = _make_request(timeout=POLL_INTERVAL)

        mock_executor = AsyncMock(spec=BaseExecutor)

        async def mock_dispatch(queue_item, _session):
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
        assert result.error is not None
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

        async def mock_dispatch(queue_item, _session):
            queue_item.id = MOCK_TASK_HISTORY_ID
            queue_item.status = TaskHistoryStatusEnum.RUNNING
            return queue_item

        async def mock_sync(_queue_item):
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
            patch(
                "app.tasks.connectivity.service.TaskHistoryManager.get_or_404",
                new=AsyncMock(return_value=completed_history),
            ),
            patch("app.tasks.connectivity.service.asyncio.sleep", new=AsyncMock()),
        ):
            result = await check_connectivity(session, request)

        assert result.success is False
        assert result.error == "Failed to parse connectivity check output"

    async def test_failure_logs_arrive_after_status_transition(self):
        """Verify stderr logs are captured when they land after status change.

        Reproduces the Nomad + executor early-return race: ``sync_task_history``
        transitions the in-memory ``queue_item`` to ``FAILED`` with empty logs,
        and the NomadExecutor then refuses to re-fetch logs for a terminal
        task. The service must re-query the DB row where the background
        Celery task has since populated the stderr.
        """
        session = AsyncMock(spec=AsyncSession)
        task = _make_task()
        request = _make_request()

        stale_failed_history = _make_task_history(
            task_history_status=TaskHistoryStatusEnum.FAILED,
        )
        fresh_failed_history = _make_task_history(
            task_history_status=TaskHistoryStatusEnum.FAILED,
            stderr="Traceback: JSONDecodeError: Expecting value",
        )

        mock_executor = AsyncMock(spec=BaseExecutor)

        async def mock_dispatch(queue_item, _session):
            queue_item.id = MOCK_TASK_HISTORY_ID
            queue_item.status = TaskHistoryStatusEnum.RUNNING
            return queue_item

        async def mock_sync(_queue_item):
            # Every executor sync returns the stale (empty-logs) copy,
            # mimicking the early-return in NomadExecutor._sync_task_history.
            return stale_failed_history

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
            patch(
                "app.tasks.connectivity.service.TaskHistoryManager.get_or_404",
                new=AsyncMock(return_value=fresh_failed_history),
            ),
            patch("app.tasks.connectivity.service.asyncio.sleep", new=AsyncMock()),
        ):
            result = await check_connectivity(session, request)

        assert result.success is False
        assert result.error is not None
        assert "JSONDecodeError" in result.error

    async def test_success_logs_arrive_after_status_transition(self):
        """Verify stdout is captured when it lands after status change.

        Same race as the FAILED case but for the happy path: the executor
        reports ``SUCCESS`` with empty stdout, and only the DB row fetched
        via ``TaskHistoryManager.get_or_404`` carries the JSON result.
        """
        session = AsyncMock(spec=AsyncSession)
        task = _make_task()
        request = _make_request()

        stale_success_history = _make_task_history(
            task_history_status=TaskHistoryStatusEnum.SUCCESS,
        )
        fresh_success_history = _make_task_history(
            task_history_status=TaskHistoryStatusEnum.SUCCESS,
            stdout=json.dumps({"success": True}),
        )

        mock_executor = AsyncMock(spec=BaseExecutor)

        async def mock_dispatch(queue_item, _session):
            queue_item.id = MOCK_TASK_HISTORY_ID
            queue_item.status = TaskHistoryStatusEnum.RUNNING
            return queue_item

        async def mock_sync(_queue_item):
            return stale_success_history

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
            patch(
                "app.tasks.connectivity.service.TaskHistoryManager.get_or_404",
                new=AsyncMock(return_value=fresh_success_history),
            ),
            patch("app.tasks.connectivity.service.asyncio.sleep", new=AsyncMock()),
        ):
            result = await check_connectivity(session, request)

        assert result.success is True
        assert result.error is None
        assert result.task_history_id == MOCK_TASK_HISTORY_ID

    async def test_fresh_fetch_retries_until_logs_are_populated(self):
        """Verify the service retries the DB fetch until logs show up.

        The periodic Celery sync may not have updated the DB row by the time
        the service first re-queries it. The service must poll
        ``TaskHistoryManager.get_or_404`` a few times until the
        ``run-script`` stdout is non-empty.
        """
        session = AsyncMock(spec=AsyncSession)
        task = _make_task()
        request = _make_request()

        stale_history = _make_task_history(
            task_history_status=TaskHistoryStatusEnum.SUCCESS,
        )
        empty_refetch = _make_task_history(
            task_history_status=TaskHistoryStatusEnum.SUCCESS,
        )
        populated_refetch = _make_task_history(
            task_history_status=TaskHistoryStatusEnum.SUCCESS,
            stdout=json.dumps({"success": True}),
        )

        mock_executor = AsyncMock(spec=BaseExecutor)

        async def mock_dispatch(queue_item, _session):
            queue_item.id = MOCK_TASK_HISTORY_ID
            queue_item.status = TaskHistoryStatusEnum.RUNNING
            return queue_item

        async def mock_sync(_queue_item):
            return stale_history

        mock_executor.sync_task_history = mock_sync

        refetch_results = iter([empty_refetch, populated_refetch])

        async def mock_get_or_404(*_args, **_kwargs):
            return next(refetch_results)

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
            patch(
                "app.tasks.connectivity.service.TaskHistoryManager.get_or_404",
                side_effect=mock_get_or_404,
            ),
            patch("app.tasks.connectivity.service.asyncio.sleep", new=AsyncMock()),
        ):
            result = await check_connectivity(session, request)

        assert result.success is True
        assert result.error is None

    async def test_task_stays_pending(self):
        """Verify timeout when the task never transitions from pending."""
        session = AsyncMock(spec=AsyncSession)
        task = _make_task()
        request = _make_request(timeout=POLL_INTERVAL)

        async def mock_dispatch(queue_item, _session):
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
        assert result.error is not None
        assert "timed out" in result.error


@pytest.mark.asyncio
class TestCheckConnectivityRealSession:
    """Exercise ``check_connectivity`` against a real ``AsyncSession``.

    The unit tests above use ``AsyncMock(spec=AsyncSession)``, which hides a
    class of greenlet-bridge bugs: the ``execution_request`` column on
    ``TaskHistory`` is declared ``deferred=True`` (``app/tasks/models.py``),
    so a plain ``session.refresh(instance)`` leaves the attribute unloaded.
    If the executor's ``sync_task_history`` path then touches
    ``queue_item.execution_request`` from plain sync code, SQLAlchemy fires
    a lazy-load callable outside the async greenlet and raises
    ``MissingGreenlet``. These tests run the service against a real
    ``aiosqlite`` session so the regression is observable.
    """

    @pytest_asyncio.fixture
    async def run_python_task(self, session: AsyncSession) -> Task:
        """Persist a ``run-python`` task row in the test DB."""
        task_write = TaskWrite.model_validate(
            TaskFactory.build(
                name="run-python",
                backend=TaskBackendEnum.NOMAD,
                is_template=False,
                protected=False,
                alert_on_fail=False,
            )
        )
        return await TaskManager.create(session, task_write)

    async def test_deferred_execution_request_survives_sync_executor(
        self,
        session: AsyncSession,
        run_python_task: Task,
    ) -> None:
        """Verify the polling loop survives the deferred-column lazy-load race.

        Reproduces the runtime bug surfaced by SEP-935 e2e QA: after the
        production ``dispatch_queue_item`` commits and refreshes the fresh
        ``TaskHistory``, the ``execution_request`` attribute is **unloaded**
        because of the deferred ``column_property``. The very first polling
        iteration then hands the stale ORM instance to
        ``NomadExecutor._sync_task_history`` → ``get_allocation_for_task_history``,
        which synchronously reads ``queue_item.execution_request.tracking``
        and triggers ``MissingGreenlet`` against the async ``aiosqlite``
        driver.

        The mock executor here replicates that sync attribute touch. The
        test must not raise ``MissingGreenlet`` and must return a
        ``ConnectivityCheckResponse`` derived from the re-fetched DB row.
        """
        request = ConnectivityCheckWrite(
            target="node1",
            host="db-host",
            port=3306,
            service_type=ConnectivityServiceType.MYSQL,
            timeout=POLL_INTERVAL,
        )

        async def real_dispatch(
            queue_item: TaskHistory, db: AsyncSession
        ) -> TaskHistory:
            queue_item.status = TaskHistoryStatusEnum.RUNNING
            queue_item.execution_request.tracking.update(
                evaluation_id="eval-1", job_id="job-1"
            )
            saved = await TaskHistoryManager.save(
                db, queue_item, flag_modified_fields=["execution_request"]
            )
            # Production reload: deferred column_property is left unloaded
            # so a plain attribute read would trip MissingGreenlet.
            await db.refresh(saved)
            return saved

        captured_history_id = []

        async def sync_task_history(queue_item: TaskHistory) -> TaskHistory:
            # Simulates NomadExecutor._sync_task_history reading tracking
            # from plain sync code within the async call chain — this is
            # where the lazy-load raises MissingGreenlet pre-fix.
            _ = queue_item.execution_request.tracking.get("allocation_id")
            captured_history_id.append(queue_item.id)
            queue_item.status = TaskHistoryStatusEnum.SUCCESS
            queue_item.execution_request.tracking["allocation_id"] = "alloc-1"
            return queue_item

        mock_executor = MagicMock(spec=BaseExecutor)
        mock_executor.sync_task_history = sync_task_history

        with (
            patch(
                "app.tasks.connectivity.service.dispatch_queue_item",
                side_effect=real_dispatch,
            ),
            patch(
                "app.tasks.connectivity.service.get_executor_for_task",
                return_value=mock_executor,
            ),
            patch("app.tasks.connectivity.service.asyncio.sleep", new=AsyncMock()),
        ):
            result = await check_connectivity(session, request)

        assert captured_history_id, "sync_task_history was never invoked"
        assert result.task_history_id == captured_history_id[0]
        assert result.success is False
        assert result.error == "Failed to parse connectivity check output"


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
        assert result.error is not None
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


class TestCheckConnectivityWithCache:
    """Test :func:`check_connectivity_with_cache` caching behaviour."""

    @pytest.mark.asyncio
    async def test_second_call_is_cached(self):
        """Verify a second identical call short-circuits via ``alru_cache``."""
        session = MagicMock(spec=AsyncSession)
        mock_response = MagicMock(success=True, error=None)
        with patch(
            "app.tasks.connectivity.service.check_connectivity",
            new=AsyncMock(return_value=mock_response),
        ) as mock_check:
            first = await check_connectivity_with_cache(
                session,
                target="node1",
                host="10.0.0.1",
                port=3306,
                service_type=ConnectivityServiceType.MYSQL,
            )
            second = await check_connectivity_with_cache(
                session,
                target="node1",
                host="10.0.0.1",
                port=3306,
                service_type=ConnectivityServiceType.MYSQL,
            )

        assert first == (True, None)
        assert second == (True, None)
        assert mock_check.await_count == 1

    @pytest.mark.asyncio
    async def test_different_keys_are_independent(self):
        """Verify entries are keyed by ``(target, host, port, service_type)``."""
        session = MagicMock(spec=AsyncSession)
        responses = [
            MagicMock(success=True, error=None),
            MagicMock(success=False, error="timeout"),
        ]
        with patch(
            "app.tasks.connectivity.service.check_connectivity",
            new=AsyncMock(side_effect=responses),
        ) as mock_check:
            first = await check_connectivity_with_cache(
                session,
                target="node1",
                host="10.0.0.1",
                port=3306,
                service_type=ConnectivityServiceType.MYSQL,
            )
            second = await check_connectivity_with_cache(
                session,
                target="node2",
                host="10.0.0.2",
                port=5432,
                service_type=ConnectivityServiceType.POSTGRESQL,
            )

        assert first == (True, None)
        assert second == (False, "timeout")
        assert mock_check.await_count == EXPECTED_INDEPENDENT_CALL_COUNT
