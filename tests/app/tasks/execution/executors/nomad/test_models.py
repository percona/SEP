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
import logging
from base64 import b64encode
from binascii import b2a_base64
from collections import defaultdict
from datetime import datetime, UTC
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientError, ClientTimeout
from fastapi import status
from nomad.api.exceptions import BaseNomadException, URLNotFoundNomadException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import HTTPBadRequestException
from app.core.settings_override.registry import (
    ReloadClassification,
    resolve_nested_field_metadata,
)
from app.core.utils import slugify
from app.tasks.anonymizer.entities import PIIEntity
from app.tasks.config import tasks_settings, TasksSettings
from app.tasks.crud import (
    TaskHistoryLogManager,
    TaskHistoryLogStateManager,
    TaskHistoryManager,
)
from app.tasks.execution.executors.nomad.exceptions import (
    AllocationNotFoundError,
    JobNotFoundError,
)
from app.tasks.execution.executors.nomad.models import (
    _alloc_step_state,
    _ANONYMIZED_STEPS,
    _detect_stale_skip,
    _NOMAD_LOG_STREAM_CLIENT_ERROR,
    _NOMAD_LOG_STREAM_SOCK_TIMEOUT,
    _should_anonymize,
    _STALE_SKIP_TASK_NAME,
    NOMAD_DEAD_JOB_STATUS,
    nomad_task_states_to_execution_events,
    NomadAllocStatusEnum,
    NomadExecutor,
)
from app.tasks.execution.executors.nomad.steps import NomadStep
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
from app.tasks.run_result import RUN_RESULT_FILENAME

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
# Line-split anonymization fixtures: a 16-digit card token straddling frames.
SPLIT_TOKEN_FIRST_FRAME_OFFSET = 13  # raw EOF after "card=41111111"
SPLIT_TOKEN_LINE_EOF_OFFSET = 22  # raw EOF after the completed "card=...\n" line
WITHHELD_PARTIAL_FRAME_EOF_OFFSET = 12  # raw EOF of "ok\ncard=41"
WITHHELD_PARTIAL_RESUME_OFFSET = 5  # cursor rolled back over the withheld "card=41"
MULTIBYTE_LINE_EOF_OFFSET = 12  # raw EOF of "café\n€uro" (6 + 6 UTF-8 bytes)
MULTIBYTE_WITHHELD_BYTES = 6  # raw byte length of the withheld "€uro"
NEWLINELESS_TAIL_FRAME_EOF_OFFSET = 21  # raw EOF of "card=4111111111111111"


def _redact_card_token(text: str, _entities: set[PIIEntity]) -> str:
    """Redact a full 16-digit card token, matching only whole lines.

    Stand-in for ``anonymize_text`` that only matches the complete number, so a
    token split across chunks is redacted only once the line is reassembled.
    """
    return text.replace("4111111111111111", "[REDACTED]")


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
        parameterized_spec = {"Payload": "required"}
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


class TestAnonymizedStepClassification:
    """Assert the redaction guard follows the NomadStep anonymization map."""

    def test_anonymized_steps_stay_run_script_and_step1(self) -> None:
        """Assert the effective anonymized set is exactly run-script and step1."""
        assert frozenset({"run-script", "step1"}) == _ANONYMIZED_STEPS

    @pytest.mark.parametrize("step", [NomadStep.RUN_SCRIPT, NomadStep.STEP1])
    def test_should_anonymize_fires_for_anonymized_steps(self, step: NomadStep) -> None:
        """Assert the guard fires for every step classified as anonymized."""
        assert _should_anonymize(step, {PIIEntity.PERSON}) is True

    @pytest.mark.parametrize(
        "step",
        [NomadStep.PREPARE_ENV, NomadStep.CLEAN_UP, NomadStep.CHECK_STALENESS],
    )
    def test_should_anonymize_stays_off_for_unanonymized_steps(
        self, step: NomadStep
    ) -> None:
        """Assert an unanonymized step stays unredacted even with entities requested.

        Pins the behaviour the classification exists to drive. A set listing only
        the anonymized steps leaves this arm unstated, so nothing fails when a
        newly-added step silently joins the wrong side.
        """
        assert _should_anonymize(step, {PIIEntity.PERSON}) is False

    @pytest.mark.parametrize("step", list(NomadStep))
    def test_no_step_is_anonymized_without_entities(self, step: NomadStep) -> None:
        """Assert no step is redacted when no PII entities were requested."""
        assert _should_anonymize(step, None) is False
        assert _should_anonymize(step, set()) is False

    def test_stale_skip_task_name_is_nomad_step(self) -> None:
        """Assert the stale-skip sentinel is NomadStep.CHECK_STALENESS."""
        assert _STALE_SKIP_TASK_NAME is NomadStep.CHECK_STALENESS
        assert _STALE_SKIP_TASK_NAME == "check-staleness"


class TestNomadExecutorTlsClassification:
    """Assert the inherited TLS leaves classify as advanced + HOT via the overlay.

    These fields are inherited (frozen) from ``BaseRemoteAPI`` and marked only
    through ``NomadExecutor.INHERITED_MARKERS`` -- not by redeclaration.
    """

    @pytest.mark.parametrize(
        "leaf", ["VERIFY_SSL", "SSL_CAFILE", "SSL_KEYFILE", "SSL_CERTFILE"]
    )
    def test_tls_leaves_are_advanced_and_hot(self, leaf: str) -> None:
        """Assert each TLS leaf classifies ``advanced`` + HOT through the settings API."""
        meta = resolve_nested_field_metadata(TasksSettings, f"NOMAD__{leaf}")
        assert meta is not None
        assert meta.is_advanced is True
        assert meta.reload is ReloadClassification.HOT

    def test_endpoint_stays_unmarked(self) -> None:
        """Assert the inherited ``endpoint`` has no overlay entry, so it stays non-advanced."""
        meta = resolve_nested_field_metadata(TasksSettings, "NOMAD__ENDPOINT")
        assert meta is not None
        assert meta.is_advanced is False

    def test_tls_leaves_remain_frozen(self) -> None:
        """Assert dropping the redeclarations keeps ``frozen=True`` inherited from the base."""
        executor = _build_executor()
        with pytest.raises(ValidationError):
            executor.verify_ssl = True

    def test_hash_is_value_stable(self) -> None:
        """Assert two executors with identical config hash equal (identity hash unchanged)."""
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


class TestAllocStepState:
    """Test the module-level ``_alloc_step_state`` helper."""

    def test_returns_state_when_present(self):
        """Assert the step's state is returned untouched when well-formed."""
        state = {"State": "running", "StartedAt": "1"}
        assert _alloc_step_state({"TaskStates": {"step1": state}}, "step1") is state

    @pytest.mark.parametrize(
        "alloc",
        [
            {"ID": "alloc-1"},
            {"ID": "alloc-1", "TaskStates": None},
            {"ID": "alloc-1", "TaskStates": {}},
            {"ID": "alloc-1", "TaskStates": {"other-step": {"State": "running"}}},
        ],
    )
    def test_absent_state_degrades_to_empty(self, alloc: dict[str, Any]):
        """Assert every shape that lacks the step yields an empty state."""
        assert _alloc_step_state(alloc, "step1") == {}

    def test_malformed_state_is_logged_and_degrades_to_empty(
        self, caplog: pytest.LogCaptureFixture
    ):
        """Assert a non-mapping task state is reported instead of silently ignored.

        A missing state is the expected shape for a task that never started; a
        state that is present but not a mapping is a broken Nomad contract, so
        it must leave a trace rather than look identical to not-started.
        """
        alloc = {"ID": "alloc-1", "TaskStates": {"step1": "not a mapping"}}

        with caplog.at_level(logging.WARNING):
            assert _alloc_step_state(alloc, "step1") == {}

        assert "non-mapping task state" in caplog.text
        assert "alloc-1" in caplog.text


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

    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_get_last_allocation_absent_task_states(self, mock_nomad_cls):
        """Assert an allocation stub without a ``TaskStates`` key is returned as-is."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.allocations.get_allocations.return_value = [
            {"ID": "alloc-1", "JobID": "job-1"}
        ]

        executor = _build_executor()
        result = executor.get_last_allocation(job_id="job-1")
        assert result == {"ID": "alloc-1", "JobID": "job-1"}


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

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    @patch("app.tasks.execution.models.schedule_annotation")
    async def test_stop_task_with_task_states_less_allocation_reaches_stopped(
        self,
        mock_annotation: MagicMock,
        mock_nomad_cls: MagicMock,
        session: AsyncSession,
        created_task_with_history: TaskHistory,
    ):
        """Assert stopping a row backed by a TaskStates-less allocation terminates it.

        ``stop_task`` syncs before it writes the status, so a sync that raised
        left the row RUNNING and answered the request with a 500 — the row could
        then never be cleared through the API. Nomad is the only mocked
        boundary: the real ``TaskHistoryManager.save`` / ``session.refresh``
        lifecycle runs, and the row is refetched to prove it persisted.
        """
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.allocation.get_allocation.return_value = {
            "ID": "alloc-2",
            "JobID": "job-1",
            "EvalID": "eval-1",
            "ClientStatus": NomadAllocStatusEnum.PENDING,
        }
        mock_backend.job.get_job.return_value = {
            "ID": "job-1",
            "Status": "running",
            "Stop": False,
        }

        queue_item = created_task_with_history
        queue_item.task.alert_on_fail = False
        queue_item.status = TaskHistoryStatusEnum.RUNNING
        queue_item.execution_request.tracking = {
            "allocation_id": "alloc-1",
            "evaluation_id": "eval-1",
            "job_id": "job-1",
        }

        result = await _build_executor().stop_task(session, queue_item)

        assert result.status == TaskHistoryStatusEnum.STOPPED
        assert result.finished_at is not None
        mock_backend.job.deregister_job.assert_called_once_with("job-1")
        mock_annotation.assert_called_once_with(result, "STOPPED")

        result_id = result.id
        await session.rollback()
        refetched = await TaskHistoryManager.get_or_404(session, id=result_id)
        assert refetched.status == TaskHistoryStatusEnum.STOPPED
        assert refetched.finished_at is not None


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


class TestSyncTaskHistoryWithoutTaskStates:
    """Test _sync_task_history against an allocation carrying no ``TaskStates``.

    Nomad's reschedule chain lands on an allocation that exists but has not
    started any task once the client running the original allocation goes away.
    Reading ``TaskStates`` off that shape used to raise ``KeyError``, which left
    the row RUNNING forever and made ``stop`` -- the endpoint meant to clear it
    -- fail with a 500.
    """

    @staticmethod
    def _alloc(**overrides: Any) -> dict[str, Any]:
        """Return an allocation dict with no ``TaskStates`` key at all.

        :param overrides: Fields to add to or replace on the allocation.
        :return: The allocation dict as Nomad returned it, ``TaskStates``-less.
        """
        return {
            "ID": "alloc-2",
            "JobID": "job-1",
            "EvalID": "eval-1",
            "ClientStatus": NomadAllocStatusEnum.PENDING,
        } | overrides

    @staticmethod
    def _queue_item() -> TaskHistory:
        """Return a RUNNING task history tracking ``alloc-1``/``job-1``."""
        return _build_queue_item(
            tracking={
                "allocation_id": "alloc-1",
                "evaluation_id": "eval-1",
                "job_id": "job-1",
            },
            status=TaskHistoryStatusEnum.RUNNING,
        )

    @staticmethod
    def _backend(
        mock_nomad_cls: MagicMock,
        alloc: dict[str, Any],
        job: dict[str, Any] | None = None,
    ) -> MagicMock:
        """Wire a Nomad backend mock returning ``alloc`` and a live job.

        :param mock_nomad_cls: The patched ``Nomad`` class.
        :param alloc: The allocation to return from both lookup paths.
        :param job: The job to return; defaults to a still-running job.
        :return: The backend mock.
        """
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.allocation.get_allocation.return_value = alloc
        mock_backend.allocations.get_allocations.return_value = [alloc]
        mock_backend.client.stream_logs.stream.return_value = ""
        mock_backend.job.get_job.return_value = job or {
            "ID": "job-1",
            "Status": "running",
            "Stop": False,
        }
        return mock_backend

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_pending_allocation_stays_running(self, mock_nomad_cls):
        """Assert a still-starting allocation does not raise and remains RUNNING."""
        self._backend(mock_nomad_cls, self._alloc())
        executor = _build_executor()

        result = await executor._sync_task_history(self._queue_item())

        assert result.status == TaskHistoryStatusEnum.RUNNING
        assert result.finished_at is None
        assert result.execution_request.tracking["task_states"] == {}
        assert result.execution_request.tracking["allocation_id"] == "alloc-2"

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_followup_eval_chain_does_not_raise(self, mock_nomad_cls):
        """Assert the reschedule chain tolerates a ``TaskStates``-less successor."""
        first_alloc = {
            "ID": "alloc-1",
            "JobID": "job-1",
            "EvalID": "eval-1",
            "FollowupEvalID": "eval-followup",
            "ClientStatus": NomadAllocStatusEnum.LOST,
            "TaskStates": {"step1": {"StartedAt": "1", "FinishedAt": None}},
        }
        mock_backend = self._backend(
            mock_nomad_cls, self._alloc(EvalID="eval-followup")
        )
        mock_backend.allocation.get_allocation.return_value = first_alloc

        executor = _build_executor()
        result = await executor._sync_task_history(self._queue_item())

        assert result.status == TaskHistoryStatusEnum.RUNNING
        assert result.execution_request.tracking["allocation_id"] == "alloc-2"

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_lost_client_status_reaches_terminal_status(self, mock_nomad_cls):
        """Assert a lost allocation moves the row to LOST with a finish time."""
        self._backend(
            mock_nomad_cls,
            self._alloc(
                ClientStatus=NomadAllocStatusEnum.LOST,
                ModifyTime=1_700_000_000_000_000_000,
            ),
        )
        executor = _build_executor()

        result = await executor._sync_task_history(self._queue_item())

        assert result.status == TaskHistoryStatusEnum.LOST
        assert result.finished_at == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_unknown_client_status_without_modify_time(self, mock_nomad_cls):
        """Assert an unknown allocation lands LOST and still stamps ``finished_at``."""
        self._backend(
            mock_nomad_cls, self._alloc(ClientStatus=NomadAllocStatusEnum.UNKNOWN)
        )
        executor = _build_executor()

        result = await executor._sync_task_history(self._queue_item())

        assert result.status == TaskHistoryStatusEnum.LOST
        assert result.finished_at is not None

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_failed_client_status_reaches_failed(self, mock_nomad_cls):
        """Assert a failed allocation with no task states maps to FAILED."""
        self._backend(
            mock_nomad_cls, self._alloc(ClientStatus=NomadAllocStatusEnum.FAILED)
        )
        executor = _build_executor()

        result = await executor._sync_task_history(self._queue_item())

        assert result.status == TaskHistoryStatusEnum.FAILED

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_absent_client_status_stays_running(self, mock_nomad_cls):
        """Assert a stub without ``ClientStatus`` is never given a terminal status."""
        alloc = self._alloc()
        del alloc["ClientStatus"]
        self._backend(mock_nomad_cls, alloc)
        executor = _build_executor()

        result = await executor._sync_task_history(self._queue_item())

        assert result.status == TaskHistoryStatusEnum.RUNNING

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_populated_task_states_keep_live_row_running(self, mock_nomad_cls):
        """Assert the empty-task-states branch does not touch a started allocation.

        A ``lost`` client status on an allocation that *did* start is left to the
        existing dead-job path, so a live row is not terminated early.
        """
        self._backend(
            mock_nomad_cls,
            self._alloc(
                ClientStatus=NomadAllocStatusEnum.LOST,
                TaskStates={"step1": {"StartedAt": "1", "FinishedAt": None}},
            ),
        )
        executor = _build_executor()

        result = await executor._sync_task_history(self._queue_item())

        assert result.status == TaskHistoryStatusEnum.RUNNING
        assert result.finished_at is None

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_dead_job_path_stamps_finished_at_once(self, mock_nomad_cls):
        """Assert a dead job with no task states still resolves via the job branch."""
        self._backend(
            mock_nomad_cls,
            self._alloc(
                ClientStatus=NomadAllocStatusEnum.COMPLETE,
                ModifyTime=1_700_000_000_000_000_000,
            ),
            job={"ID": "job-1", "Status": NOMAD_DEAD_JOB_STATUS, "Stop": False},
        )
        executor = _build_executor()

        result = await executor._sync_task_history(self._queue_item())

        assert result.status == TaskHistoryStatusEnum.SUCCESS
        assert result.finished_at == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)


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
    def test_get_logs_for_allocation_absent_task_states(self, mock_nomad_cls):
        """Assert an allocation without a ``TaskStates`` key yields no logs.

        This read runs on the Celery sync path (``writer_session`` is supplied
        there), so an absent key must not raise either.
        """
        mock_nomad_cls.return_value = MagicMock()
        executor = _build_executor()
        result = executor.get_logs_for_allocation({"ID": "alloc-1"})
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

        raw_msg = b64encode(b"sensitive data\n").decode()
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
        raw_bytes = b"4111-1111-1111-1111\n"
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
        raw_bytes = b"4111-1111-1111-1111\n"
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

    @patch("app.tasks.execution.executors.nomad.models.anonymize_text")
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_get_logs_for_allocation_redacts_token_split_across_frames(
        self, mock_nomad_cls, mock_anonymize
    ):
        """Assert a token split across two frames of one fetch is redacted.

        Per-frame anonymization would see ``card=41111111`` and
        ``11111111`` separately and match neither; joining the frames before
        anonymization lets Presidio see the whole token.
        """
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_anonymize.side_effect = _redact_card_token
        frame_one = json.dumps(
            {
                "Data": b64encode(b"card=41111111").decode(),
                "Offset": SPLIT_TOKEN_FIRST_FRAME_OFFSET,
            }
        )
        frame_two = json.dumps(
            {
                "Data": b64encode(b"11111111\n").decode(),
                "Offset": SPLIT_TOKEN_LINE_EOF_OFFSET,
            }
        )
        mock_backend.client.stream_logs.stream.return_value = frame_one + frame_two
        alloc = {
            "ID": "alloc-1",
            "TaskStates": {"run-script": {"StartedAt": "2024-01-01T00:00:00Z"}},
        }

        executor = _build_executor()
        result = executor.get_logs_for_allocation(
            alloc, anonymize_entities={PIIEntity.CREDIT_CARD}
        )

        assert result["run-script"]["stdout"] == "card=[REDACTED]\n"
        assert "4111" not in result["run-script"]["stdout"]
        assert result["run-script"]["stdout_last_offset"] == SPLIT_TOKEN_LINE_EOF_OFFSET
        assert result["run-script"]["stdout_withheld"] == 0

    @patch("app.tasks.execution.executors.nomad.models.anonymize_text")
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_get_logs_for_allocation_withholds_partial_line_across_cycles(
        self, mock_nomad_cls, mock_anonymize
    ):
        """Assert a token straddling a sync-cycle boundary is redacted.

        Cycle one ends mid-token with no newline: the partial line is withheld
        and the Nomad cursor is rolled back by its raw byte length, so cycle two
        re-fetches the bytes, joins the completed line, and redacts it.
        """
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_anonymize.side_effect = _redact_card_token
        cycle_one = json.dumps(
            {
                "Data": b64encode(b"card=41111111").decode(),
                "Offset": SPLIT_TOKEN_FIRST_FRAME_OFFSET,
            }
        )
        cycle_two = json.dumps(
            {
                "Data": b64encode(b"card=4111111111111111\n").decode(),
                "Offset": SPLIT_TOKEN_LINE_EOF_OFFSET,
            }
        )
        mock_backend.client.stream_logs.stream.side_effect = [
            cycle_one,  # run-script stdout, cycle 1
            "",  # run-script stderr, cycle 1
            cycle_two,  # run-script stdout, cycle 2
            "",  # run-script stderr, cycle 2
        ]
        alloc = {
            "ID": "alloc-1",
            "TaskStates": {"run-script": {"StartedAt": "2024-01-01T00:00:00Z"}},
        }

        executor = _build_executor()
        first = executor.get_logs_for_allocation(
            alloc, anonymize_entities={PIIEntity.CREDIT_CARD}
        )

        assert first["run-script"]["stdout"] == ""
        assert first["run-script"]["stdout_last_offset"] == 0  # rolled back past token
        assert first["run-script"]["stdout_withheld"] == SPLIT_TOKEN_FIRST_FRAME_OFFSET

        second = executor.get_logs_for_allocation(
            alloc,
            initial_logs={
                "run-script": {
                    "stdout_last_offset": first["run-script"]["stdout_last_offset"],
                    "stdout_producer_offset": first["run-script"][
                        "stdout_producer_offset"
                    ],
                }
            },
            anonymize_entities={PIIEntity.CREDIT_CARD},
        )

        assert second["run-script"]["stdout"] == "card=[REDACTED]\n"
        assert "4111" not in second["run-script"]["stdout"]
        assert second["run-script"]["stdout_last_offset"] == SPLIT_TOKEN_LINE_EOF_OFFSET
        assert second["run-script"]["stdout_withheld"] == 0

    @patch("app.tasks.execution.executors.nomad.models.anonymize_text")
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_get_logs_for_allocation_multibyte_split_not_corrupted(
        self, mock_nomad_cls, mock_anonymize
    ):
        """Assert the line split never cleaves a multi-byte UTF-8 codepoint.

        The complete portion ends after a multi-byte char and the withheld
        remainder both starts and continues with multi-byte chars; the emitted
        delta must decode cleanly and the cursor roll back by the exact raw byte
        length of the remainder.
        """
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_anonymize.side_effect = _redact_card_token
        raw_bytes = "café\n€uro".encode()
        frame = json.dumps(
            {
                "Data": b64encode(raw_bytes).decode(),
                "Offset": MULTIBYTE_LINE_EOF_OFFSET,
            }
        )
        mock_backend.client.stream_logs.stream.return_value = frame
        alloc = {
            "ID": "alloc-1",
            "TaskStates": {"run-script": {"StartedAt": "2024-01-01T00:00:00Z"}},
        }

        executor = _build_executor()
        result = executor.get_logs_for_allocation(
            alloc, anonymize_entities={PIIEntity.CREDIT_CARD}
        )

        assert result["run-script"]["stdout"] == "café\n"
        assert result["run-script"]["stdout_withheld"] == MULTIBYTE_WITHHELD_BYTES
        assert result["run-script"]["stdout_last_offset"] == (
            MULTIBYTE_LINE_EOF_OFFSET - MULTIBYTE_WITHHELD_BYTES
        )

    @patch("app.tasks.execution.executors.nomad.models.anonymize_text")
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    def test_get_logs_for_allocation_flush_partial_emits_newlineless_tail(
        self, mock_nomad_cls, mock_anonymize
    ):
        """Assert flush_partial emits a trailing line that never gets a newline."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_anonymize.side_effect = _redact_card_token
        raw_bytes = b"card=4111111111111111"  # no terminating newline
        frame = json.dumps(
            {"Data": b64encode(raw_bytes).decode(), "Offset": len(raw_bytes)}
        )
        alloc = {
            "ID": "alloc-1",
            "TaskStates": {"run-script": {"StartedAt": "2024-01-01T00:00:00Z"}},
        }
        executor = _build_executor()

        mock_backend.client.stream_logs.stream.return_value = frame
        withheld = executor.get_logs_for_allocation(
            alloc, anonymize_entities={PIIEntity.CREDIT_CARD}
        )
        assert withheld["run-script"]["stdout"] == ""
        assert withheld["run-script"]["stdout_withheld"] == len(raw_bytes)

        mock_backend.client.stream_logs.stream.return_value = frame
        flushed = executor.get_logs_for_allocation(
            alloc,
            anonymize_entities={PIIEntity.CREDIT_CARD},
            flush_partial=True,
        )
        assert flushed["run-script"]["stdout"] == "card=[REDACTED]"
        assert flushed["run-script"]["stdout_withheld"] == 0
        assert flushed["run-script"]["stdout_last_offset"] == len(raw_bytes)


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
        frame = {"Offset": offset}
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
                pending=bytearray(),
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
                pending=bytearray(),
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
                pending=bytearray(),
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
                pending=bytearray(),
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
    @patch("app.tasks.execution.executors.nomad.models.anonymize_text")
    async def test_consume_stream_redacts_token_split_across_frames(
        self, mock_anonymize
    ):
        """Assert a token split across two live frames is redacted once whole."""
        mock_anonymize.side_effect = _redact_card_token
        chunks = [
            self._nomad_log_frame(
                msg="card=41111111", offset=SPLIT_TOKEN_FIRST_FRAME_OFFSET
            ),
            self._nomad_log_frame(msg="11111111\n", offset=SPLIT_TOKEN_LINE_EOF_OFFSET),
        ]
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.content.iter_chunks = self._make_iter_chunks(chunks)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        executor = _build_executor()
        alloc = {
            "ID": "alloc-stream",
            "JobID": "job-1",
            "EvalID": "eval-1",
            "TaskStates": {
                "run-script": {"StartedAt": "2024-01-01T00:00:00Z", "State": "running"}
            },
        }
        params = {
            "task": "run-script",
            "type": TaskLogType.STDOUT,
            "follow": "true",
            "offset": 0,
        }
        queue = asyncio.Queue()

        with patch.object(executor, "_request", return_value=mock_ctx):
            await executor._consume_nomad_log_stream(
                alloc=alloc,
                step="run-script",
                log_type=TaskLogType.STDOUT,
                queue=queue,
                params=params,
                client_timeout=ClientTimeout(sock_read=NOMAD_DEFAULT_TIMEOUT),
                anonymize_entities={PIIEntity.CREDIT_CARD},
                pending=bytearray(),
            )

        logs = await self._drain_task_logs(queue)
        assert [log.msg for log in logs] == ["card=[REDACTED]\n"]
        assert "4111" not in logs[0].msg
        assert logs[0].offset == SPLIT_TOKEN_LINE_EOF_OFFSET

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.anonymize_text")
    async def test_consume_stream_withholds_partial_and_rolls_back_offset(
        self, mock_anonymize
    ):
        """Assert the emitted offset is rolled back over a withheld partial line."""
        mock_anonymize.side_effect = _redact_card_token
        chunks = [
            self._nomad_log_frame(
                msg="ok\ncard=41", offset=WITHHELD_PARTIAL_FRAME_EOF_OFFSET
            )
        ]
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.content.iter_chunks = self._make_iter_chunks(chunks)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        executor = _build_executor()
        alloc = {
            "ID": "alloc-stream",
            "JobID": "job-1",
            "EvalID": "eval-1",
            "TaskStates": {
                "run-script": {"StartedAt": "2024-01-01T00:00:00Z", "State": "running"}
            },
        }
        params = {
            "task": "run-script",
            "type": TaskLogType.STDOUT,
            "follow": "true",
            "offset": 0,
        }
        queue = asyncio.Queue()
        pending = bytearray()

        with patch.object(executor, "_request", return_value=mock_ctx):
            await executor._consume_nomad_log_stream(
                alloc=alloc,
                step="run-script",
                log_type=TaskLogType.STDOUT,
                queue=queue,
                params=params,
                client_timeout=ClientTimeout(sock_read=NOMAD_DEFAULT_TIMEOUT),
                anonymize_entities={PIIEntity.CREDIT_CARD},
                pending=pending,
            )

        logs = await self._drain_task_logs(queue)
        assert [log.msg for log in logs] == ["ok\n"]
        # raw EOF (12) minus the 7 withheld bytes of "card=41"
        assert logs[0].offset == WITHHELD_PARTIAL_RESUME_OFFSET
        assert bytes(pending) == b"card=41"  # carried for the next frame
        assert (
            params["offset"] == WITHHELD_PARTIAL_FRAME_EOF_OFFSET
        )  # raw resume cursor

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.anonymize_text")
    async def test_push_logs_flushes_withheld_tail_on_stream_end(self, mock_anonymize):
        """Assert a newline-less withheld tail is flushed before the end sentinel."""
        mock_anonymize.side_effect = _redact_card_token

        async def iter_chunks():
            yield (
                self._nomad_log_frame(
                    msg="card=4111111111111111",
                    offset=NEWLINELESS_TAIL_FRAME_EOF_OFFSET,
                ),
                None,
            )
            raise TimeoutError

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.content.iter_chunks = iter_chunks
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        executor = _build_executor()
        queue = asyncio.Queue()

        with (
            patch.object(executor, "_request", return_value=mock_ctx),
            patch.object(executor, "_log_stream_timeout"),
        ):
            await executor._push_logs_to_queue(
                self._alloc_for_logs(),
                "run-script",
                TaskLogType.STDOUT,
                queue,
                start_offset=0,
                anonymize_entities={PIIEntity.CREDIT_CARD},
            )

        logs = await self._drain_task_logs(queue)
        assert logs[0].msg == "card=[REDACTED]"
        assert "4111" not in logs[0].msg
        assert logs[-1].msg is None  # end-of-stream sentinel comes last

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
                pending=bytearray(),
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
                pending=bytearray(),
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
                pending=bytearray(),
            )

        logs = await self._drain_task_logs(queue)

        assert state == RECHECKED_TASK_STATE
        assert out_alloc is refreshed_alloc
        assert stream_start is not None
        mock_get_last_allocation.assert_called_once_with("job-1", "eval-1")
        assert logs == []

    @pytest.mark.asyncio
    @patch(
        "app.tasks.execution.executors.nomad.models.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_consume_nomad_log_stream_404_absent_task_states_waits(
        self, mock_sleep
    ):
        """Treat a 404 on a TaskStates-less allocation as not-started-yet."""
        mock_response = MagicMock()
        mock_response.status = 404
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        executor = _build_executor()
        alloc = {"ID": "alloc-stream", "JobID": "job-1", "EvalID": "eval-1"}
        params = {
            "task": "step1",
            "type": TaskLogType.STDOUT,
            "follow": "true",
            "offset": 0,
        }

        with patch.object(executor, "_request", return_value=mock_ctx):
            state, out_alloc, stream_start = await executor._consume_nomad_log_stream(
                alloc=alloc,
                step="step1",
                log_type=TaskLogType.STDOUT,
                queue=asyncio.Queue(),
                params=params,
                client_timeout=ClientTimeout(sock_read=NOMAD_DEFAULT_TIMEOUT),
                anonymize_entities=None,
                pending=bytearray(),
            )

        assert state == "running"
        assert out_alloc is alloc
        assert stream_start is None
        mock_sleep.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_consume_nomad_log_stream_recheck_missing_step_ends_stream(self):
        """End the stream loop when a refreshed allocation dropped the step.

        ``_push_logs_to_queue`` loops while the returned state is ``running``, so
        a rescheduled allocation whose task states no longer carry this step must
        yield a non-``running`` state rather than spin forever.
        """
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
        refreshed_alloc = {"ID": "alloc-rescheduled", "JobID": "job-1", "EvalID": "e-2"}
        params = {
            "task": "step2",
            "type": TaskLogType.STDOUT,
            "follow": "true",
            "offset": 0,
        }

        with (
            patch.object(executor, "_request", return_value=mock_ctx),
            patch.object(
                NomadExecutor, "get_last_allocation", return_value=refreshed_alloc
            ),
        ):
            state, out_alloc, _ = await executor._consume_nomad_log_stream(
                alloc=alloc,
                step="step2",
                log_type=TaskLogType.STDOUT,
                queue=asyncio.Queue(),
                params=params,
                client_timeout=ClientTimeout(sock_read=NOMAD_DEFAULT_TIMEOUT),
                anonymize_entities=None,
                pending=bytearray(),
            )

        assert state != "running"
        assert out_alloc is refreshed_alloc

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_stream_logs_absent_task_states_yields_sentinel(self, mock_nomad_cls):
        """Assert streaming an allocation with no TaskStates key yields the sentinel."""
        mock_nomad_cls.return_value = MagicMock()
        executor = _build_executor()
        queue_item = _build_queue_item(
            tracking={
                "allocation_id": "alloc-1",
                "evaluation_id": "eval-1",
                "job_id": "job-1",
            }
        )

        with patch.object(
            NomadExecutor,
            "get_last_allocation",
            return_value={"ID": "alloc-1", "JobID": "job-1", "EvalID": "eval-1"},
        ):
            emitted = [log async for log in executor.stream_logs(queue_item)]

        assert emitted == [None]


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
    async def test_list_files_excludes_the_run_result_file(self, mock_nomad_cls):
        """Assert SEP's own run-result file never reaches the output-files browser."""
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
                {"Name": "backup.sql", "Size": 1024, "IsDir": False},
                {"Name": RUN_RESULT_FILENAME, "Size": 96, "IsDir": False},
            ]
        )

        mock_ctx_manager = AsyncMock()
        mock_ctx_manager.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx_manager.__aexit__ = AsyncMock(return_value=False)

        with patch.object(executor, "_request", return_value=mock_ctx_manager):
            result = await executor.list_files(queue_item, "/alloc/data")

        assert RUN_RESULT_FILENAME not in result
        assert "backup.sql" in result

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
    @patch("app.tasks.execution.executors.nomad.models.anonymize_text")
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_stream_file_without_anonymization(
        self, mock_nomad_cls, mock_anonymize
    ):
        """Assert anonymize=False returns content verbatim despite set entities."""
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

        file_content = b'{"size_bytes": 20260725}'
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
                async for chunk in executor.stream_file(
                    queue_item, "/output/.sep-run-result.json", anonymize=False
                )
            ]

        assert b"".join(chunks) == file_content
        mock_anonymize.assert_not_called()

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

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_stream_file_directory_forwards_anonymize_flag(self, mock_nomad_cls):
        """Assert the anonymize flag reaches the directory archiving path."""
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

        tar_gz = MagicMock(side_effect=fake_tar_gz)
        with (
            patch.object(executor, "_request", side_effect=mock_request),
            patch.object(executor, "_stream_directory_as_tar_gz", tar_gz),
        ):
            [
                chunk
                async for chunk in executor.stream_file(
                    queue_item, "/output/subdir", anonymize=False
                )
            ]

        assert tar_gz.call_args.kwargs["anonymize"] is False


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
    @patch("app.tasks.execution.executors.nomad.models.anonymize_text")
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_read_file_bytes_without_anonymization(
        self, mock_nomad_cls, mock_anonymize
    ):
        """Assert anonymize=False returns content verbatim despite set entities."""
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
                queue_item, "alloc-1", "/f.txt", len(content), anonymize=False
            )

        assert result == content
        mock_anonymize.assert_not_called()

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
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_absent_task_states_persists_nothing(
        self,
        mock_nomad_cls,
        session,
        created_task_with_history,
    ):
        """Assert the Celery log-persistence path tolerates a TaskStates-less alloc.

        ``sync_running_items`` supplies a ``writer_session``, so this branch runs
        on every periodic sync of a rescheduled allocation.
        """
        mock_nomad_cls.return_value = MagicMock()
        executor = _build_executor()
        created_task_with_history.anonymize_mask = 0

        await executor._persist_nomad_task_logs(
            writer_session=session,
            queue_item=created_task_with_history,
            alloc={"ID": "alloc-rescheduled", "CreateIndex": ALLOCATION_CREATE_INDEX},
            previous_allocation_id="alloc-1",
        )

        chunks = await TaskHistoryLogManager.list_chunks_for_task(
            session, created_task_with_history.id
        )
        assert chunks == []

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


class TestDrainTerminalLogs:
    """Exercise the bounded post-terminal log drain in ``_persist_nomad_task_logs``."""

    DRAIN_MAX_ATTEMPTS = 5
    SHORT_DRAIN_MAX_ATTEMPTS = 3
    EXPECTED_SLEEPS_ALL_STREAMS_DRAINED = 2

    @staticmethod
    def _reconstruct_stream(chunks, state) -> str:
        """Return the ordered persisted-plus-staged content for one stream."""
        body = "".join(
            chunk.content for chunk in sorted(chunks, key=lambda c: c.start_offset)
        )
        staged = state.staging.decode("utf-8") if state and state.staging else ""
        return body + staged

    @staticmethod
    def _growing_stream(snapshots: dict[tuple, list[str]]):
        """Return a ``stream_logs.stream`` mock that reveals content over calls.

        ``snapshots[(task, type_)]`` is the cumulative on-disk content visible on
        each successive call to that stream; once the list is exhausted the last
        snapshot repeats. Every call honors the ``offset`` kwarg and returns only
        ``content[offset:]`` (or ``""`` when nothing new is on disk), modelling
        Nomad's non-blocking single-shot read as ``logmon`` flushes the tail.
        """
        calls = defaultdict(int)

        def fake_stream(alloc_id, *, task, type_, offset):
            series = snapshots.get((task, type_), [""])
            idx = min(calls[(task, type_)], len(series) - 1)
            calls[(task, type_)] += 1
            content = series[idx]
            delta = content[offset:]
            if not delta:
                return ""
            return json.dumps(
                {"Data": b64encode(delta.encode()).decode(), "Offset": len(content)}
            )

        return fake_stream

    @staticmethod
    def _terminal_alloc(*steps: str) -> dict:
        """Return an allocation dict with the given steps already started."""
        return {
            "ID": "alloc-1",
            "CreateIndex": ALLOCATION_CREATE_INDEX,
            "TaskStates": {
                step: {"StartedAt": "2024-01-01T00:00:00Z"} for step in steps
            },
        }

    async def _stream_content(self, session, history_id, step, stream) -> str:
        """Return the full persisted-plus-staged content for one stream."""
        chunks = [
            chunk
            for chunk in await TaskHistoryLogManager.list_chunks_for_task(
                session, history_id
            )
            if chunk.source == step and chunk.stream == stream
        ]
        state = await TaskHistoryLogStateManager.get_for_stream(
            session, history_id, step, stream
        )
        return self._reconstruct_stream(chunks, state)

    @pytest.mark.asyncio
    @patch(
        "app.tasks.execution.executors.nomad.models.asyncio.sleep",
        new_callable=AsyncMock,
    )
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_lagging_tail_captured_across_drain_reads(
        self, mock_nomad_cls, mock_sleep, session, created_task_with_history
    ):
        """Assert a tail ``logmon`` flushes after terminal detection is captured."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.client.stream_logs.stream.side_effect = self._growing_stream(
            {("run-script", TaskLogType.STDOUT): ["partial\n", "partial\ntail\n"]}
        )
        history = created_task_with_history
        history.anonymize_mask = 0
        history.status = TaskHistoryStatusEnum.SUCCESS
        executor = _build_executor(
            terminal_log_drain_max_attempts=self.DRAIN_MAX_ATTEMPTS
        )

        await executor._persist_nomad_task_logs(
            writer_session=session,
            queue_item=history,
            alloc=self._terminal_alloc("run-script"),
            previous_allocation_id="alloc-1",
        )

        content = await self._stream_content(
            session, history.id, "run-script", TaskLogType.STDOUT
        )
        assert content == "partial\ntail\n"
        mock_sleep.assert_awaited()

    @pytest.mark.asyncio
    @patch(
        "app.tasks.execution.executors.nomad.models.asyncio.sleep",
        new_callable=AsyncMock,
    )
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_empty_first_retry_does_not_end_drain(
        self, mock_nomad_cls, mock_sleep, session, created_task_with_history
    ):
        """Assert an empty first retry does not end the drain before the tail lands."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.client.stream_logs.stream.side_effect = self._growing_stream(
            {
                ("run-script", TaskLogType.STDOUT): [
                    "partial\n",
                    "partial\n",
                    "partial\ntail\n",
                ]
            }
        )
        history = created_task_with_history
        history.anonymize_mask = 0
        history.status = TaskHistoryStatusEnum.SUCCESS
        executor = _build_executor(
            terminal_log_drain_max_attempts=self.DRAIN_MAX_ATTEMPTS
        )

        await executor._persist_nomad_task_logs(
            writer_session=session,
            queue_item=history,
            alloc=self._terminal_alloc("run-script"),
            previous_allocation_id="alloc-1",
        )

        content = await self._stream_content(
            session, history.id, "run-script", TaskLogType.STDOUT
        )
        assert content == "partial\ntail\n"
        assert mock_sleep.await_count == self.DRAIN_MAX_ATTEMPTS

    @pytest.mark.asyncio
    @patch(
        "app.tasks.execution.executors.nomad.models.asyncio.sleep",
        new_callable=AsyncMock,
    )
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_early_exit_when_all_streams_drained(
        self, mock_nomad_cls, mock_sleep, session, created_task_with_history
    ):
        """Assert the drain early-exits once every active stream drains then quiets."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.client.stream_logs.stream.side_effect = self._growing_stream(
            {
                ("run-script", TaskLogType.STDOUT): ["out\n", "out\ntail\n"],
                ("run-script", TaskLogType.STDERR): ["err\n", "err\ndone\n"],
            }
        )
        history = created_task_with_history
        history.anonymize_mask = 0
        history.status = TaskHistoryStatusEnum.SUCCESS
        executor = _build_executor(
            terminal_log_drain_max_attempts=self.DRAIN_MAX_ATTEMPTS
        )

        await executor._persist_nomad_task_logs(
            writer_session=session,
            queue_item=history,
            alloc=self._terminal_alloc("run-script"),
            previous_allocation_id="alloc-1",
        )

        stdout = await self._stream_content(
            session, history.id, "run-script", TaskLogType.STDOUT
        )
        stderr = await self._stream_content(
            session, history.id, "run-script", TaskLogType.STDERR
        )
        assert stdout == "out\ntail\n"
        assert stderr == "err\ndone\n"
        assert mock_sleep.await_count == self.EXPECTED_SLEEPS_ALL_STREAMS_DRAINED

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.anonymize_text")
    @patch(
        "app.tasks.execution.executors.nomad.models.asyncio.sleep",
        new_callable=AsyncMock,
    )
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_terminal_drain_flushes_newlineless_anonymized_tail(
        self,
        mock_nomad_cls,
        mock_sleep,
        mock_anonymize,
        session,
        created_task_with_history,
    ):
        """Assert a newline-less anonymized tail is flushed, not withheld forever."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_anonymize.side_effect = _redact_card_token
        mock_backend.client.stream_logs.stream.side_effect = self._growing_stream(
            {("run-script", TaskLogType.STDOUT): ["", "card=4111111111111111"]}
        )
        history = created_task_with_history
        history.anonymize_mask = PIIEntity.CREDIT_CARD.value
        history.status = TaskHistoryStatusEnum.SUCCESS
        executor = _build_executor(
            terminal_log_drain_max_attempts=self.DRAIN_MAX_ATTEMPTS
        )

        await executor._persist_nomad_task_logs(
            writer_session=session,
            queue_item=history,
            alloc=self._terminal_alloc("run-script"),
            previous_allocation_id="alloc-1",
        )

        content = await self._stream_content(
            session, history.id, "run-script", TaskLogType.STDOUT
        )
        assert content == "card=[REDACTED]"
        assert "4111" not in content

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.anonymize_text")
    @patch(
        "app.tasks.execution.executors.nomad.models.asyncio.sleep",
        new_callable=AsyncMock,
    )
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_terminal_drain_not_fooled_by_withheld_partial(
        self,
        mock_nomad_cls,
        mock_sleep,
        mock_anonymize,
        session,
        created_task_with_history,
    ):
        """Assert the early-exit does not fire while a stream withholds a partial.

        Both streams advance then quiet, which would normally early-exit; but
        stdout still holds a withheld partial, so the loop must poll the full
        window and the completed tail must be redacted on the final flush.
        """
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_anonymize.side_effect = _redact_card_token
        mock_backend.client.stream_logs.stream.side_effect = self._growing_stream(
            {
                ("run-script", TaskLogType.STDOUT): [
                    "",
                    "tail1\n",
                    "tail1\ncard=4111111111111111",
                ],
                ("run-script", TaskLogType.STDERR): ["", "eout\n"],
            }
        )
        history = created_task_with_history
        history.anonymize_mask = PIIEntity.CREDIT_CARD.value
        history.status = TaskHistoryStatusEnum.SUCCESS
        executor = _build_executor(
            terminal_log_drain_max_attempts=self.SHORT_DRAIN_MAX_ATTEMPTS
        )

        await executor._persist_nomad_task_logs(
            writer_session=session,
            queue_item=history,
            alloc=self._terminal_alloc("run-script"),
            previous_allocation_id="alloc-1",
        )

        stdout = await self._stream_content(
            session, history.id, "run-script", TaskLogType.STDOUT
        )
        assert stdout == "tail1\ncard=[REDACTED]"
        assert "4111" not in stdout
        assert mock_sleep.await_count == self.SHORT_DRAIN_MAX_ATTEMPTS

    @pytest.mark.asyncio
    @patch(
        "app.tasks.execution.executors.nomad.models.asyncio.sleep",
        new_callable=AsyncMock,
    )
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_fully_flushed_task_polls_full_window(
        self, mock_nomad_cls, mock_sleep, session, created_task_with_history
    ):
        """Assert a task whose tail was already captured polls the full window."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.client.stream_logs.stream.side_effect = self._growing_stream(
            {("run-script", TaskLogType.STDOUT): ["complete\n"]}
        )
        history = created_task_with_history
        history.anonymize_mask = 0
        history.status = TaskHistoryStatusEnum.SUCCESS
        executor = _build_executor(
            terminal_log_drain_max_attempts=self.DRAIN_MAX_ATTEMPTS
        )

        await executor._persist_nomad_task_logs(
            writer_session=session,
            queue_item=history,
            alloc=self._terminal_alloc("run-script"),
            previous_allocation_id="alloc-1",
        )

        content = await self._stream_content(
            session, history.id, "run-script", TaskLogType.STDOUT
        )
        assert content == "complete\n"
        assert mock_sleep.await_count == self.DRAIN_MAX_ATTEMPTS

    @pytest.mark.asyncio
    @patch(
        "app.tasks.execution.executors.nomad.models.asyncio.sleep",
        new_callable=AsyncMock,
    )
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_never_empty_stream_bounded_by_max_attempts(
        self, mock_nomad_cls, mock_sleep, session, created_task_with_history
    ):
        """Assert a pathological never-quiet stream still terminates at the cap."""
        calls = defaultdict(int)

        def ever_growing(alloc_id, *, task, type_, offset):
            length = calls[(task, type_)] + 1
            calls[(task, type_)] += 1
            content = "x" * length
            delta = content[offset:]
            if not delta:
                return ""
            return json.dumps(
                {"Data": b64encode(delta.encode()).decode(), "Offset": len(content)}
            )

        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.client.stream_logs.stream.side_effect = ever_growing
        history = created_task_with_history
        history.anonymize_mask = 0
        history.status = TaskHistoryStatusEnum.SUCCESS
        executor = _build_executor(
            terminal_log_drain_max_attempts=self.SHORT_DRAIN_MAX_ATTEMPTS
        )

        await executor._persist_nomad_task_logs(
            writer_session=session,
            queue_item=history,
            alloc=self._terminal_alloc("run-script"),
            previous_allocation_id="alloc-1",
        )

        assert mock_sleep.await_count == self.SHORT_DRAIN_MAX_ATTEMPTS

    @pytest.mark.asyncio
    @patch(
        "app.tasks.execution.executors.nomad.models.asyncio.sleep",
        new_callable=AsyncMock,
    )
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_max_attempts_zero_disables_drain(
        self, mock_nomad_cls, mock_sleep, session, created_task_with_history
    ):
        """Assert ``max_attempts=0`` skips the drain entirely — no fetch, no sleep."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.client.stream_logs.stream.side_effect = self._growing_stream(
            {("run-script", TaskLogType.STDOUT): ["partial\n", "partial\ntail\n"]}
        )
        history = created_task_with_history
        history.anonymize_mask = 0
        history.status = TaskHistoryStatusEnum.SUCCESS
        executor = _build_executor(terminal_log_drain_max_attempts=0)

        await executor._persist_nomad_task_logs(
            writer_session=session,
            queue_item=history,
            alloc=self._terminal_alloc("run-script"),
            previous_allocation_id="alloc-1",
        )

        content = await self._stream_content(
            session, history.id, "run-script", TaskLogType.STDOUT
        )
        assert content == "partial\n"
        mock_sleep.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("app.tasks.execution.executors.nomad.models.anonymize_text")
    @patch(
        "app.tasks.execution.executors.nomad.models.asyncio.sleep",
        new_callable=AsyncMock,
    )
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_max_attempts_zero_still_flushes_anonymized_tail(
        self,
        mock_nomad_cls,
        mock_sleep,
        mock_anonymize,
        session,
        created_task_with_history,
    ):
        """Assert AC3's no-loss promise holds even when the drain is disabled.

        ``max_attempts=0`` skips the polling loop entirely, but the terminal
        flush is gated on whether withholding was possible at all, not on the
        drain's polling budget -- so an anonymized step's newline-less tail
        must still be persisted rather than dropped.
        """
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_anonymize.side_effect = _redact_card_token
        mock_backend.client.stream_logs.stream.side_effect = self._growing_stream(
            {("run-script", TaskLogType.STDOUT): ["card=4111111111111111"]}
        )
        history = created_task_with_history
        history.anonymize_mask = PIIEntity.CREDIT_CARD.value
        history.status = TaskHistoryStatusEnum.SUCCESS
        executor = _build_executor(terminal_log_drain_max_attempts=0)

        await executor._persist_nomad_task_logs(
            writer_session=session,
            queue_item=history,
            alloc=self._terminal_alloc("run-script"),
            previous_allocation_id="alloc-1",
        )

        content = await self._stream_content(
            session, history.id, "run-script", TaskLogType.STDOUT
        )
        assert content == "card=[REDACTED]"
        assert "4111" not in content
        mock_sleep.assert_not_awaited()

    @pytest.mark.asyncio
    @patch(
        "app.tasks.execution.executors.nomad.models.asyncio.sleep",
        new_callable=AsyncMock,
    )
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_drain_resume_is_idempotent_across_terminal_reruns(
        self, mock_nomad_cls, mock_sleep, session, created_task_with_history
    ):
        """Assert re-running the terminal persist re-reads without duplicating bytes."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.client.stream_logs.stream.side_effect = self._growing_stream(
            {("run-script", TaskLogType.STDOUT): ["partial\n", "partial\ntail\n"]}
        )
        history = created_task_with_history
        history.anonymize_mask = 0
        history.status = TaskHistoryStatusEnum.SUCCESS
        executor = _build_executor(
            terminal_log_drain_max_attempts=self.DRAIN_MAX_ATTEMPTS
        )
        alloc = self._terminal_alloc("run-script")

        for _ in range(2):
            await executor._persist_nomad_task_logs(
                writer_session=session,
                queue_item=history,
                alloc=alloc,
                previous_allocation_id="alloc-1",
            )

        content = await self._stream_content(
            session, history.id, "run-script", TaskLogType.STDOUT
        )
        assert content == "partial\ntail\n"

    @pytest.mark.asyncio
    @patch(
        "app.tasks.execution.executors.nomad.models.asyncio.sleep",
        new_callable=AsyncMock,
    )
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_running_status_does_not_drain(
        self, mock_nomad_cls, mock_sleep, session, created_task_with_history
    ):
        """Assert a still-running sync (``force_flush=False``) never drains."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.client.stream_logs.stream.side_effect = self._growing_stream(
            {("run-script", TaskLogType.STDOUT): ["partial\n", "partial\ntail\n"]}
        )
        history = created_task_with_history
        history.anonymize_mask = 0
        history.status = TaskHistoryStatusEnum.RUNNING
        executor = _build_executor(
            terminal_log_drain_max_attempts=self.DRAIN_MAX_ATTEMPTS
        )

        await executor._persist_nomad_task_logs(
            writer_session=session,
            queue_item=history,
            alloc=self._terminal_alloc("run-script"),
            previous_allocation_id="alloc-1",
        )

        mock_sleep.assert_not_awaited()

    @pytest.mark.asyncio
    @patch(
        "app.tasks.execution.executors.nomad.models.asyncio.sleep",
        new_callable=AsyncMock,
    )
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_allocation_gone_during_drain_degrades_gracefully(
        self, mock_nomad_cls, mock_sleep, session, created_task_with_history
    ):
        """Assert a GC'd allocation mid-drain degrades to empty without crashing."""
        calls = defaultdict(int)

        def gone_after_terminal(alloc_id, *, task, type_, offset):
            index = calls[(task, type_)]
            calls[(task, type_)] += 1
            if index == 0:
                return json.dumps(
                    {
                        "Data": b64encode(b"partial\n").decode(),
                        "Offset": len("partial\n"),
                    }
                )
            raise BaseNomadException(MagicMock())

        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.client.stream_logs.stream.side_effect = gone_after_terminal
        history = created_task_with_history
        history.anonymize_mask = 0
        history.status = TaskHistoryStatusEnum.SUCCESS
        executor = _build_executor(
            terminal_log_drain_max_attempts=self.DRAIN_MAX_ATTEMPTS
        )

        await executor._persist_nomad_task_logs(
            writer_session=session,
            queue_item=history,
            alloc=self._terminal_alloc("run-script"),
            previous_allocation_id="alloc-1",
        )

        content = await self._stream_content(
            session, history.id, "run-script", TaskLogType.STDOUT
        )
        assert content == "partial\n"

    @pytest.mark.asyncio
    @patch(
        "app.tasks.execution.executors.nomad.models.asyncio.sleep",
        new_callable=AsyncMock,
    )
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_lagging_stdout_with_settled_stderr(
        self, mock_nomad_cls, mock_sleep, session, created_task_with_history
    ):
        """Assert the drain captures a lagging stdout tail while stderr is settled."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.client.stream_logs.stream.side_effect = self._growing_stream(
            {
                ("run-script", TaskLogType.STDERR): ["boot ok\n"],
                ("run-script", TaskLogType.STDOUT): ["head\n", "head\ntail\n"],
            }
        )
        history = created_task_with_history
        history.anonymize_mask = 0
        history.status = TaskHistoryStatusEnum.SUCCESS
        executor = _build_executor(
            terminal_log_drain_max_attempts=self.DRAIN_MAX_ATTEMPTS
        )

        await executor._persist_nomad_task_logs(
            writer_session=session,
            queue_item=history,
            alloc=self._terminal_alloc("run-script"),
            previous_allocation_id="alloc-1",
        )

        stdout = await self._stream_content(
            session, history.id, "run-script", TaskLogType.STDOUT
        )
        stderr = await self._stream_content(
            session, history.id, "run-script", TaskLogType.STDERR
        )
        assert stdout == "head\ntail\n"
        assert stderr == "boot ok\n"

    @pytest.mark.asyncio
    @patch(
        "app.tasks.execution.executors.nomad.models.asyncio.sleep",
        new_callable=AsyncMock,
    )
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_terminal_failed_status_drains_lagging_tail(
        self, mock_nomad_cls, mock_sleep, session, created_task_with_history
    ):
        """Assert a non-``SUCCESS`` terminal status (FAILED) still drains the tail."""
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.client.stream_logs.stream.side_effect = self._growing_stream(
            {("run-script", TaskLogType.STDOUT): ["partial\n", "partial\ntail\n"]}
        )
        history = created_task_with_history
        history.anonymize_mask = 0
        history.status = TaskHistoryStatusEnum.FAILED
        executor = _build_executor(
            terminal_log_drain_max_attempts=self.DRAIN_MAX_ATTEMPTS
        )

        await executor._persist_nomad_task_logs(
            writer_session=session,
            queue_item=history,
            alloc=self._terminal_alloc("run-script"),
            previous_allocation_id="alloc-1",
        )

        content = await self._stream_content(
            session, history.id, "run-script", TaskLogType.STDOUT
        )
        assert content == "partial\ntail\n"

    @pytest.mark.asyncio
    @patch(
        "app.tasks.execution.executors.nomad.models.asyncio.sleep",
        new_callable=AsyncMock,
    )
    @patch("app.tasks.execution.executors.nomad.models.Nomad")
    async def test_lagging_second_stream_not_dropped_after_sibling_drains(
        self, mock_nomad_cls, mock_sleep, session, created_task_with_history
    ):
        """Assert a stream whose tail lands after a sibling drained is not dropped.

        stdout's tail lands and goes quiet, then a fully-quiet round passes
        before stderr's own tail flushes. A task-wide early-exit gate would
        return on that quiet round and lose the stderr tail; per-stream tracking
        keeps polling because stderr has not advanced yet.
        """
        mock_backend = MagicMock()
        mock_nomad_cls.return_value = mock_backend
        mock_backend.client.stream_logs.stream.side_effect = self._growing_stream(
            {
                ("run-script", TaskLogType.STDOUT): ["head\n", "head\ntail\n"],
                ("run-script", TaskLogType.STDERR): [
                    "boot\n",
                    "boot\n",
                    "boot\nlate\n",
                ],
            }
        )
        history = created_task_with_history
        history.anonymize_mask = 0
        history.status = TaskHistoryStatusEnum.SUCCESS
        executor = _build_executor(
            terminal_log_drain_max_attempts=self.DRAIN_MAX_ATTEMPTS
        )

        await executor._persist_nomad_task_logs(
            writer_session=session,
            queue_item=history,
            alloc=self._terminal_alloc("run-script"),
            previous_allocation_id="alloc-1",
        )

        stdout = await self._stream_content(
            session, history.id, "run-script", TaskLogType.STDOUT
        )
        stderr = await self._stream_content(
            session, history.id, "run-script", TaskLogType.STDERR
        )
        assert stdout == "head\ntail\n"
        assert stderr == "boot\nlate\n"
