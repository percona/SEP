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

"""Define tests for the app.tasks.execution.executors.nomad.models module."""

import asyncio
import json
from base64 import b64encode
from binascii import b2a_base64
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import zstandard
from aiohttp import ClientError, ClientTimeout
from fastapi import HTTPException
from nomad.api.exceptions import BaseNomadException, URLNotFoundNomadException

from app.core.exceptions import HTTPBadRequestException
from app.core.utils import slugify
from app.tasks.anonymizer.entities import PIIEntity
from app.tasks.execution.executors.nomad.exceptions import (
    AllocationNotFoundError,
    JobNotFoundError,
)
from app.tasks.execution.executors.nomad.models import (
    _NOMAD_LOG_STREAM_CLIENT_ERROR,
    _NOMAD_LOG_STREAM_SOCK_TIMEOUT,
    NOMAD_DEAD_JOB_STATUS,
    NomadAllocStatusEnum,
    NomadExecutor,
)
from app.tasks.execution.utils import minify_file_content
from app.tasks.models import (
    FileMetadata,
    Task,
    TaskExecutionRequest,
    TaskHistory,
    TaskHistoryStatusEnum,
    TaskLogType,
)

EXPECTED_ALLOC_STATUS_COUNT = 6
NOMAD_DEFAULT_TIMEOUT = 10
INITIAL_LOG_OFFSET = 50
# One started step times (stdout + stderr) when another step has StartedAt None.
EXPECTED_GET_LOGS_STREAM_CALLS_ONE_READY_STEP = 2
MOCK_LOG_STREAM_BODY_START_MONOTONIC = 1000.0


def _build_task(
    task_id: str = "my-job",
    *,
    parameterized: bool = False,
    constraints: list | None = None,
) -> Task:
    """Build a minimal Task instance for testing.

    :param task_id: The job ID to use in the task data.
    :type task_id: str
    :param parameterized: Whether to include a ParameterizedJob field.
    :type parameterized: bool
    :param constraints: Optional constraints list.
    :type constraints: list | None
    :return: A Task instance with minimal fields.
    :rtype: Task
    """
    data = {"ID": task_id, "Constraints": constraints or []}
    if parameterized:
        data["ParameterizedJob"] = {"Payload": "required"}
    return Task(
        id=1,
        name="test-task",
        data=data,
        backend="nomad",
        owner="any",
    )


def _build_queue_item(
    task: Task | None = None,
    tracking: dict | None = None,
    meta: dict | None = None,
    payload: str | None = None,
    status: TaskHistoryStatusEnum = TaskHistoryStatusEnum.RUNNING,
) -> TaskHistory:
    """Build a minimal TaskHistory instance for testing.

    :param task: The task to associate with the history.
    :type task: Task | None
    :param tracking: Tracking dictionary.
    :type tracking: dict | None
    :param meta: Metadata dictionary.
    :type meta: dict | None
    :param payload: Payload string.
    :type payload: str | None
    :param status: The status of the task history.
    :type status: TaskHistoryStatusEnum
    :return: A TaskHistory instance.
    :rtype: TaskHistory
    """
    task = task or _build_task()
    return TaskHistory(
        id=10,
        task_id=task.id,
        task=task,
        execution_request=TaskExecutionRequest(
            task=task.name,
            target="node-1",
            meta=meta or {"target": "node-1"},
            payload=payload,
            tracking=tracking
            or {"allocation_id": None, "evaluation_id": "eval-1", "job_id": "job-1"},
        ),
        status=status,
        anonymize_mask=0,
    )


def _build_executor(**kwargs) -> NomadExecutor:
    """Build a NomadExecutor with default test settings.

    :return: A NomadExecutor instance.
    :rtype: NomadExecutor
    """
    defaults = {
        "endpoint": "http://localhost:4646",
        "verify_ssl": False,
    }
    defaults.update(kwargs)
    return NomadExecutor(**defaults)


class TestNomadAllocStatusEnum:
    """Test NomadAllocStatusEnum values."""

    def test_alloc_status_enum_values(self):
        """Assert all enum members have expected string values."""
        assert NomadAllocStatusEnum.PENDING == "pending"
        assert NomadAllocStatusEnum.RUNNING == "running"
        assert NomadAllocStatusEnum.COMPLETE == "complete"
        assert NomadAllocStatusEnum.FAILED == "failed"
        assert NomadAllocStatusEnum.LOST == "lost"
        assert NomadAllocStatusEnum.UNKNOWN == "unknown"

    def test_alloc_status_enum_count(self):
        """Assert there are exactly 6 enum members."""
        assert len(NomadAllocStatusEnum) == EXPECTED_ALLOC_STATUS_COUNT


class TestTimestampToDatetime:
    """Test NomadExecutor.timestamp_to_datetime."""

    def test_timestamp_to_datetime(self):
        """Assert nanosecond timestamp converts to correct UTC datetime."""
        ns = 1_700_000_000_000_000_000
        result = NomadExecutor.timestamp_to_datetime(ns)
        assert isinstance(result, datetime)
        assert result.tzinfo == UTC
        expected = datetime.fromtimestamp(1_700_000_000, UTC)
        assert result == expected

    def test_timestamp_to_datetime_zero(self):
        """Assert zero nanoseconds converts to epoch."""
        result = NomadExecutor.timestamp_to_datetime(0)
        assert result == datetime.fromtimestamp(0, UTC)


class TestGetTaskHistoryStatusFromAllocStatus:
    """Test NomadExecutor.get_task_history_status_from_alloc_status."""

    def test_complete_not_stopped(self):
        """Assert COMPLETE without stop maps to SUCCESS."""
        result = NomadExecutor.get_task_history_status_from_alloc_status(
            NomadAllocStatusEnum.COMPLETE,
        )
        assert result == TaskHistoryStatusEnum.SUCCESS

    def test_complete_stopped(self):
        """Assert COMPLETE with stopped maps to STOPPED."""
        result = NomadExecutor.get_task_history_status_from_alloc_status(
            NomadAllocStatusEnum.COMPLETE,
            stopped=True,
        )
        assert result == TaskHistoryStatusEnum.STOPPED

    def test_failed(self):
        """Assert FAILED maps to FAILED."""
        result = NomadExecutor.get_task_history_status_from_alloc_status(
            NomadAllocStatusEnum.FAILED,
        )
        assert result == TaskHistoryStatusEnum.FAILED

    def test_lost(self):
        """Assert LOST maps to LOST."""
        result = NomadExecutor.get_task_history_status_from_alloc_status(
            NomadAllocStatusEnum.LOST,
        )
        assert result == TaskHistoryStatusEnum.LOST

    def test_unknown(self):
        """Assert UNKNOWN maps to LOST."""
        result = NomadExecutor.get_task_history_status_from_alloc_status(
            NomadAllocStatusEnum.UNKNOWN,
        )
        assert result == TaskHistoryStatusEnum.LOST

    def test_running_returns_default(self):
        """Assert RUNNING returns default value."""
        result = NomadExecutor.get_task_history_status_from_alloc_status(
            NomadAllocStatusEnum.RUNNING,
        )
        assert result is None

    def test_running_returns_custom_default(self):
        """Assert RUNNING returns the provided default."""
        result = NomadExecutor.get_task_history_status_from_alloc_status(
            NomadAllocStatusEnum.RUNNING,
            default=TaskHistoryStatusEnum.RUNNING,
        )
        assert result == TaskHistoryStatusEnum.RUNNING

    def test_pending_returns_default(self):
        """Assert PENDING returns default value."""
        result = NomadExecutor.get_task_history_status_from_alloc_status(
            NomadAllocStatusEnum.PENDING,
        )
        assert result is None


class TestPrepareTask:
    """Test NomadExecutor.prepare_task."""

    def test_prepare_task_sets_id_suffix(self):
        """Assert prepare_task appends target slug to task data ID."""
        task = _build_task(task_id="base-job")
        queue_item = _build_queue_item(task=task)
        result = NomadExecutor.prepare_task(queue_item)
        assert result.data["ID"] == f"base-job-{slugify('node-1')}"

    def test_prepare_task_with_explicit_task(self):
        """Assert prepare_task uses explicit task argument over queue_item.task."""
        queue_item = _build_queue_item()
        explicit_task = _build_task(task_id="explicit-job")
        result = NomadExecutor.prepare_task(queue_item, task=explicit_task)
        assert result.data["ID"].startswith("explicit-job-")

    def test_prepare_task_meta_substitution(self):
        """Assert prepare_task substitutes meta variables in constraints."""
        constraints = [{"Operand": "${NOMAD_META_target}"}]
        task = _build_task(task_id="meta-job", constraints=constraints)
        meta = {"target": "node-1", "dc": "dc1"}
        queue_item = _build_queue_item(task=task, meta=meta)
        result = NomadExecutor.prepare_task(queue_item)
        assert result.data["Constraints"][0]["Operand"] == "node-1"

    def test_prepare_task_no_meta(self):
        """Assert prepare_task works when meta is None."""
        task = _build_task(task_id="no-meta-job")
        queue_item = _build_queue_item(task=task, meta=None)
        queue_item.execution_request.meta = None
        result = NomadExecutor.prepare_task(queue_item)
        assert result.data["ID"] == f"no-meta-job-{slugify('node-1')}"


class TestBackendProperty:
    """Test NomadExecutor.backend cached property."""

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_backend_creates_nomad_client(self, mock_nomad_cls):
        """Assert backend property creates a Nomad client with correct args."""
        executor = _build_executor()
        _ = executor.backend
        mock_nomad_cls.assert_called_once()
        call_kwargs = mock_nomad_cls.call_args[1]
        assert str(call_kwargs["address"]) == "http://localhost:4646/"
        assert call_kwargs["secure"] is False
        assert call_kwargs["timeout"] == NOMAD_DEFAULT_TIMEOUT
        assert call_kwargs["verify"] is False
        assert call_kwargs["cert"] == ()

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_backend_ssl_config_certfile_only(self, mock_nomad_cls):
        """Assert backend passes single-element cert tuple when only certfile set."""
        executor = _build_executor(verify_ssl=True, secure=True)
        object.__setattr__(executor, "ssl_certfile", "/path/cert.pem")
        object.__setattr__(executor, "ssl_keyfile", None)
        _ = executor.backend
        call_kwargs = mock_nomad_cls.call_args[1]
        assert call_kwargs["cert"] == ("/path/cert.pem",)

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_backend_ssl_config_cert_and_key(self, mock_nomad_cls):
        """Assert backend passes cert+key tuple when both are set."""
        executor = _build_executor(verify_ssl=True, secure=True)
        object.__setattr__(executor, "ssl_certfile", "/path/cert.pem")
        object.__setattr__(executor, "ssl_keyfile", "/path/key.pem")
        _ = executor.backend
        call_kwargs = mock_nomad_cls.call_args[1]
        assert call_kwargs["cert"] == ("/path/cert.pem", "/path/key.pem")

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_backend_verify_with_cafile(self, mock_nomad_cls):
        """Assert backend passes cafile as verify when ssl is fully configured."""
        executor = _build_executor(verify_ssl=True, secure=True)
        object.__setattr__(executor, "ssl_cafile", "/path/ca.pem")
        _ = executor.backend
        call_kwargs = mock_nomad_cls.call_args[1]
        assert call_kwargs["verify"] == "/path/ca.pem"


class TestRegisterJob:
    """Test NomadExecutor.register_job."""

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_register_job_success(self, mock_nomad_cls):
        """Assert register_job calls backend and returns status."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.job.register_job.return_value = {"EvalID": "eval-1"}

        executor = _build_executor()
        task = _build_task(task_id="reg-job")
        result = executor.register_job(task)

        mock_backend.job.register_job.assert_called_once_with(
            id_="reg-job",
            job={"Job": task.data},
        )
        assert result == {"EvalID": "eval-1"}

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_register_job_empty_status_raises(self, mock_nomad_cls):
        """Assert register_job raises ValueError when backend returns empty status."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.job.register_job.return_value = {}

        executor = _build_executor()
        task = _build_task()
        with pytest.raises(ValueError, match="job status could not be determined"):
            executor.register_job(task)


class TestDispatchJob:
    """Test NomadExecutor.dispatch_job."""

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_dispatch_job_with_payload(self, mock_nomad_cls):
        """Assert dispatch_job encodes and dispatches payload correctly."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.job.dispatch_job.return_value = {
            "DispatchedJobID": "dispatched-1",
            "EvalID": "eval-2",
        }

        executor = _build_executor()
        task = _build_task(task_id="dispatch-job", parameterized=True)
        queue_item = _build_queue_item(
            task=task,
            payload="SELECT 1;",
            meta={"target": "node-1", "_job_id_prefix": "custom"},
        )

        result = executor.dispatch_job(queue_item, task)

        assert result["DispatchedJobID"] == "dispatched-1"
        call_kwargs = mock_backend.job.dispatch_job.call_args
        assert call_kwargs[0][0] == "dispatch-job"
        assert call_kwargs[1]["payload"] is not None
        assert call_kwargs[1]["meta"] == {"target": "node-1"}
        assert "_job_id_prefix" not in call_kwargs[1]["meta"]

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_dispatch_job_no_payload(self, mock_nomad_cls):
        """Assert dispatch_job sends None payload when not provided."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.job.dispatch_job.return_value = {
            "DispatchedJobID": "d-1",
            "EvalID": "e-1",
        }

        executor = _build_executor()
        task = _build_task(task_id="no-payload-job", parameterized=True)
        queue_item = _build_queue_item(task=task, payload=None)

        executor.dispatch_job(queue_item, task)

        call_kwargs = mock_backend.job.dispatch_job.call_args
        assert call_kwargs[1]["payload"] is None

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_dispatch_job_empty_status_raises(self, mock_nomad_cls):
        """Assert dispatch_job raises ValueError when status is empty."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.job.dispatch_job.return_value = {}

        executor = _build_executor()
        task = _build_task(parameterized=True)
        queue_item = _build_queue_item(task=task)

        with pytest.raises(ValueError, match="job status could not be determined"):
            executor.dispatch_job(queue_item, task)

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_dispatch_job_payload_is_base64_gzip(self, mock_nomad_cls):
        """Assert payload is gzip-compressed and base64-encoded."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.job.dispatch_job.return_value = {
            "DispatchedJobID": "d-1",
            "EvalID": "e-1",
        }

        executor = _build_executor()
        task = _build_task(parameterized=True)
        raw_payload = "SELECT 1;"
        queue_item = _build_queue_item(task=task, payload=raw_payload)

        executor.dispatch_job(queue_item, task)

        sent_payload = mock_backend.job.dispatch_job.call_args[1]["payload"]
        minified_payload = minify_file_content(raw_payload)
        cctx = zstandard.ZstdCompressor(level=22)
        compressed = cctx.compress(minified_payload.encode("utf-8"))
        expected = b2a_base64(compressed).decode("utf-8").strip()
        assert sent_payload == expected

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_dispatch_job_custom_prefix(self, mock_nomad_cls):
        """Assert dispatch_job uses custom job_id_prefix from meta."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.job.dispatch_job.return_value = {
            "DispatchedJobID": "d-1",
            "EvalID": "e-1",
        }

        executor = _build_executor()
        task = _build_task(parameterized=True)
        queue_item = _build_queue_item(
            task=task,
            meta={"target": "n1", "_job_id_prefix": "prefix"},
        )

        executor.dispatch_job(queue_item, task)

        call_kwargs = mock_backend.job.dispatch_job.call_args
        expected_prefix = f"{slugify(task.name)}-{task.id}-{slugify('prefix')}"
        assert call_kwargs[1]["id_prefix_template"] == expected_prefix


class TestGetJob:
    """Test NomadExecutor.get_job."""

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_get_job_success(self, mock_nomad_cls):
        """Assert get_job returns job details."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.job.get_job.return_value = {"ID": "job-1", "Status": "running"}

        executor = _build_executor()
        result = executor.get_job("job-1")
        assert result["ID"] == "job-1"

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_get_job_not_found_raises(self, mock_nomad_cls):
        """Assert get_job raises JobNotFoundError on URLNotFoundNomadException."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.job.get_job.side_effect = URLNotFoundNomadException(
            MagicMock(text="not found")
        )

        executor = _build_executor()
        with pytest.raises(JobNotFoundError):
            executor.get_job("missing-job")


class TestGetJobForTaskHistory:
    """Test NomadExecutor.get_job_for_task_history."""

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_get_job_for_task_history_success(self, mock_nomad_cls):
        """Assert get_job_for_task_history retrieves job by tracking job_id."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.job.get_job.return_value = {"ID": "job-1"}

        executor = _build_executor()
        queue_item = _build_queue_item(
            tracking={"job_id": "job-1", "allocation_id": None, "evaluation_id": "e-1"}
        )
        result = executor.get_job_for_task_history(queue_item)
        assert result["ID"] == "job-1"

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_get_job_for_task_history_missing_job_id(self, mock_nomad_cls):
        """Assert get_job_for_task_history raises when job_id is missing."""
        mock_nomad_cls.return_value = MagicMock()
        executor = _build_executor()
        queue_item = _build_queue_item(
            tracking={"allocation_id": None, "evaluation_id": "e-1"}
        )
        with pytest.raises(JobNotFoundError, match="Missing job_id"):
            executor.get_job_for_task_history(queue_item)


class TestGetHosts:
    """Test NomadExecutor.get_hosts."""

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_get_hosts(self, mock_nomad_cls):
        """Assert get_hosts returns filtered healthy nodes."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.nodes.get_nodes.return_value = [
            {"Name": "node-a", "Address": "10.0.0.1"},
            {"Name": "node-b", "Address": "10.0.0.2"},
        ]

        executor = _build_executor()
        result = executor.get_hosts()

        assert result == {"node-a": "10.0.0.1", "node-b": "10.0.0.2"}
        mock_backend.nodes.get_nodes.assert_called_once()


class TestGetAllocationForTaskHistory:
    """Test NomadExecutor.get_allocation_for_task_history."""

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_get_allocation_by_allocation_id(self, mock_nomad_cls):
        """Assert allocation is fetched directly when allocation_id is in tracking."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.allocation.get_allocation.return_value = {"ID": "alloc-1"}

        executor = _build_executor()
        queue_item = _build_queue_item(
            tracking={
                "allocation_id": "alloc-1",
                "evaluation_id": "eval-1",
                "job_id": "job-1",
            }
        )

        result = executor.get_allocation_for_task_history(queue_item)
        assert result["ID"] == "alloc-1"

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_get_allocation_fallback_to_last_allocation(self, mock_nomad_cls):
        """Assert fallback to get_last_allocation when allocation_id lookup fails."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.allocation.get_allocation.side_effect = URLNotFoundNomadException(
            MagicMock(text="not found")
        )
        mock_backend.allocations.get_allocations.return_value = [
            {
                "ID": "alloc-fallback",
                "JobID": "job-1",
                "EvalID": "eval-1",
                "TaskStates": None,
            }
        ]

        executor = _build_executor()
        queue_item = _build_queue_item(
            tracking={
                "allocation_id": "alloc-missing",
                "evaluation_id": "eval-1",
                "job_id": "job-1",
            }
        )

        result = executor.get_allocation_for_task_history(queue_item)
        assert result["ID"] == "alloc-fallback"


class TestGetLastAllocation:
    """Test NomadExecutor.get_last_allocation."""

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_get_last_allocation_success(self, mock_nomad_cls):
        """Assert get_last_allocation returns first allocation with sorted task states."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.allocations.get_allocations.return_value = [
            {
                "ID": "alloc-1",
                "JobID": "job-1",
                "TaskStates": {
                    "zz-step": {"StartedAt": "2", "FinishedAt": "3"},
                    "aa-step": {"StartedAt": "1", "FinishedAt": "2"},
                },
            }
        ]

        executor = _build_executor()
        result = executor.get_last_allocation(job_id="job-1", eval_id="eval-1")

        assert result["ID"] == "alloc-1"
        keys = list(result["TaskStates"].keys())
        assert keys == ["aa-step", "zz-step"]

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_get_last_allocation_no_filters_raises(self, mock_nomad_cls):
        """Assert get_last_allocation raises ValueError without any filter."""
        mock_nomad_cls.return_value = MagicMock()
        executor = _build_executor()
        with pytest.raises(ValueError, match="Either job_id or eval_id"):
            executor.get_last_allocation()

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_get_last_allocation_not_found(self, mock_nomad_cls):
        """Assert get_last_allocation raises AllocationNotFoundError when empty."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.allocations.get_allocations.return_value = []

        executor = _build_executor()
        with pytest.raises(AllocationNotFoundError) as ctx:
            executor.get_last_allocation(job_id="missing-job")
        err = ctx.value
        assert err.job_id == "missing-job"
        assert err.evaluation_id is None
        assert err.resource_type == "allocation"

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_get_last_allocation_null_task_states(self, mock_nomad_cls):
        """Assert get_last_allocation handles None TaskStates."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.allocations.get_allocations.return_value = [
            {"ID": "alloc-1", "JobID": "job-1", "TaskStates": None}
        ]

        executor = _build_executor()
        result = executor.get_last_allocation(job_id="job-1")
        assert result["TaskStates"] is None


class TestDispatchTask:
    """Test NomadExecutor.dispatch_task."""

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.TaskHistoryManager")
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_dispatch_task_parameterized(self, mock_nomad_cls, mock_th_manager):
        """Assert dispatch_task handles parameterized job flow correctly."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend

        mock_backend.job.register_job.return_value = {"EvalID": "eval-reg"}
        mock_backend.job.get_job.side_effect = [
            URLNotFoundNomadException(MagicMock(text="not found")),
            {"ID": "param-job-node-1", "SubmitTime": None},
            {"ID": "dispatched-job-1", "SubmitTime": 1_700_000_000_000_000_000},
        ]
        mock_backend.job.dispatch_job.return_value = {
            "DispatchedJobID": "dispatched-job-1",
            "EvalID": "eval-disp",
        }

        mock_th_manager.save = AsyncMock(side_effect=lambda _s, qi, **_kw: qi)

        executor = _build_executor()
        task = _build_task(task_id="param-job", parameterized=True)
        queue_item = _build_queue_item(
            task=task,
            status=TaskHistoryStatusEnum.PENDING,
        )
        session = AsyncMock()

        result = await executor.dispatch_task(session, queue_item, task)

        assert result.status == TaskHistoryStatusEnum.RUNNING
        assert result.execution_request.tracking["job_id"] == "dispatched-job-1"
        assert result.execution_request.tracking["evaluation_id"] == "eval-disp"
        assert result.started_at is not None

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.TaskHistoryManager")
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_dispatch_task_non_parameterized(
        self, mock_nomad_cls, mock_th_manager
    ):
        """Assert dispatch_task handles non-parameterized job registration."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend

        mock_backend.job.register_job.return_value = {"EvalID": "eval-1"}
        mock_backend.job.get_job.return_value = {
            "ID": "non-param-job-node-1",
            "SubmitTime": 1_700_000_000_000_000_000,
        }

        mock_th_manager.save = AsyncMock(side_effect=lambda _s, qi, **_kw: qi)

        executor = _build_executor()
        task = _build_task(task_id="non-param-job", parameterized=False)
        queue_item = _build_queue_item(
            task=task,
            status=TaskHistoryStatusEnum.PENDING,
        )
        session = AsyncMock()

        result = await executor.dispatch_task(session, queue_item, task)

        assert result.status == TaskHistoryStatusEnum.RUNNING
        mock_backend.job.register_job.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.TaskHistoryManager")
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_dispatch_task_uses_submit_time(
        self, mock_nomad_cls, mock_th_manager
    ):
        """Assert dispatch_task uses SubmitTime for started_at when available."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend

        submit_ns = 1_700_000_000_000_000_000
        mock_backend.job.register_job.return_value = {"EvalID": "eval-1"}
        mock_backend.job.get_job.return_value = {
            "ID": "job-1",
            "SubmitTime": submit_ns,
        }

        mock_th_manager.save = AsyncMock(side_effect=lambda _s, qi, **_kw: qi)

        executor = _build_executor()
        task = _build_task(task_id="ts-job", parameterized=False)
        queue_item = _build_queue_item(
            task=task,
            status=TaskHistoryStatusEnum.PENDING,
        )
        session = AsyncMock()

        result = await executor.dispatch_task(session, queue_item, task)

        expected_dt = datetime.fromtimestamp(submit_ns / 10**9, UTC)
        assert result.started_at == expected_dt


class TestStopTask:
    """Test NomadExecutor._stop_task."""

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_stop_task(self, mock_nomad_cls):
        """Assert _stop_task deregisters the job."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend

        executor = _build_executor()
        queue_item = _build_queue_item(
            tracking={
                "job_id": "job-to-stop",
                "allocation_id": None,
                "evaluation_id": "eval-1",
            }
        )

        await executor._stop_task(queue_item)

        mock_backend.job.deregister_job.assert_called_once_with("job-to-stop")

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_stop_task_missing_job_id_raises(self, mock_nomad_cls):
        """Assert _stop_task raises ValueError when job_id is missing."""
        mock_nomad_cls.return_value = MagicMock()
        executor = _build_executor()
        queue_item = _build_queue_item(
            tracking={"allocation_id": None, "evaluation_id": "eval-1"}
        )

        with pytest.raises(ValueError, match="job ID could not be determined"):
            await executor._stop_task(queue_item)


class TestSyncTaskHistory:
    """Test NomadExecutor._sync_task_history."""

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_sync_task_history_not_running_returns_early(self, mock_nomad_cls):
        """Assert _sync_task_history returns immediately if status is not RUNNING."""
        mock_nomad_cls.return_value = MagicMock()
        executor = _build_executor()
        queue_item = _build_queue_item(status=TaskHistoryStatusEnum.SUCCESS)

        result = await executor._sync_task_history(queue_item)
        assert result.status == TaskHistoryStatusEnum.SUCCESS

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_sync_task_history_complete(self, mock_nomad_cls):
        """Assert _sync_task_history updates to SUCCESS when job is dead and alloc complete."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend

        mock_backend.allocation.get_allocation.return_value = {
            "ID": "alloc-1",
            "JobID": "job-1",
            "EvalID": "eval-1",
            "ClientStatus": NomadAllocStatusEnum.COMPLETE,
            "TaskStates": {"step1": {"StartedAt": "1", "FinishedAt": "2"}},
            "ModifyTime": 1_700_000_000_000_000_000,
        }
        mock_backend.client.stream_logs.stream.return_value = ""
        mock_backend.job.get_job.return_value = {
            "ID": "job-1",
            "Status": NOMAD_DEAD_JOB_STATUS,
            "Stop": False,
        }

        executor = _build_executor()
        queue_item = _build_queue_item(
            tracking={
                "allocation_id": "alloc-1",
                "evaluation_id": "eval-1",
                "job_id": "job-1",
            },
            status=TaskHistoryStatusEnum.RUNNING,
        )

        result = await executor._sync_task_history(queue_item)

        assert result.status == TaskHistoryStatusEnum.SUCCESS
        assert result.finished_at is not None

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_sync_task_history_failed(self, mock_nomad_cls):
        """Assert _sync_task_history updates to FAILED when alloc is failed."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend

        mock_backend.allocation.get_allocation.return_value = {
            "ID": "alloc-1",
            "JobID": "job-1",
            "EvalID": "eval-1",
            "ClientStatus": NomadAllocStatusEnum.FAILED,
            "TaskStates": {"step1": {"StartedAt": "1", "FinishedAt": "2"}},
            "ModifyTime": 1_700_000_000_000_000_000,
        }
        mock_backend.client.stream_logs.stream.return_value = ""
        mock_backend.job.get_job.return_value = {
            "ID": "job-1",
            "Status": NOMAD_DEAD_JOB_STATUS,
            "Stop": False,
        }

        executor = _build_executor()
        queue_item = _build_queue_item(
            tracking={
                "allocation_id": "alloc-1",
                "evaluation_id": "eval-1",
                "job_id": "job-1",
            },
            status=TaskHistoryStatusEnum.RUNNING,
        )

        result = await executor._sync_task_history(queue_item)

        assert result.status == TaskHistoryStatusEnum.FAILED
        assert result.finished_at is not None

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_sync_task_history_allocation_not_found_lost(self, mock_nomad_cls):
        """Assert _sync_task_history sets LOST when both allocation and job are gone."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend

        mock_backend.allocation.get_allocation.side_effect = URLNotFoundNomadException(
            MagicMock(text="not found")
        )
        mock_backend.allocations.get_allocations.return_value = []
        mock_backend.job.get_job.side_effect = URLNotFoundNomadException(
            MagicMock(text="not found")
        )

        executor = _build_executor()
        queue_item = _build_queue_item(
            tracking={
                "allocation_id": "alloc-gone",
                "evaluation_id": "eval-1",
                "job_id": "job-1",
            },
            status=TaskHistoryStatusEnum.RUNNING,
        )

        result = await executor._sync_task_history(queue_item)

        assert result.status == TaskHistoryStatusEnum.LOST

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_sync_task_history_allocation_not_found_no_pending_evals(
        self, mock_nomad_cls
    ):
        """Assert _sync_task_history sets FAILED when no alloc and no pending evals."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend

        mock_backend.allocation.get_allocation.side_effect = URLNotFoundNomadException(
            MagicMock(text="not found")
        )
        mock_backend.allocations.get_allocations.return_value = []
        mock_backend.job.get_job.return_value = {"ID": "job-1"}
        mock_backend.job.get_evaluations.return_value = [
            {"Status": "complete"},
        ]

        executor = _build_executor()
        queue_item = _build_queue_item(
            tracking={
                "allocation_id": "alloc-gone",
                "evaluation_id": "eval-1",
                "job_id": "job-1",
            },
            status=TaskHistoryStatusEnum.RUNNING,
        )

        result = await executor._sync_task_history(queue_item)

        assert result.status == TaskHistoryStatusEnum.FAILED
        assert result.started_at is None

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_sync_task_history_complete_no_modify_time(self, mock_nomad_cls):
        """Assert _sync_task_history uses utc_now when ModifyTime is missing."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend

        mock_backend.allocation.get_allocation.return_value = {
            "ID": "alloc-1",
            "JobID": "job-1",
            "EvalID": "eval-1",
            "ClientStatus": NomadAllocStatusEnum.COMPLETE,
            "TaskStates": {"step1": {"StartedAt": "1", "FinishedAt": "2"}},
            "ModifyTime": None,
        }
        mock_backend.client.stream_logs.stream.return_value = ""
        mock_backend.job.get_job.return_value = {
            "ID": "job-1",
            "Status": NOMAD_DEAD_JOB_STATUS,
            "Stop": False,
        }

        executor = _build_executor()
        queue_item = _build_queue_item(
            tracking={
                "allocation_id": "alloc-1",
                "evaluation_id": "eval-1",
                "job_id": "job-1",
            },
            status=TaskHistoryStatusEnum.RUNNING,
        )

        result = await executor._sync_task_history(queue_item)

        assert result.status == TaskHistoryStatusEnum.SUCCESS
        assert result.finished_at is not None

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_sync_task_history_followup_eval_chain(self, mock_nomad_cls):
        """Assert _sync_task_history follows FollowupEvalID chain."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend

        first_alloc = {
            "ID": "alloc-1",
            "JobID": "job-1",
            "EvalID": "eval-1",
            "FollowupEvalID": "eval-followup",
            "ClientStatus": NomadAllocStatusEnum.RUNNING,
            "TaskStates": {"step1": {"StartedAt": "1", "FinishedAt": None}},
        }
        followup_alloc = {
            "ID": "alloc-2",
            "JobID": "job-1",
            "EvalID": "eval-followup",
            "ClientStatus": NomadAllocStatusEnum.COMPLETE,
            "TaskStates": {"step1": {"StartedAt": "1", "FinishedAt": "2"}},
            "ModifyTime": 1_700_000_000_000_000_000,
        }

        mock_backend.allocation.get_allocation.return_value = first_alloc
        mock_backend.allocations.get_allocations.return_value = [followup_alloc]
        mock_backend.client.stream_logs.stream.return_value = ""
        mock_backend.job.get_job.return_value = {
            "ID": "job-1",
            "Status": NOMAD_DEAD_JOB_STATUS,
            "Stop": False,
        }

        executor = _build_executor()
        queue_item = _build_queue_item(
            tracking={
                "allocation_id": "alloc-1",
                "evaluation_id": "eval-1",
                "job_id": "job-1",
            },
            status=TaskHistoryStatusEnum.RUNNING,
        )

        result = await executor._sync_task_history(queue_item)

        assert result.status == TaskHistoryStatusEnum.SUCCESS
        assert result.execution_request.tracking["allocation_id"] == "alloc-2"

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_sync_task_history_stopped(self, mock_nomad_cls):
        """Assert _sync_task_history maps COMPLETE with Stop=True to STOPPED."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend

        mock_backend.allocation.get_allocation.return_value = {
            "ID": "alloc-1",
            "JobID": "job-1",
            "EvalID": "eval-1",
            "ClientStatus": NomadAllocStatusEnum.COMPLETE,
            "TaskStates": {"step1": {"StartedAt": "1", "FinishedAt": "2"}},
            "ModifyTime": 1_700_000_000_000_000_000,
        }
        mock_backend.client.stream_logs.stream.return_value = ""
        mock_backend.job.get_job.return_value = {
            "ID": "job-1",
            "Status": NOMAD_DEAD_JOB_STATUS,
            "Stop": True,
        }

        executor = _build_executor()
        queue_item = _build_queue_item(
            tracking={
                "allocation_id": "alloc-1",
                "evaluation_id": "eval-1",
                "job_id": "job-1",
            },
            status=TaskHistoryStatusEnum.RUNNING,
        )

        result = await executor._sync_task_history(queue_item)
        assert result.status == TaskHistoryStatusEnum.STOPPED

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_sync_task_history_job_lost_after_alloc_found(self, mock_nomad_cls):
        """Assert _sync_task_history sets LOST when job disappears after alloc lookup."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend

        mock_backend.allocation.get_allocation.return_value = {
            "ID": "alloc-1",
            "JobID": "job-1",
            "EvalID": "eval-1",
            "ClientStatus": NomadAllocStatusEnum.RUNNING,
            "TaskStates": {"step1": {"StartedAt": "1", "FinishedAt": None}},
            "ModifyTime": None,
        }
        mock_backend.client.stream_logs.stream.return_value = ""
        mock_backend.job.get_job.side_effect = URLNotFoundNomadException(
            MagicMock(text="not found")
        )

        executor = _build_executor()
        queue_item = _build_queue_item(
            tracking={
                "allocation_id": "alloc-1",
                "evaluation_id": "eval-1",
                "job_id": "job-1",
            },
            status=TaskHistoryStatusEnum.RUNNING,
        )

        result = await executor._sync_task_history(queue_item)
        assert result.status == TaskHistoryStatusEnum.LOST


class TestTaskNeedsJobRegister:
    """Test NomadExecutor.task_needs_job_register."""

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_non_parameterized_always_true(self, mock_nomad_cls):
        """Assert non-parameterized tasks always need registration."""
        mock_nomad_cls.return_value = MagicMock()
        executor = _build_executor()
        task = _build_task(parameterized=False)
        assert executor.task_needs_job_register(task) is True

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_parameterized_job_not_found(self, mock_nomad_cls):
        """Assert True when parameterized job doesn't exist."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.job.get_job.side_effect = URLNotFoundNomadException(
            MagicMock(text="not found")
        )

        executor = _build_executor()
        task = _build_task(parameterized=True)
        assert executor.task_needs_job_register(task) is True

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_parameterized_job_stale(self, mock_nomad_cls):
        """Assert True when existing job is older than task update time."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        old_timestamp = 1_600_000_000_000_000_000
        mock_backend.job.get_job.return_value = {
            "ID": "job-1",
            "SubmitTime": old_timestamp,
        }

        executor = _build_executor()
        task = _build_task(parameterized=True)
        task.updated_at = datetime(2024, 1, 1, tzinfo=UTC)
        assert executor.task_needs_job_register(task) is True

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_parameterized_job_fresh(self, mock_nomad_cls):
        """Assert False when existing job is newer than task update time."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        recent_timestamp = 2_000_000_000_000_000_000
        mock_backend.job.get_job.return_value = {
            "ID": "job-1",
            "SubmitTime": recent_timestamp,
        }

        executor = _build_executor()
        task = _build_task(parameterized=True)
        task.updated_at = datetime(2020, 1, 1, tzinfo=UTC)
        assert executor.task_needs_job_register(task) is False

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_parameterized_job_no_submit_time(self, mock_nomad_cls):
        """Assert True when existing job has no SubmitTime."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.job.get_job.return_value = {
            "ID": "job-1",
            "SubmitTime": None,
        }

        executor = _build_executor()
        task = _build_task(parameterized=True)
        assert executor.task_needs_job_register(task) is True


class TestValidateJob:
    """Test NomadExecutor.validate_job."""

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.async_run")
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_validate_job_success(self, mock_nomad_cls, mock_async_run):
        """Assert validate_job returns job when validation passes."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = json.dumps({"ValidationErrors": []})
        mock_async_run.return_value = (mock_response,)

        executor = _build_executor()
        job = {"ID": "test-job", "Type": "batch"}
        result = await executor.validate_job(job)
        assert result == job

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.async_run")
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_validate_job_validation_errors(self, mock_nomad_cls, mock_async_run):
        """Assert validate_job raises HTTPBadRequestException on validation errors."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = json.dumps(
            {"ValidationErrors": ["missing required field"]}
        )
        mock_async_run.return_value = (mock_response,)

        executor = _build_executor()
        with pytest.raises(HTTPBadRequestException):
            await executor.validate_job({"ID": "bad-job"})

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.async_run")
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_validate_job_non_200_raises(self, mock_nomad_cls, mock_async_run):
        """Assert validate_job raises HTTPException on non-200 status."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_async_run.return_value = (mock_response,)

        executor = _build_executor()
        with pytest.raises(HTTPException):
            await executor.validate_job({"ID": "error-job"})


class TestGetLogsForAllocation:
    """Test NomadExecutor.get_logs_for_allocation."""

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_get_logs_for_allocation(self, mock_nomad_cls):
        """Assert get_logs_for_allocation decodes base64 logs for each step."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend

        raw_msg = b64encode(b"Hello from step1").decode()
        log_data = json.dumps({"Data": raw_msg, "Offset": 100})
        mock_backend.client.stream_logs.stream.return_value = log_data

        alloc = {
            "ID": "alloc-1",
            "TaskStates": {"step1": {"StartedAt": "2024-01-01T00:00:00Z"}},
        }

        executor = _build_executor()
        result = executor.get_logs_for_allocation(alloc)

        assert "step1" in result
        assert "Hello from step1" in result["step1"]["stdout"]

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_get_logs_for_allocation_no_task_states(self, mock_nomad_cls):
        """Assert get_logs_for_allocation returns empty when no task states."""
        mock_nomad_cls.return_value = MagicMock()
        executor = _build_executor()
        alloc = {"ID": "alloc-1", "TaskStates": None}
        result = executor.get_logs_for_allocation(alloc)
        assert dict(result) == {}

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_get_logs_for_allocation_exception_handling(self, mock_nomad_cls):
        """Assert get_logs_for_allocation handles stream_logs exceptions gracefully."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.client.stream_logs.stream.side_effect = BaseNomadException(
            MagicMock(text="stream error")
        )

        alloc = {
            "ID": "alloc-1",
            "TaskStates": {"step1": {"StartedAt": "2024-01-01T00:00:00Z"}},
        }

        executor = _build_executor()
        result = executor.get_logs_for_allocation(alloc)

        assert "step1" in result
        assert result["step1"]["stdout"] == ""
        assert result["step1"]["stderr"] == ""

    @patch("app.tasks.execution.executors.nomad.models.anonymize_text")
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_get_logs_for_allocation_with_anonymization(
        self, mock_nomad_cls, mock_anonymize
    ):
        """Assert get_logs_for_allocation applies anonymization for run-script step."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_anonymize.return_value = "REDACTED"

        raw_msg = b64encode(b"sensitive data").decode()
        log_data = json.dumps({"Data": raw_msg, "Offset": 100})
        mock_backend.client.stream_logs.stream.return_value = log_data

        alloc = {
            "ID": "alloc-1",
            "TaskStates": {"run-script": {"StartedAt": "2024-01-01T00:00:00Z"}},
        }

        executor = _build_executor()
        result = executor.get_logs_for_allocation(
            alloc, anonymize_entities={PIIEntity.PERSON}
        )

        assert "REDACTED" in result["run-script"]["stdout"]
        mock_anonymize.assert_called()

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_get_logs_for_allocation_with_initial_logs(self, mock_nomad_cls):
        """Assert get_logs_for_allocation merges initial_logs."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.client.stream_logs.stream.return_value = ""

        alloc = {
            "ID": "alloc-1",
            "TaskStates": {"step1": {"StartedAt": "2024-01-01T00:00:00Z"}},
        }
        initial_logs = {
            "step1": {
                "stdout": "previous output",
                "stdout_last_offset": INITIAL_LOG_OFFSET,
            }
        }

        executor = _build_executor()
        result = executor.get_logs_for_allocation(alloc, initial_logs=initial_logs)

        assert result["step1"]["stdout"] == "previous output"
        assert result["step1"]["stdout_last_offset"] == INITIAL_LOG_OFFSET

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_get_logs_for_allocation_skips_step_when_not_started(self, mock_nomad_cls):
        """Assert steps with StartedAt None do not call stream_logs."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.client.stream_logs.stream.return_value = ""

        alloc = {
            "ID": "alloc-1",
            "TaskStates": {
                "pending-step": {"StartedAt": None},
                "ready-step": {"StartedAt": "2024-01-01T00:00:00Z"},
            },
        }

        executor = _build_executor()
        executor.get_logs_for_allocation(alloc)

        stream = mock_backend.client.stream_logs.stream
        assert stream.call_count == EXPECTED_GET_LOGS_STREAM_CALLS_ONE_READY_STEP
        tasks = {c.kwargs["task"] for c in stream.call_args_list}
        types = {c.kwargs["type_"] for c in stream.call_args_list}
        assert tasks == {"ready-step"}
        assert types == {TaskLogType.STDOUT, TaskLogType.STDERR}


class TestNomadLogStreaming:
    """Regression tests for Nomad HTTP log streaming helpers."""

    @staticmethod
    def _alloc_for_logs():
        return {
            "ID": "alloc-stream",
            "JobID": "job-1",
            "EvalID": "eval-1",
            "TaskStates": {
                "step1": {"StartedAt": "2024-01-01T00:00:00Z", "State": "running"},
            },
        }

    @pytest.mark.asyncio
    @patch(
        "app.tasks.execution.executors.nomad.models.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_consume_nomad_log_stream_404_before_task_starts_waits(
        self, mock_sleep
    ):
        """404 while StartedAt is None should sleep and return running with no stream start."""
        mock_response = MagicMock()
        mock_response.status = 404
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        executor = _build_executor()
        alloc = {
            "ID": "alloc-stream",
            "JobID": "job-1",
            "EvalID": "eval-1",
            "TaskStates": {
                "step1": {"StartedAt": None, "State": "pending"},
            },
        }
        params = {
            "task": "step1",
            "type": TaskLogType.STDOUT,
            "follow": "true",
            "offset": 0,
        }
        queue = asyncio.Queue()

        with patch.object(executor, "_request", return_value=mock_ctx):
            state, out_alloc, stream_start = await executor._consume_nomad_log_stream(
                alloc=alloc,
                step="step1",
                log_type=TaskLogType.STDOUT,
                queue=queue,
                params=params,
                client_timeout=ClientTimeout(sock_read=NOMAD_DEFAULT_TIMEOUT),
                anonymize_entities=None,
            )

        assert state == "running"
        assert out_alloc is alloc
        assert stream_start is None
        mock_sleep.assert_awaited_once()

    @pytest.mark.asyncio
    @patch.object(NomadExecutor, "_consume_nomad_log_stream", new_callable=AsyncMock)
    async def test_push_logs_queue_sock_timeout_logs_and_stops(self, mock_consume):
        """Sock read timeout sentinel ends the push loop and calls _log_stream_timeout."""
        alloc = self._alloc_for_logs()
        mock_consume.return_value = (
            _NOMAD_LOG_STREAM_SOCK_TIMEOUT,
            alloc,
            MOCK_LOG_STREAM_BODY_START_MONOTONIC,
        )

        executor = _build_executor()
        queue = asyncio.Queue()

        with patch.object(executor, "_log_stream_timeout") as mock_log_timeout:
            await executor._push_logs_to_queue(
                alloc, "step1", TaskLogType.STDOUT, queue, start_offset=0
            )

        mock_log_timeout.assert_called_once()
        args, kwargs = mock_log_timeout.call_args
        assert args[0] == "alloc-stream"
        assert args[1] == "step1"
        assert args[2] == TaskLogType.STDOUT
        assert args[3] == MOCK_LOG_STREAM_BODY_START_MONOTONIC
        sentinel = await queue.get()
        assert sentinel.msg is None

    @pytest.mark.asyncio
    @patch.object(NomadExecutor, "_consume_nomad_log_stream", new_callable=AsyncMock)
    async def test_push_logs_queue_client_error_logs_and_stops(self, mock_consume):
        """Client error sentinel ends the push loop and calls _log_stream_client_error."""
        alloc = self._alloc_for_logs()
        mock_consume.return_value = (_NOMAD_LOG_STREAM_CLIENT_ERROR, alloc, None)

        executor = _build_executor()
        queue = asyncio.Queue()

        with patch.object(executor, "_log_stream_client_error") as mock_log_client:
            await executor._push_logs_to_queue(
                alloc, "step1", TaskLogType.STDERR, queue, start_offset=3
            )

        mock_log_client.assert_called_once()
        sentinel = await queue.get()
        assert sentinel.msg is None

    @pytest.mark.asyncio
    @patch.object(NomadExecutor, "_consume_nomad_log_stream", new_callable=AsyncMock)
    async def test_push_logs_queue_cancelled_logs_and_reraises(self, mock_consume):
        """CancelledError must propagate after _log_stream_cancelled."""
        alloc = self._alloc_for_logs()
        mock_consume.side_effect = asyncio.CancelledError()

        executor = _build_executor()
        queue = asyncio.Queue()

        with (
            patch.object(executor, "_log_stream_cancelled") as mock_log_cancel,
            pytest.raises(asyncio.CancelledError),
        ):
            await executor._push_logs_to_queue(
                alloc, "step1", TaskLogType.STDOUT, queue
            )

        mock_log_cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_consume_nomad_log_stream_client_error_from_raise_for_status(self):
        """ClientError from raise_for_status returns client-error sentinel."""
        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.raise_for_status.side_effect = ClientError("boom")
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        executor = _build_executor()
        alloc = self._alloc_for_logs()
        params = {
            "task": "step1",
            "type": TaskLogType.STDOUT,
            "follow": "true",
            "offset": 0,
        }
        queue = asyncio.Queue()

        with patch.object(executor, "_request", return_value=mock_ctx):
            state, out_alloc, stream_start = await executor._consume_nomad_log_stream(
                alloc=alloc,
                step="step1",
                log_type=TaskLogType.STDOUT,
                queue=queue,
                params=params,
                client_timeout=ClientTimeout(sock_read=NOMAD_DEFAULT_TIMEOUT),
                anonymize_entities=None,
            )

        assert state == _NOMAD_LOG_STREAM_CLIENT_ERROR
        assert out_alloc is alloc
        assert stream_start is None

    @pytest.mark.asyncio
    async def test_consume_nomad_log_stream_timeout_during_iter_chunks(self):
        """TimeoutError while reading the body returns sock-timeout with stream_start set."""

        async def iter_chunks():
            raise TimeoutError
            yield (b"", None)  # pragma: no cover

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.content.iter_chunks = iter_chunks

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        executor = _build_executor()
        alloc = self._alloc_for_logs()
        params = {
            "task": "step1",
            "type": TaskLogType.STDOUT,
            "follow": "true",
            "offset": 0,
        }
        queue = asyncio.Queue()

        with patch.object(executor, "_request", return_value=mock_ctx):
            state, out_alloc, stream_start = await executor._consume_nomad_log_stream(
                alloc=alloc,
                step="step1",
                log_type=TaskLogType.STDOUT,
                queue=queue,
                params=params,
                client_timeout=ClientTimeout(sock_read=NOMAD_DEFAULT_TIMEOUT),
                anonymize_entities=None,
            )

        assert state == _NOMAD_LOG_STREAM_SOCK_TIMEOUT
        assert out_alloc is alloc
        assert stream_start is not None


class TestListFiles:
    """Test NomadExecutor.list_files."""

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_list_files(self, mock_nomad_cls):
        """Assert list_files returns FileMetadata dict excluding hidden files."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.allocation.get_allocation.return_value = {"ID": "alloc-1"}

        executor = _build_executor()
        queue_item = _build_queue_item(
            tracking={
                "allocation_id": "alloc-1",
                "evaluation_id": "eval-1",
                "job_id": "job-1",
            }
        )

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = AsyncMock(
            return_value=[
                {"Name": "output.sql", "Size": 1024, "IsDir": False},
                {"Name": ".hidden", "Size": 0, "IsDir": False},
                {"Name": "subdir", "Size": 0, "IsDir": True},
            ]
        )

        mock_ctx_manager = AsyncMock()
        mock_ctx_manager.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx_manager.__aexit__ = AsyncMock(return_value=False)

        with patch.object(executor, "_request", return_value=mock_ctx_manager):
            result = await executor.list_files(queue_item, "/alloc/data")

        assert "output.sql" in result
        assert result["output.sql"] == FileMetadata(size=1024, is_dir=False)
        assert ".hidden" not in result
        assert "subdir" in result
        assert result["subdir"].is_dir is True


class TestParsePayload:
    """Test NomadExecutor.parse_payload."""

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.async_run")
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_parse_payload_hcl(self, mock_nomad_cls, mock_async_run):
        """Assert parse_payload delegates HCL to backend.jobs.parse."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_async_run.return_value = {"Job": {"ID": "parsed"}}

        executor = _build_executor()
        result = await executor.parse_payload("job {}", "hcl")

        mock_async_run.assert_called_once_with(mock_backend.jobs.parse, "job {}")
        assert result == {"Job": {"ID": "parsed"}}

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_parse_payload_json(self, mock_nomad_cls):
        """Assert parse_payload delegates JSON to parent class."""
        mock_nomad_cls.return_value = MagicMock()
        executor = _build_executor()

        json_payload = json.dumps({"Job": {"ID": "test"}})
        result = await executor.parse_payload(json_payload, "json")

        assert result == {"Job": {"ID": "test"}}


class TestStreamFile:
    """Test NomadExecutor.stream_file."""

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_stream_file_regular(self, mock_nomad_cls):
        """Assert stream_file reads a regular file in chunks."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.allocation.get_allocation.return_value = {"ID": "alloc-1"}

        executor = _build_executor()
        queue_item = _build_queue_item(
            tracking={
                "allocation_id": "alloc-1",
                "evaluation_id": "eval-1",
                "job_id": "job-1",
            }
        )

        file_content = b"file content here"
        stat_response = AsyncMock()
        stat_response.raise_for_status = MagicMock()
        stat_response.json = AsyncMock(
            return_value={"Size": len(file_content), "IsDir": False}
        )

        read_response = AsyncMock()
        read_response.raise_for_status = MagicMock()
        read_response.read = AsyncMock(return_value=file_content)

        call_count = 0

        def mock_request(method, path, **kwargs):
            nonlocal call_count
            call_count += 1
            ctx = AsyncMock()
            if "stat" in path:
                ctx.__aenter__ = AsyncMock(return_value=stat_response)
            else:
                ctx.__aenter__ = AsyncMock(return_value=read_response)
            ctx.__aexit__ = AsyncMock(return_value=False)
            return ctx

        with patch.object(executor, "_request", side_effect=mock_request):
            chunks = [
                chunk
                async for chunk in executor.stream_file(queue_item, "/output/dump.sql")
            ]

        assert b"".join(chunks) == file_content

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_stream_file_empty(self, mock_nomad_cls):
        """Assert stream_file yields empty bytes for zero-size file."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.allocation.get_allocation.return_value = {"ID": "alloc-1"}

        executor = _build_executor()
        queue_item = _build_queue_item(
            tracking={
                "allocation_id": "alloc-1",
                "evaluation_id": "eval-1",
                "job_id": "job-1",
            }
        )

        stat_response = AsyncMock()
        stat_response.raise_for_status = MagicMock()
        stat_response.json = AsyncMock(return_value={"Size": 0, "IsDir": False})

        def mock_request(method, path, **kwargs):
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=stat_response)
            ctx.__aexit__ = AsyncMock(return_value=False)
            return ctx

        with patch.object(executor, "_request", side_effect=mock_request):
            chunks = [
                chunk
                async for chunk in executor.stream_file(queue_item, "/output/empty.txt")
            ]

        assert chunks == [b""]

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.anonymize_text")
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_stream_file_with_anonymization(self, mock_nomad_cls, mock_anonymize):
        """Assert stream_file applies anonymization when entities are set."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.allocation.get_allocation.return_value = {"ID": "alloc-1"}
        mock_anonymize.return_value = "REDACTED"

        executor = _build_executor()
        queue_item = _build_queue_item(
            tracking={
                "allocation_id": "alloc-1",
                "evaluation_id": "eval-1",
                "job_id": "job-1",
            }
        )
        queue_item.anonymize_mask = 1

        file_content = b"sensitive data"
        stat_response = AsyncMock()
        stat_response.raise_for_status = MagicMock()
        stat_response.json = AsyncMock(
            return_value={"Size": len(file_content), "IsDir": False}
        )

        read_response = AsyncMock()
        read_response.raise_for_status = MagicMock()
        read_response.read = AsyncMock(return_value=file_content)

        def mock_request(method, path, **kwargs):
            ctx = AsyncMock()
            if "stat" in path:
                ctx.__aenter__ = AsyncMock(return_value=stat_response)
            else:
                ctx.__aenter__ = AsyncMock(return_value=read_response)
            ctx.__aexit__ = AsyncMock(return_value=False)
            return ctx

        with patch.object(executor, "_request", side_effect=mock_request):
            chunks = [
                chunk
                async for chunk in executor.stream_file(queue_item, "/output/dump.sql")
            ]

        assert b"".join(chunks) == b"REDACTED"
        mock_anonymize.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_stream_file_directory_delegates(self, mock_nomad_cls):
        """Assert stream_file delegates to _stream_directory_as_tar_gz for directories."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.allocation.get_allocation.return_value = {"ID": "alloc-1"}

        executor = _build_executor()
        queue_item = _build_queue_item(
            tracking={
                "allocation_id": "alloc-1",
                "evaluation_id": "eval-1",
                "job_id": "job-1",
            }
        )

        stat_response = AsyncMock()
        stat_response.raise_for_status = MagicMock()
        stat_response.json = AsyncMock(return_value={"IsDir": True, "Size": 0})

        def mock_request(method, path, **kwargs):
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=stat_response)
            ctx.__aexit__ = AsyncMock(return_value=False)
            return ctx

        async def fake_tar_gz(*args, **kwargs):
            yield b"fake-tar-data"

        with (
            patch.object(executor, "_request", side_effect=mock_request),
            patch.object(
                executor,
                "_stream_directory_as_tar_gz",
                side_effect=fake_tar_gz,
            ),
        ):
            chunks = [
                chunk
                async for chunk in executor.stream_file(queue_item, "/output/subdir")
            ]

        assert chunks == [b"fake-tar-data"]


class TestReadFileBytes:
    """Test NomadExecutor._read_file_bytes."""

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_read_file_bytes_empty(self, mock_nomad_cls):
        """Assert _read_file_bytes returns empty bytes for zero-size file."""
        mock_nomad_cls.return_value = MagicMock()
        executor = _build_executor()
        queue_item = _build_queue_item()

        result = await executor._read_file_bytes(queue_item, "alloc-1", "/f.txt", 0)
        assert result == b""

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_read_file_bytes_single_chunk(self, mock_nomad_cls):
        """Assert _read_file_bytes reads a small file in one chunk."""
        mock_nomad_cls.return_value = MagicMock()
        executor = _build_executor()
        queue_item = _build_queue_item()

        content = b"hello world"
        read_response = AsyncMock()
        read_response.raise_for_status = MagicMock()
        read_response.read = AsyncMock(return_value=content)

        def mock_request(method, path, **kwargs):
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=read_response)
            ctx.__aexit__ = AsyncMock(return_value=False)
            return ctx

        with patch.object(executor, "_request", side_effect=mock_request):
            result = await executor._read_file_bytes(
                queue_item, "alloc-1", "/f.txt", len(content)
            )

        assert result == content

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.anonymize_text")
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_read_file_bytes_with_anonymization(
        self, mock_nomad_cls, mock_anonymize
    ):
        """Assert _read_file_bytes applies anonymization when entities are set."""
        mock_nomad_cls.return_value = MagicMock()
        mock_anonymize.return_value = "REDACTED content"

        executor = _build_executor()
        queue_item = _build_queue_item()
        queue_item.anonymize_mask = 1

        content = b"sensitive content"
        read_response = AsyncMock()
        read_response.raise_for_status = MagicMock()
        read_response.read = AsyncMock(return_value=content)

        def mock_request(method, path, **kwargs):
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=read_response)
            ctx.__aexit__ = AsyncMock(return_value=False)
            return ctx

        with patch.object(executor, "_request", side_effect=mock_request):
            result = await executor._read_file_bytes(
                queue_item, "alloc-1", "/f.txt", len(content)
            )

        assert result == b"REDACTED content"
        mock_anonymize.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_read_file_bytes_size_mismatch_logs_warning(self, mock_nomad_cls):
        """Assert _read_file_bytes handles size mismatch gracefully."""
        mock_nomad_cls.return_value = MagicMock()
        executor = _build_executor()
        queue_item = _build_queue_item()

        content = b"short"
        read_response = AsyncMock()
        read_response.raise_for_status = MagicMock()
        read_response.read = AsyncMock(return_value=content)

        def mock_request(method, path, **kwargs):
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=read_response)
            ctx.__aexit__ = AsyncMock(return_value=False)
            return ctx

        with patch.object(executor, "_request", side_effect=mock_request):
            result = await executor._read_file_bytes(
                queue_item, "alloc-1", "/f.txt", 9999
            )

        assert result == content


class TestIterDirectoryEntries:
    """Test NomadExecutor._iter_directory_entries."""

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_iter_directory_entries_flat(self, mock_nomad_cls):
        """Assert _iter_directory_entries yields entries with correct paths."""
        mock_nomad_cls.return_value = MagicMock()
        executor = _build_executor()

        ls_response = AsyncMock()
        ls_response.raise_for_status = MagicMock()
        ls_response.json = AsyncMock(
            return_value=[
                {"Name": "file1.txt", "IsDir": False, "Size": 100},
                {"Name": ".hidden", "IsDir": False, "Size": 50},
                {"Name": "sub", "IsDir": True, "Size": 0},
            ]
        )

        sub_response = AsyncMock()
        sub_response.raise_for_status = MagicMock()
        sub_response.json = AsyncMock(
            return_value=[
                {"Name": "nested.txt", "IsDir": False, "Size": 200},
            ]
        )

        call_count = 0

        def mock_request(method, path, **kwargs):
            nonlocal call_count
            call_count += 1
            ctx = AsyncMock()
            if call_count == 1:
                ctx.__aenter__ = AsyncMock(return_value=ls_response)
            else:
                ctx.__aenter__ = AsyncMock(return_value=sub_response)
            ctx.__aexit__ = AsyncMock(return_value=False)
            return ctx

        with patch.object(executor, "_request", side_effect=mock_request):
            entries = [
                entry
                async for entry in executor._iter_directory_entries(
                    "alloc-1", "/alloc/data", "root"
                )
            ]

        abs_paths = [e[0] for e in entries]
        rel_paths = [e[1] for e in entries]
        assert "/alloc/data/file1.txt" in abs_paths
        assert "/alloc/data/.hidden" not in abs_paths
        assert "root/file1.txt" in rel_paths
        assert "root/sub/" in rel_paths
        assert "root/sub/nested.txt" in rel_paths


class TestIsDirectory:
    """Test NomadExecutor._is_directory."""

    @pytest.mark.parametrize(
        ("stat", "expected"),
        [
            ({"IsDir": True}, True),
            ({"Directory": "some-dir"}, True),
            ({"Type": "directory"}, True),
            ({"Type": "dir"}, True),
            ({"IsDir": False, "Type": "file"}, False),
            ({}, False),
        ],
    )
    def test_is_directory(self, stat, expected):
        """Assert _is_directory correctly detects directory stats."""
        assert NomadExecutor._is_directory(stat) is expected
