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
from collections import defaultdict
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientError, ClientTimeout
from fastapi import status
from nomad.api.exceptions import BaseNomadException, URLNotFoundNomadException
from pydantic import ValidationError

from app.core.exceptions import HTTPBadRequestException
from app.core.settings_override.registry import (
    ReloadClassification,
    resolve_nested_field_metadata,
)
from app.core.utils import slugify
from app.tasks.anonymizer.entities import PIIEntity
from app.tasks.config import tasks_settings, TasksSettings
from app.tasks.crud import TaskHistoryLogManager, TaskHistoryLogStateManager
from app.tasks.execution.executors.nomad.exceptions import (
    AllocationNotFoundError,
    JobNotFoundError,
)
from app.tasks.execution.executors.nomad.models import (
    _detect_stale_skip,
    _NOMAD_LOG_STREAM_CLIENT_ERROR,
    _NOMAD_LOG_STREAM_SOCK_TIMEOUT,
    NOMAD_DEAD_JOB_STATUS,
    nomad_task_states_to_execution_events,
    NomadAllocStatusEnum,
    NomadExecutor,
)
from app.tasks.execution.utils import gzip_compress, minify_file_content
from app.tasks.logs.log_writer import TaskHistoryLogWriter
from app.tasks.models import (
    ExecutionEvent,
    FileMetadata,
    Task,
    TaskExecutionRequest,
    TaskHistory,
    TaskHistoryStatusEnum,
    TaskLog,
    TaskLogType,
)

EXPECTED_ALLOC_STATUS_COUNT = 6
NOMAD_DEFAULT_TIMEOUT = 10
INITIAL_LOG_OFFSET = 50
# One started step times (stdout + stderr) when another step has StartedAt None.
EXPECTED_GET_LOGS_STREAM_CALLS_ONE_READY_STEP = 2
MOCK_LOG_STREAM_BODY_START_MONOTONIC = 1000.0
STALENESS_THRESHOLD_OVERRIDE = 300
MULTI_CHUNK_LOG_FIRST_OFFSET = 17
MULTI_CHUNK_LOG_SECOND_OFFSET = 42
EXPECTED_MULTI_CHUNK_LOG_COUNT = 2
SPLIT_FRAME_LOG_OFFSET = 99
EXPECTED_SINGLE_TASK_LOG_COUNT = 1
EMPTY_DATA_FRAME_DATA_OFFSET = 10
EMPTY_DATA_FRAME_OFFSET_ONLY = 25
RECHECK_LOG_SOCKET_READ_TIMEOUT = 2
EXPECTED_EMPTY_FRAMES_BEFORE_RECHECK = 3
RECHECKED_TASK_STATE = "dead"
ALLOCATION_CREATE_INDEX = 100
SUPERSEDED_ALLOCATION_EPOCH = 100
CURRENT_ALLOCATION_EPOCH = 200
SEED_OFFSET = 3
LEGACY_SEED_PRODUCER_OFFSET = 5


def _build_task(
    task_id: str = "my-job",
    *,
    parameterized: bool = False,
    constraints: list | None = None,
    declares_staleness_meta: bool = True,
) -> Task:
    """Build a minimal Task instance for testing.

    :param task_id: The job ID to use in the task data.
    :type task_id: str
    :param parameterized: Whether to include a ParameterizedJob field.
    :type parameterized: bool
    :param constraints: Optional constraints list.
    :type constraints: list | None
    :param declares_staleness_meta: Whether the ParameterizedJob declares the
        ``scheduled_at``/``staleness_threshold_seconds`` meta keys (matches the
        shape of the centralized templates). Only effective when
        ``parameterized=True``.
    :type declares_staleness_meta: bool
    :return: A Task instance with minimal fields.
    :rtype: Task
    """
    data = {"ID": task_id, "Constraints": constraints or []}
    if parameterized:
        parameterized_spec: dict = {"Payload": "required"}
        if declares_staleness_meta:
            parameterized_spec["MetaOptional"] = [
                "scheduled_at",
                "staleness_threshold_seconds",
            ]
        data["ParameterizedJob"] = parameterized_spec
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


class TestNomadExecutorTlsClassification:
    """Assert the inherited TLS leaves classify as advanced + HOT via the overlay.

    These fields are inherited (frozen) from ``BaseRemoteAPI`` and marked only
    through ``NomadExecutor.INHERITED_MARKERS`` -- not by redeclaration. See
    SEP-1511.
    """

    @pytest.mark.parametrize(
        "leaf", ["VERIFY_SSL", "SSL_CAFILE", "SSL_KEYFILE", "SSL_CERTFILE"]
    )
    def test_tls_leaves_are_advanced_and_hot(self, leaf: str) -> None:
        """Each TLS leaf classifies ``advanced`` + HOT through the settings API."""
        meta = resolve_nested_field_metadata(TasksSettings, f"NOMAD__{leaf}")
        assert meta is not None
        assert meta.is_advanced is True
        assert meta.reload is ReloadClassification.HOT

    def test_endpoint_stays_unmarked(self) -> None:
        """The inherited ``endpoint`` has no overlay entry, so it stays non-advanced."""
        meta = resolve_nested_field_metadata(TasksSettings, "NOMAD__ENDPOINT")
        assert meta is not None
        assert meta.is_advanced is False

    def test_tls_leaves_remain_frozen(self) -> None:
        """Dropping the redeclarations keeps ``frozen=True`` inherited from the base."""
        executor = _build_executor()
        with pytest.raises(ValidationError):
            executor.verify_ssl = True

    def test_hash_is_value_stable(self) -> None:
        """Two executors with identical config hash equal (identity hash unchanged)."""
        assert hash(_build_executor()) == hash(_build_executor())


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
        assert call_kwargs["address"] == "http://localhost:4646"
        assert call_kwargs["secure"] is False
        assert call_kwargs["timeout"] == NOMAD_DEFAULT_TIMEOUT
        assert call_kwargs["verify"] is False
        assert call_kwargs["cert"] == ()

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_backend_strips_trailing_slash_from_endpoint(self, mock_nomad_cls):
        """Strip the trailing slash off a host-only Nomad endpoint.

        ``HttpUrl`` normalises a host-only URL by appending ``/``. python-nomad
        joins paths as ``f"{address}/v1/..."``, so a trailing slash yields
        ``//v1/nodes``; Nomad 307-redirects that to an HTML body and python-nomad
        (no redirect following) calls ``.json()`` on it, raising
        ``Expecting value: line 1 column 1 (char 0)``. The executor must strip the
        slash so the request path stays single-slashed.
        """
        executor = _build_executor(endpoint="https://nomad.example:4646")
        _ = executor.backend
        address = mock_nomad_cls.call_args[1]["address"]
        assert address == "https://nomad.example:4646"
        assert not address.endswith("/")

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
        assert call_kwargs[1]["meta"]["target"] == "node-1"
        assert "_job_id_prefix" not in call_kwargs[1]["meta"]
        assert "staleness_threshold_seconds" in call_kwargs[1]["meta"]

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
        expected = b2a_base64(gzip_compress(minify_file_content(raw_payload))).decode(
            "utf-8"
        )
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

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_dispatch_job_injects_threshold_from_settings(self, mock_nomad_cls):
        """Assert dispatch_job injects the configured staleness threshold."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.job.dispatch_job.return_value = {
            "DispatchedJobID": "d-1",
            "EvalID": "e-1",
        }
        executor = _build_executor()
        task = _build_task(parameterized=True)
        queue_item = _build_queue_item(task=task, meta={"target": "n"})

        original = tasks_settings.STALENESS_THRESHOLD_SECONDS
        tasks_settings.STALENESS_THRESHOLD_SECONDS = STALENESS_THRESHOLD_OVERRIDE
        try:
            executor.dispatch_job(queue_item, task)
        finally:
            tasks_settings.STALENESS_THRESHOLD_SECONDS = original

        meta = mock_backend.job.dispatch_job.call_args[1]["meta"]
        assert meta["staleness_threshold_seconds"] == str(STALENESS_THRESHOLD_OVERRIDE)

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_dispatch_job_strips_underscore_meta_but_preserves_staleness(
        self, mock_nomad_cls
    ):
        """Assert underscore keys are stripped while staleness meta is injected."""
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
            meta={
                "target": "n",
                "_chain_task_names": ["next"],
            },
        )

        executor.dispatch_job(queue_item, task)

        meta = mock_backend.job.dispatch_job.call_args[1]["meta"]
        assert "_chain_task_names" not in meta
        assert "scheduled_at" in meta
        assert isinstance(meta["scheduled_at"], str)
        assert "staleness_threshold_seconds" in meta
        assert isinstance(meta["staleness_threshold_seconds"], str)

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_dispatch_job_skips_staleness_meta_when_job_does_not_declare_it(
        self, mock_nomad_cls
    ):
        """Assert staleness meta is NOT injected into jobs that don't declare it.

        Custom user-defined parameterized jobs that haven't been updated to
        include the staleness meta keys would otherwise be rejected by Nomad,
        so ``dispatch_job`` must preserve backward compatibility by only
        injecting the staleness meta when the job spec declares it.
        """
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.job.dispatch_job.return_value = {
            "DispatchedJobID": "d-1",
            "EvalID": "e-1",
        }
        executor = _build_executor()
        task = _build_task(parameterized=True, declares_staleness_meta=False)
        queue_item = _build_queue_item(task=task, meta={"target": "n"})

        executor.dispatch_job(queue_item, task)

        meta = mock_backend.job.dispatch_job.call_args[1]["meta"]
        assert "scheduled_at" not in meta
        assert "staleness_threshold_seconds" not in meta

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_dispatch_job_scheduled_at_uses_eta_when_set(self, mock_nomad_cls):
        """Assert ``scheduled_at`` derives from ``eta`` when the ETA is set."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.job.dispatch_job.return_value = {
            "DispatchedJobID": "d-1",
            "EvalID": "e-1",
        }
        executor = _build_executor()
        task = _build_task(parameterized=True)
        queue_item = _build_queue_item(task=task, meta={"target": "n"})
        eta = datetime(2030, 1, 1, tzinfo=UTC)
        queue_item.execution_request.eta = eta

        executor.dispatch_job(queue_item, task)

        meta = mock_backend.job.dispatch_job.call_args[1]["meta"]
        assert meta["scheduled_at"] == str(int(eta.timestamp()))


class TestDetectStaleSkip:
    """Test the module-level ``_detect_stale_skip`` helper."""

    def test_returns_false_when_task_states_none(self):
        """Assert ``_detect_stale_skip`` returns ``False`` when input is ``None``."""
        assert _detect_stale_skip(None) is False

    def test_returns_false_when_task_states_not_dict(self):
        """Assert ``_detect_stale_skip`` tolerates a non-dict input."""
        assert _detect_stale_skip("not a dict") is False

    def test_returns_false_when_task_absent(self):
        """Assert ``_detect_stale_skip`` returns ``False`` when the task key is absent."""
        assert _detect_stale_skip({"other-task": {"Events": []}}) is False

    def test_returns_false_when_events_missing(self):
        """Assert ``_detect_stale_skip`` returns ``False`` when ``Events`` is missing."""
        assert _detect_stale_skip({"check-staleness": {"State": "dead"}}) is False

    def test_returns_true_on_terminated_exit_75(self):
        """Assert exit-75 ``Terminated`` event classifies as stale."""
        task_states = {
            "check-staleness": {
                "Events": [
                    {"Type": "Started"},
                    {"Type": "Terminated", "ExitCode": 75},
                ],
            }
        }
        assert _detect_stale_skip(task_states) is True

    def test_returns_false_on_terminated_exit_1(self):
        """Assert non-75 ``Terminated`` exit does NOT classify as stale."""
        task_states = {
            "check-staleness": {
                "Events": [{"Type": "Terminated", "ExitCode": 1}],
            }
        }
        assert _detect_stale_skip(task_states) is False

    def test_returns_false_when_exit_code_missing(self):
        """Assert a ``Terminated`` event with no exit code short-circuits to ``False``."""
        task_states = {
            "check-staleness": {
                "Events": [{"Type": "Terminated"}],
            }
        }
        assert _detect_stale_skip(task_states) is False

    def test_reads_exit_code_from_details_nested_shape(self):
        """Assert exit-code falls back to ``Details.exit_code`` shape."""
        task_states = {
            "check-staleness": {
                "Events": [
                    {"Type": "Terminated", "Details": {"exit_code": 75}},
                ],
            }
        }
        assert _detect_stale_skip(task_states) is True


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
    async def test_sync_task_history_stale_override(self, mock_nomad_cls):
        """Assert _sync_task_history maps to STALE when check-staleness exited 75."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend

        mock_backend.allocation.get_allocation.return_value = {
            "ID": "alloc-1",
            "JobID": "job-1",
            "EvalID": "eval-1",
            "ClientStatus": NomadAllocStatusEnum.FAILED,
            "TaskStates": {
                "check-staleness": {
                    "Events": [{"Type": "Terminated", "ExitCode": 75}],
                },
            },
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

        assert result.status == TaskHistoryStatusEnum.STALE
        assert result.finished_at is not None

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_sync_task_history_non_stale_exit_code_preserves_failed(
        self, mock_nomad_cls
    ):
        """Assert _sync_task_history keeps FAILED mapping for non-75 prestart exits."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend

        mock_backend.allocation.get_allocation.return_value = {
            "ID": "alloc-1",
            "JobID": "job-1",
            "EvalID": "eval-1",
            "ClientStatus": NomadAllocStatusEnum.FAILED,
            "TaskStates": {
                "check-staleness": {
                    "Events": [{"Type": "Terminated", "ExitCode": 1}],
                },
            },
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
        mock_response.status_code = status.HTTP_200_OK
        mock_response.text = json.dumps({"ValidationErrors": []})
        mock_async_run.return_value = mock_response

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
        mock_response.status_code = status.HTTP_200_OK
        mock_response.text = json.dumps(
            {"ValidationErrors": ["missing required field"]}
        )
        mock_async_run.return_value = mock_response

        executor = _build_executor()
        with pytest.raises(HTTPBadRequestException):
            await executor.validate_job({"ID": "bad-job"})

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.async_run")
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_validate_job_non_200_raises(self, mock_nomad_cls, mock_async_run):
        """Assert validate_job raises HTTPBadRequestException on non-200 status."""
        mock_response = MagicMock()
        mock_response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        mock_async_run.return_value = mock_response

        executor = _build_executor()
        with pytest.raises(HTTPBadRequestException):
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
    def test_get_logs_for_allocation_with_initial_offsets(self, mock_nomad_cls):
        """Assert get_logs_for_allocation starts Nomad reads at the given offsets.

        The fetcher returns only the delta for this cycle — content keys in
        ``initial_logs`` are ignored; only ``f"{log_type}_last_offset"`` keys
        are read.
        """
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.client.stream_logs.stream.return_value = ""

        alloc = {
            "ID": "alloc-1",
            "TaskStates": {"step1": {"StartedAt": "2024-01-01T00:00:00Z"}},
        }
        initial_logs = {
            "step1": {
                "stdout_last_offset": INITIAL_LOG_OFFSET,
                "stderr_last_offset": INITIAL_LOG_OFFSET,
            }
        }

        executor = _build_executor()
        result = executor.get_logs_for_allocation(alloc, initial_logs=initial_logs)

        assert result["step1"]["stdout"] == ""
        assert result["step1"]["stderr"] == ""
        assert result["step1"]["stdout_last_offset"] == INITIAL_LOG_OFFSET
        assert result["step1"]["stderr_last_offset"] == INITIAL_LOG_OFFSET
        stream_call_kwargs = [
            call.kwargs
            for call in mock_backend.client.stream_logs.stream.call_args_list
        ]
        assert all(
            kwargs["offset"] == INITIAL_LOG_OFFSET for kwargs in stream_call_kwargs
        )

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

    @patch("app.tasks.execution.executors.nomad.models.anonymize_text")
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_get_logs_for_allocation_anonymized_offsets_track_producer_space(
        self, mock_nomad_cls, mock_anonymize
    ):
        """Assert producer offset tracks anonymized bytes, not Nomad bytes.

        Regression test: when anonymization replaces raw bytes
        with a shorter or longer string, the producer-space offset returned
        alongside the delta must track the post-anonymization byte length
        so the writer dedup window does not mix Nomad-space and
        anonymized-space counts on retry.
        """
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_anonymize.return_value = "[REDACTED]"
        raw_bytes = b"4111-1111-1111-1111"
        raw_msg = b64encode(raw_bytes).decode()
        log_data = json.dumps({"Data": raw_msg, "Offset": len(raw_bytes)})
        mock_backend.client.stream_logs.stream.return_value = log_data
        alloc = {
            "ID": "alloc-1",
            "TaskStates": {"run-script": {"StartedAt": "2024-01-01T00:00:00Z"}},
        }

        executor = _build_executor()
        result = executor.get_logs_for_allocation(
            alloc, anonymize_entities={PIIEntity.CREDIT_CARD}
        )

        assert result["run-script"]["stdout"] == "[REDACTED]"
        assert result["run-script"]["stdout_last_offset"] == len(raw_bytes)
        assert result["run-script"]["stdout_producer_offset"] == len("[REDACTED]")

    @patch("app.tasks.execution.executors.nomad.models.anonymize_text")
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_get_logs_for_allocation_anonymized_retry_dedups_correctly(
        self, mock_nomad_cls, mock_anonymize
    ):
        """Assert a second fetch at the advanced offsets yields no new bytes.

        Simulates a retry after a successful first fetch: the second cycle
        starts at the advanced Nomad offset (so Nomad returns nothing new)
        and passes the advanced producer offset through; the writer caller
        therefore sees a zero-length delta and never re-writes already
        persisted anonymized bytes.
        """
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_anonymize.return_value = "[REDACTED]"
        raw_bytes = b"4111-1111-1111-1111"
        raw_msg = b64encode(raw_bytes).decode()
        first_log_data = json.dumps({"Data": raw_msg, "Offset": len(raw_bytes)})
        mock_backend.client.stream_logs.stream.side_effect = [
            first_log_data,
            "",
            "",
            "",
        ]
        alloc = {
            "ID": "alloc-1",
            "TaskStates": {"run-script": {"StartedAt": "2024-01-01T00:00:00Z"}},
        }

        executor = _build_executor()
        first = executor.get_logs_for_allocation(
            alloc, anonymize_entities={PIIEntity.CREDIT_CARD}
        )
        second = executor.get_logs_for_allocation(
            alloc,
            initial_logs={
                "run-script": {
                    "stdout_last_offset": first["run-script"]["stdout_last_offset"],
                    "stdout_producer_offset": first["run-script"][
                        "stdout_producer_offset"
                    ],
                    "stderr_last_offset": first["run-script"]["stderr_last_offset"],
                    "stderr_producer_offset": first["run-script"][
                        "stderr_producer_offset"
                    ],
                }
            },
            anonymize_entities={PIIEntity.CREDIT_CARD},
        )

        assert second["run-script"]["stdout"] == ""
        assert second["run-script"]["stdout_last_offset"] == len(raw_bytes)
        assert second["run-script"]["stdout_producer_offset"] == len("[REDACTED]")


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

    @staticmethod
    def _alloc_for_logs_step2():
        return {
            "ID": "alloc-stream",
            "JobID": "job-1",
            "EvalID": "eval-1",
            "TaskStates": {
                "step2": {"StartedAt": "2024-01-01T00:00:00Z", "State": "running"},
            },
        }

    @staticmethod
    def _nomad_log_frame(*, msg: str | None, offset: int) -> bytes:
        frame: dict = {"Offset": offset}
        if msg is not None:
            frame["Data"] = b64encode(msg.encode()).decode()
        return json.dumps(frame).encode()

    @staticmethod
    def _make_iter_chunks(chunks: list[bytes]):
        async def iter_chunks():
            for chunk in chunks:
                yield chunk, None

        return iter_chunks

    @staticmethod
    async def _drain_task_logs(queue: asyncio.Queue) -> list[TaskLog]:
        logs = []
        while not queue.empty():
            logs.append(await queue.get())
        return logs

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

    @pytest.mark.asyncio
    async def test_consume_nomad_log_stream_advances_offset_across_chunks(self):
        """Two data frames advance params offset and enqueue TaskLogs in order (step2)."""
        chunks = [
            self._nomad_log_frame(msg="line-one", offset=MULTI_CHUNK_LOG_FIRST_OFFSET),
            self._nomad_log_frame(msg="line-two", offset=MULTI_CHUNK_LOG_SECOND_OFFSET),
        ]

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.content.iter_chunks = self._make_iter_chunks(chunks)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        executor = _build_executor()
        alloc = self._alloc_for_logs_step2()
        params = {
            "task": "step2",
            "type": TaskLogType.STDOUT,
            "follow": "true",
            "offset": 0,
        }
        queue = asyncio.Queue()

        with patch.object(executor, "_request", return_value=mock_ctx):
            state, out_alloc, stream_start = await executor._consume_nomad_log_stream(
                alloc=alloc,
                step="step2",
                log_type=TaskLogType.STDOUT,
                queue=queue,
                params=params,
                client_timeout=ClientTimeout(sock_read=NOMAD_DEFAULT_TIMEOUT),
                anonymize_entities=None,
            )

        logs = await self._drain_task_logs(queue)

        assert state == "running"
        assert out_alloc is alloc
        assert stream_start is not None
        assert params["offset"] == MULTI_CHUNK_LOG_SECOND_OFFSET
        assert len(logs) == EXPECTED_MULTI_CHUNK_LOG_COUNT
        assert [log.msg for log in logs] == ["line-one", "line-two"]
        assert [log.offset for log in logs] == [
            MULTI_CHUNK_LOG_FIRST_OFFSET,
            MULTI_CHUNK_LOG_SECOND_OFFSET,
        ]
        assert all(log.step == "step2" for log in logs)
        assert all(log.type == TaskLogType.STDOUT for log in logs)
        offsets = [log.offset for log in logs]
        assert offsets == sorted(offsets)

    @pytest.mark.asyncio
    async def test_consume_nomad_log_stream_split_frame_reassembly(self):
        """Split JSON across chunks reassembles via raw_data before json.loads (step2)."""
        full = self._nomad_log_frame(msg="split-msg", offset=SPLIT_FRAME_LOG_OFFSET)
        split_at = full.rfind(b"}")
        assert b"}" not in full[:split_at]
        chunks = [full[:split_at], full[split_at:]]

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.content.iter_chunks = self._make_iter_chunks(chunks)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        executor = _build_executor()
        alloc = self._alloc_for_logs_step2()
        params = {
            "task": "step2",
            "type": TaskLogType.STDOUT,
            "follow": "true",
            "offset": 0,
        }
        queue = asyncio.Queue()

        with patch.object(executor, "_request", return_value=mock_ctx):
            state, out_alloc, stream_start = await executor._consume_nomad_log_stream(
                alloc=alloc,
                step="step2",
                log_type=TaskLogType.STDOUT,
                queue=queue,
                params=params,
                client_timeout=ClientTimeout(sock_read=NOMAD_DEFAULT_TIMEOUT),
                anonymize_entities=None,
            )

        logs = await self._drain_task_logs(queue)

        assert state == "running"
        assert out_alloc is alloc
        assert stream_start is not None
        assert params["offset"] == SPLIT_FRAME_LOG_OFFSET
        assert len(logs) == EXPECTED_SINGLE_TASK_LOG_COUNT
        assert logs[0].msg == "split-msg"
        assert logs[0].offset == SPLIT_FRAME_LOG_OFFSET
        assert logs[0].step == "step2"
        assert logs[0].type == TaskLogType.STDOUT

    @pytest.mark.asyncio
    async def test_consume_nomad_log_stream_empty_data_increments_without_recheck(self):
        """Data frame then empty frame increments empty_data_count without recheck (step2)."""
        chunks = [
            self._nomad_log_frame(msg="has-data", offset=EMPTY_DATA_FRAME_DATA_OFFSET),
            self._nomad_log_frame(msg=None, offset=EMPTY_DATA_FRAME_OFFSET_ONLY),
        ]

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.content.iter_chunks = self._make_iter_chunks(chunks)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        executor = _build_executor()
        alloc = self._alloc_for_logs_step2()
        params = {
            "task": "step2",
            "type": TaskLogType.STDOUT,
            "follow": "true",
            "offset": 0,
        }
        queue = asyncio.Queue()

        with (
            patch.object(executor, "_request", return_value=mock_ctx),
            patch.object(
                NomadExecutor, "get_last_allocation"
            ) as mock_get_last_allocation,
        ):
            state, out_alloc, stream_start = await executor._consume_nomad_log_stream(
                alloc=alloc,
                step="step2",
                log_type=TaskLogType.STDOUT,
                queue=queue,
                params=params,
                client_timeout=ClientTimeout(sock_read=NOMAD_DEFAULT_TIMEOUT),
                anonymize_entities=None,
            )

        logs = await self._drain_task_logs(queue)

        assert state == "running"
        assert out_alloc is alloc
        assert stream_start is not None
        assert params["offset"] == EMPTY_DATA_FRAME_OFFSET_ONLY
        mock_get_last_allocation.assert_not_called()
        assert len(logs) == EXPECTED_SINGLE_TASK_LOG_COUNT
        assert logs[0].msg == "has-data"
        assert logs[0].offset == EMPTY_DATA_FRAME_DATA_OFFSET

    @pytest.mark.asyncio
    async def test_consume_nomad_log_stream_empty_data_triggers_recheck(self):
        """Consecutive empty frames trigger get_last_allocation and return task state (step2)."""
        empty_offsets = list(range(1, EXPECTED_EMPTY_FRAMES_BEFORE_RECHECK + 1))
        chunks = [
            self._nomad_log_frame(msg=None, offset=offset) for offset in empty_offsets
        ]

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.content.iter_chunks = self._make_iter_chunks(chunks)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        executor = _build_executor(
            log_socket_read_timeout=RECHECK_LOG_SOCKET_READ_TIMEOUT
        )
        alloc = self._alloc_for_logs_step2()
        refreshed_alloc = {
            **alloc,
            "TaskStates": {
                "step2": {
                    "StartedAt": "2024-01-01T00:00:00Z",
                    "State": RECHECKED_TASK_STATE,
                },
            },
        }
        params = {
            "task": "step2",
            "type": TaskLogType.STDOUT,
            "follow": "true",
            "offset": 0,
        }
        queue = asyncio.Queue()

        with (
            patch.object(executor, "_request", return_value=mock_ctx),
            patch.object(
                NomadExecutor,
                "get_last_allocation",
                return_value=refreshed_alloc,
            ) as mock_get_last_allocation,
        ):
            state, out_alloc, stream_start = await executor._consume_nomad_log_stream(
                alloc=alloc,
                step="step2",
                log_type=TaskLogType.STDOUT,
                queue=queue,
                params=params,
                client_timeout=ClientTimeout(sock_read=NOMAD_DEFAULT_TIMEOUT),
                anonymize_entities=None,
            )

        logs = await self._drain_task_logs(queue)

        assert state == RECHECKED_TASK_STATE
        assert out_alloc is refreshed_alloc
        assert stream_start is not None
        mock_get_last_allocation.assert_called_once_with("job-1", "eval-1")
        assert logs == []


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

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_list_files_no_filesystem_returns_empty_dict(self, mock_nomad_cls):
        """Assert list_files returns {} when allocation has no filesystem (prestart 404)."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.allocation.get_allocation.return_value = {
            "ID": "alloc-1",
            "ClientStatus": "failed",
        }

        executor = _build_executor()
        queue_item = _build_queue_item(
            tracking={
                "allocation_id": "alloc-1",
                "evaluation_id": "eval-1",
                "job_id": "job-1",
            }
        )

        mock_response = AsyncMock()
        mock_response.status = status.HTTP_404_NOT_FOUND
        mock_response.raise_for_status = MagicMock()

        mock_ctx_manager = AsyncMock()
        mock_ctx_manager.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx_manager.__aexit__ = AsyncMock(return_value=False)

        with patch.object(executor, "_request", return_value=mock_ctx_manager):
            result = await executor.list_files(queue_item, "/alloc/data")

        assert result == {}
        mock_response.raise_for_status.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_list_files_404_non_failed_alloc_propagates(self, mock_nomad_cls):
        """Assert list_files raises on 404 when alloc status is not failed/lost.

        A 404 on a completed allocation means the output path is misconfigured —
        that error must surface, not be swallowed.
        """
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.allocation.get_allocation.return_value = {
            "ID": "alloc-1",
            "ClientStatus": "complete",
        }

        executor = _build_executor()
        queue_item = _build_queue_item(
            tracking={
                "allocation_id": "alloc-1",
                "evaluation_id": "eval-1",
                "job_id": "job-1",
            }
        )

        mock_response = AsyncMock()
        mock_response.status = status.HTTP_404_NOT_FOUND
        mock_response.raise_for_status = MagicMock(side_effect=ClientError("not found"))

        mock_ctx_manager = AsyncMock()
        mock_ctx_manager.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx_manager.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(executor, "_request", return_value=mock_ctx_manager),
            pytest.raises(ClientError),
        ):
            await executor.list_files(queue_item, "/alloc/data")

        mock_response.raise_for_status.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error_status",
        [status.HTTP_500_INTERNAL_SERVER_ERROR, status.HTTP_403_FORBIDDEN],
    )
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_list_files_non_404_http_errors_propagate(
        self, mock_nomad_cls, error_status
    ):
        """Assert list_files propagates non-404 HTTP errors (outage/auth errors must surface)."""
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
        mock_response.status = error_status
        mock_response.raise_for_status = MagicMock(side_effect=ClientError("error"))

        mock_ctx_manager = AsyncMock()
        mock_ctx_manager.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx_manager.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(executor, "_request", return_value=mock_ctx_manager),
            pytest.raises(ClientError),
        ):
            await executor.list_files(queue_item, "/alloc/data")


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


_NS_EARLY = 1_700_000_000_000_000_000
_NS_LATER = 1_700_000_060_000_000_000


class TestNomadTaskStatesToExecutionEvents:
    """Tests for :func:`nomad_task_states_to_execution_events`."""

    def test_non_dict_returns_empty(self):
        """Absent or wrong-type task_states yields no events."""
        assert nomad_task_states_to_execution_events(None) == []
        assert nomad_task_states_to_execution_events([]) == []
        assert nomad_task_states_to_execution_events("bad") == []

    def test_missing_or_empty_events(self):
        """Empty structures yield an empty list."""
        assert nomad_task_states_to_execution_events({}) == []
        assert nomad_task_states_to_execution_events({"step1": {}}) == []
        assert nomad_task_states_to_execution_events({"step1": {"Events": []}}) == []

    def test_malformed_events_skipped(self):
        """Events without valid Time or non-mapping entries are ignored."""
        task_states = {
            "step1": {
                "Events": [
                    {
                        "Type": "Started",
                        "Time": _NS_EARLY,
                        "DisplayMessage": "Task received",
                    },
                    {"Type": "Broken", "DisplayMessage": "missing Time"},
                    "not-a-dict",
                ],
            },
        }
        events = nomad_task_states_to_execution_events(task_states)
        assert len(events) == 1
        assert events[0].event_type == "Started"
        assert events[0].step == "step1"
        assert "Task received" in events[0].description

    def test_sorted_oldest_first_across_tasks(self):
        """Events from multiple tasks are merged and sorted by Nomad time."""
        task_states = {
            "b": {
                "Events": [
                    {
                        "Type": "Late",
                        "Time": _NS_LATER,
                        "DisplayMessage": "second",
                    },
                ],
            },
            "a": {
                "Events": [
                    {
                        "Type": "Early",
                        "Time": _NS_EARLY,
                        "DisplayMessage": "first",
                    },
                ],
            },
        }
        events = nomad_task_states_to_execution_events(task_states)
        assert len(events) == len(task_states)
        assert "first" in events[0].description
        assert events[0].step == "a"
        assert "second" in events[1].description
        assert events[1].step == "b"

    def test_exit_code_from_details(self):
        """Exit code may appear only under Details (defensive parse)."""
        task_states = {
            "step1": {
                "Events": [
                    {
                        "Type": "Terminated",
                        "Time": _NS_EARLY,
                        "DisplayMessage": "Exited",
                        "Details": {"exit_code": 123},
                    },
                ],
            },
        }
        events = nomad_task_states_to_execution_events(task_states)
        assert len(events) == 1
        assert events[0].event_type == "Terminated"
        assert "123" in events[0].description

    def test_nomad_executor_get_events_reads_tracking(self):
        """NomadExecutor.get_events delegates to stored task_states."""
        tracking = {
            "allocation_id": None,
            "evaluation_id": "eval-1",
            "job_id": "job-1",
            "task_states": {
                "step1": {
                    "Events": [
                        {
                            "Type": "Setup",
                            "Time": _NS_EARLY,
                            "DisplayMessage": "Downloading Artifacts",
                        },
                    ],
                },
            },
        }
        history = _build_queue_item(
            tracking=tracking, status=TaskHistoryStatusEnum.SUCCESS
        )
        executor = _build_executor()
        out = executor.get_events(history)
        assert len(out) == 1
        assert isinstance(out[0], ExecutionEvent)
        assert out[0].event_type == "Setup"
        assert "Downloading Artifacts" in out[0].description
        assert out[0].step == "step1"

    def test_prestart_artifact_download_failure_event_extracted(self):
        """Assert 'Failed Artifact Download' prestart event surfaces as ExecutionEvent."""
        task_states = {
            "step1": {
                "Events": [
                    {
                        "Type": "Failed Artifact Download",
                        "Time": _NS_EARLY,
                        "DisplayMessage": "Failed to download artifact: connection refused",
                    },
                ],
            },
        }
        events = nomad_task_states_to_execution_events(task_states)
        assert len(events) == 1
        assert events[0].event_type == "Failed Artifact Download"
        assert "connection refused" in events[0].description
        assert events[0].step == "step1"

    def test_prestart_setup_failure_event_extracted(self):
        """Assert 'Setup Failure' prestart event surfaces as ExecutionEvent."""
        task_states = {
            "step1": {
                "Events": [
                    {
                        "Type": "Setup Failure",
                        "Time": _NS_EARLY,
                        "DisplayMessage": "failed to setup alloc: artifact download failed",
                    },
                ],
            },
        }
        events = nomad_task_states_to_execution_events(task_states)
        assert len(events) == 1
        assert events[0].event_type == "Setup Failure"
        assert "artifact download failed" in events[0].description
        assert events[0].step == "step1"


class TestPersistNomadTaskLogsCursorDurability:
    """Test durable Nomad fetch-cursor behavior across sync cycles."""

    @staticmethod
    def _reconstruct_stream(chunks, state) -> str:
        """Return the ordered persisted-plus-staged content for one stream."""
        body = "".join(
            chunk.content for chunk in sorted(chunks, key=lambda c: c.start_offset)
        )
        staged = state.staging.decode("utf-8") if state and state.staging else ""
        return body + staged

    @staticmethod
    def _offset_aware_stream(raw_logs: dict):
        """Return a ``stream_logs.stream`` mock that honors the ``offset`` kwarg.

        The mock returns only the raw bytes at or after ``offset`` so a fetch
        that wrongly restarts from ``0`` re-reads content the caller already
        persisted — the exact regression the durable cursor prevents.
        """

        def fake_stream(alloc_id, *, task, type_, offset):
            content = raw_logs.get((task, type_), "")
            delta = content[offset:]
            if not delta:
                return ""
            return json.dumps(
                {"Data": b64encode(delta.encode()).decode(), "Offset": len(content)}
            )

        return fake_stream

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.anonymize_text")
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_cold_worker_second_cycle_resumes_from_db_cursor(
        self,
        mock_nomad_cls,
        mock_anonymize,
        session,
        created_task_with_history,
    ):
        """Assert a cold second cycle resumes from the DB cursor without re-reading.

        With the process-local fetch-offset dict gone, the ``taskhistory_log_state``
        row is the only record of the raw Nomad offset. A second sync cycle that
        lands on a worker without the in-memory cursor must seed from that row;
        otherwise the anonymized run-script stream re-reads from offset ``0`` and
        the producer-offset dedup (``skip == 0``) appends the whole file again.
        """
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_anonymize.side_effect = lambda text, _entities: text.replace(
            "4111", "[REDACTED]"
        )
        raw_logs = {
            ("prepare", TaskLogType.STDOUT): "prepare-A\n",
            ("run-script", TaskLogType.STDOUT): "cc 4111 here\n",
        }
        mock_backend.client.stream_logs.stream.side_effect = self._offset_aware_stream(
            raw_logs
        )

        history = created_task_with_history
        history.anonymize_mask = PIIEntity.CREDIT_CARD.value
        alloc = {
            "ID": "alloc-1",
            "CreateIndex": ALLOCATION_CREATE_INDEX,
            "TaskStates": {
                "prepare": {"StartedAt": "2024-01-01T00:00:00Z"},
                "run-script": {"StartedAt": "2024-01-01T00:00:00Z"},
            },
        }
        executor = _build_executor()

        await executor._persist_nomad_task_logs(
            writer_session=session,
            queue_item=history,
            alloc=alloc,
            previous_allocation_id="alloc-1",
        )
        raw_logs[("prepare", TaskLogType.STDOUT)] = "prepare-A\nprepare-B\n"
        raw_logs[("run-script", TaskLogType.STDOUT)] = "cc 4111 here\nsecond\n"
        await executor._persist_nomad_task_logs(
            writer_session=session,
            queue_item=history,
            alloc=alloc,
            previous_allocation_id="alloc-1",
        )

        chunks = await TaskHistoryLogManager.list_chunks_for_task(session, history.id)
        chunks_by_stream = defaultdict(list)
        for chunk in chunks:
            chunks_by_stream[(chunk.source, chunk.stream)].append(chunk)
        prepare_state = await TaskHistoryLogStateManager.get_for_stream(
            session, history.id, "prepare", TaskLogType.STDOUT
        )
        run_script_state = await TaskHistoryLogStateManager.get_for_stream(
            session, history.id, "run-script", TaskLogType.STDOUT
        )

        assert (
            self._reconstruct_stream(
                chunks_by_stream[("prepare", TaskLogType.STDOUT)], prepare_state
            )
            == "prepare-A\nprepare-B\n"
        )
        assert (
            self._reconstruct_stream(
                chunks_by_stream[("run-script", TaskLogType.STDOUT)],
                run_script_state,
            )
            == "cc [REDACTED] here\nsecond\n"
        )

    @pytest.mark.asyncio
    async def test_build_initial_log_offsets_skips_superseded_epoch_row(
        self, session, created_task_with_history
    ):
        """Assert a row from a different allocation epoch is not used to seed."""
        history = created_task_with_history
        await TaskHistoryLogWriter.append(
            session,
            history.id,
            source="run-script",
            stream=TaskLogType.STDOUT,
            new_bytes=b"old",
            force_flush=True,
            producer_offset_after=SEED_OFFSET,
            nomad_offset_after=SEED_OFFSET,
            allocation_epoch=SUPERSEDED_ALLOCATION_EPOCH,
        )

        offsets = await NomadExecutor._build_initial_log_offsets(
            session, history.id, current_epoch=CURRENT_ALLOCATION_EPOCH
        )

        assert "run-script" not in offsets

    @pytest.mark.asyncio
    async def test_build_initial_log_offsets_seeds_matching_epoch_row(
        self, session, created_task_with_history
    ):
        """Assert a row matching the current epoch seeds both cursors."""
        history = created_task_with_history
        await TaskHistoryLogWriter.append(
            session,
            history.id,
            source="run-script",
            stream=TaskLogType.STDOUT,
            new_bytes=b"cur",
            force_flush=True,
            producer_offset_after=SEED_OFFSET,
            nomad_offset_after=SEED_OFFSET,
            allocation_epoch=CURRENT_ALLOCATION_EPOCH,
        )

        offsets = await NomadExecutor._build_initial_log_offsets(
            session, history.id, current_epoch=CURRENT_ALLOCATION_EPOCH
        )

        assert offsets["run-script"]["stdout_last_offset"] == SEED_OFFSET
        assert offsets["run-script"]["stdout_producer_offset"] == SEED_OFFSET

    @pytest.mark.asyncio
    async def test_build_initial_log_offsets_seeds_legacy_epoch_zero_row(
        self, session, created_task_with_history
    ):
        """Assert a legacy ``allocation_epoch == 0`` row is trusted for seeding."""
        history = created_task_with_history
        await TaskHistoryLogWriter.append(
            session,
            history.id,
            source="run-script",
            stream=TaskLogType.STDOUT,
            new_bytes=b"legacy",
            force_flush=True,
            producer_offset_after=LEGACY_SEED_PRODUCER_OFFSET,
        )

        offsets = await NomadExecutor._build_initial_log_offsets(
            session, history.id, current_epoch=CURRENT_ALLOCATION_EPOCH
        )

        assert "run-script" in offsets
        assert (
            offsets["run-script"]["stdout_producer_offset"]
            == LEGACY_SEED_PRODUCER_OFFSET
        )
