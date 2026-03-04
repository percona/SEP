"""Define test cases for the tasks data models and validation."""

import base64
import gzip
import json
from collections import defaultdict
from datetime import datetime, UTC
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.core.alerts.config import alert_service
from app.core.alerts.models import AlertSeverity
from app.tasks.anonymizer.entities import PIIEntity
from app.tasks.models import (
    _encode_anonymize_mask,
    DispatchLock,
    FileMetadata,
    Task,
    TaskBackendEnum,
    TaskBase,
    TaskExecuteRequest,
    TaskExecutionRequest,
    TaskHistory,
    TaskHistoryBase,
    TaskHistoryResponse,
    TaskHistoryStatusEnum,
    TaskLogType,
    TaskOwner,
    TaskResponse,
    TaskStats,
    TransformPayloadRequest,
)
from tests.app.factories import TaskFactory

ENCODE_MASK_INT_INPUT = 42
FILE_METADATA_TEST_SIZE = 100
DURATION_SECONDS = 90.0
STATS_EXPECTED_TOTAL = 2
STATS_AVERAGE_SECONDS = 15.0
STATS_LAST_SECONDS = 20.0
STATS_TOTAL_SECONDS = 10.0
CHUNK_SIZE = 3
EXPECTED_CHUNKS = 4
LAST_CHUNK_OFFSET = 12


class TestTaskBackendEnum:
    """Test TaskBackendEnum values."""

    def test_nomad_value(self) -> None:
        """Assert NOMAD has the expected auto-generated value."""
        assert TaskBackendEnum.NOMAD == "nomad"

    def test_proxy_value(self) -> None:
        """Assert PROXY has the expected auto-generated value."""
        assert TaskBackendEnum.PROXY == "proxy"

    def test_is_str_enum(self) -> None:
        """Assert values are strings."""
        assert isinstance(TaskBackendEnum.NOMAD, str)


class TestTaskHistoryStatusEnum:
    """Test TaskHistoryStatusEnum values and is_finished method."""

    def test_all_values_exist(self) -> None:
        """Assert all six status values exist."""
        expected = {"FAILED", "PENDING", "RUNNING", "SUCCESS", "STOPPED", "LOST"}
        assert {s.name for s in TaskHistoryStatusEnum} == expected

    @pytest.mark.parametrize(
        "status",
        [
            TaskHistoryStatusEnum.FAILED,
            TaskHistoryStatusEnum.SUCCESS,
            TaskHistoryStatusEnum.STOPPED,
        ],
    )
    def test_is_finished_true(self, status: TaskHistoryStatusEnum) -> None:
        """Assert is_finished returns True for terminal statuses."""
        assert status.is_finished() is True

    @pytest.mark.parametrize(
        "status",
        [
            TaskHistoryStatusEnum.PENDING,
            TaskHistoryStatusEnum.RUNNING,
            TaskHistoryStatusEnum.LOST,
        ],
    )
    def test_is_finished_false(self, status: TaskHistoryStatusEnum) -> None:
        """Assert is_finished returns False for non-terminal statuses."""
        assert status.is_finished() is False


class TestTaskOwner:
    """Test TaskOwner enum values."""

    def test_all_values_exist(self) -> None:
        """Assert all nine owner values exist."""
        expected = {
            "ANY",
            "ALTERS",
            "ARCHIVER",
            "BACKUPS",
            "RESTORES",
            "CHECKSUMS",
            "BACKUP_MONGO",
            "RESTORE_MONGO",
            "BACKUP_PG",
        }
        assert {o.name for o in TaskOwner} == expected


class TestTaskLogType:
    """Test TaskLogType enum values."""

    def test_stdout_value(self) -> None:
        """Assert STDOUT has value 'stdout'."""
        assert TaskLogType.STDOUT == "stdout"

    def test_stderr_value(self) -> None:
        """Assert STDERR has value 'stderr'."""
        assert TaskLogType.STDERR == "stderr"


class TestEncodeAnonymizeMask:
    """Test the _encode_anonymize_mask function."""

    def test_encode_set_of_pii_entities(self) -> None:
        """Assert encoding a set of PIIEntity produces correct bitmask."""
        entities = {PIIEntity.CREDIT_CARD, PIIEntity.EMAIL_ADDRESS}
        result = _encode_anonymize_mask(entities)
        assert result == PIIEntity.CREDIT_CARD | PIIEntity.EMAIL_ADDRESS

    def test_pass_through_int(self) -> None:
        """Assert an integer value passes through unchanged."""
        assert _encode_anonymize_mask(ENCODE_MASK_INT_INPUT) == ENCODE_MASK_INT_INPUT

    def test_type_error_returns_as_is(self) -> None:
        """Assert non-encodable input is returned as-is on TypeError."""
        result = _encode_anonymize_mask("not_encodable")
        assert result == "not_encodable"


class TestFileMetadata:
    """Test FileMetadata model."""

    def test_default_construction(self) -> None:
        """Assert default values are size=0 and is_dir=False."""
        meta = FileMetadata()
        assert meta.size == 0
        assert meta.is_dir is False

    def test_extra_fields_ignored(self) -> None:
        """Assert extra fields are silently ignored."""
        meta = FileMetadata(
            size=FILE_METADATA_TEST_SIZE, is_dir=True, unknown_field="ignored"
        )
        assert meta.size == FILE_METADATA_TEST_SIZE
        assert meta.is_dir is True
        assert not hasattr(meta, "unknown_field")


class TestTaskBaseValidation:
    """Test TaskBase.validate_data_for_backend validator."""

    def test_proxy_backend_without_task_raises(self) -> None:
        """Assert ValidationError when PROXY backend has no 'task' in data."""
        with pytest.raises(ValidationError, match="data must contain 'task'"):
            TaskBase(
                name="test",
                data={"something": "else"},
                backend=TaskBackendEnum.PROXY,
            )

    def test_proxy_backend_with_task_passes(self) -> None:
        """Assert PROXY backend with 'task' in data is valid."""
        task = TaskBase(
            name="test",
            data={"task": "inner-task"},
            backend=TaskBackendEnum.PROXY,
        )
        assert task.backend == TaskBackendEnum.PROXY

    def test_nomad_backend_without_task_passes(self) -> None:
        """Assert NOMAD backend does not require 'task' in data."""
        task = TaskBase(
            name="test",
            data={"something": "else"},
            backend=TaskBackendEnum.NOMAD,
        )
        assert task.backend == TaskBackendEnum.NOMAD


class TestTask:
    """Test Task model construction and properties."""

    def test_construction_with_required_fields(self) -> None:
        """Assert Task can be constructed with required fields."""
        task = TaskFactory.build(
            name="my-task",
            data={"key": "value"},
        )
        assert task.name == "my-task"
        assert task.data == {"key": "value"}

    def test_anonymized_entities_with_explicit_mask(self) -> None:
        """Assert anonymized_entities decodes an explicit bitmask."""
        mask = PIIEntity.CREDIT_CARD | PIIEntity.IP_ADDRESS
        task = TaskFactory.build(anonymize_mask=mask)
        assert task.anonymized_entities == {PIIEntity.CREDIT_CARD, PIIEntity.IP_ADDRESS}

    def test_anonymized_entities_with_none_mask(self) -> None:
        """Assert anonymized_entities falls back to anonymizer_settings defaults."""
        default_entities = {PIIEntity.EMAIL_ADDRESS, PIIEntity.PHONE_NUMBER}
        mock_defaults = defaultdict(lambda: default_entities)
        task = TaskFactory.build(anonymize_mask=None, owner=TaskOwner.BACKUPS)
        with patch("app.tasks.models.anonymizer_settings") as mock_settings:
            mock_settings.DEFAULT_ENTITIES = mock_defaults
            result = task.anonymized_entities
        assert result == default_entities


class TestTaskExecutionRequest:
    """Test TaskExecutionRequest model."""

    def test_default_values(self) -> None:
        """Assert default values for meta and tracking fields."""
        req = TaskExecutionRequest(task="backup", target="node-1")
        assert req.meta == {}
        assert req.tracking == {"allocation_id": None, "evaluation_id": None}

    def test_payload_content_plain_string(self) -> None:
        """Assert payload_content returns payload string when not a file path."""
        req = TaskExecutionRequest(task="t", target="n", payload="some content")
        assert req.payload_content == "some content"

    def test_payload_content_file_path_existing(self, tmp_path) -> None:
        """Assert payload_content reads file content for file:// paths."""
        payload_file = tmp_path / "payload.json"
        payload_file.write_text('{"key": "value"}')
        req = TaskExecutionRequest(
            task="t", target="n", payload=f"file://{payload_file}"
        )
        assert req.payload_content == '{"key": "value"}'

    def test_payload_content_file_path_nonexistent(self) -> None:
        """Assert payload_content returns payload string for non-existent file."""
        req = TaskExecutionRequest(
            task="t", target="n", payload="file:///nonexistent/path.json"
        )
        assert req.payload_content == "file:///nonexistent/path.json"

    def test_payload_content_none(self) -> None:
        """Assert payload_content returns None when payload is None."""
        req = TaskExecutionRequest(task="t", target="n")
        assert req.payload_content is None


class TestTaskExecuteRequest:
    """Test TaskExecuteRequest model and validators."""

    def test_default_values(self) -> None:
        """Assert default values for meta, payload, and eta."""
        req = TaskExecuteRequest()
        assert req.meta == {}
        assert req.payload is None
        assert req.eta is None

    def test_populate_meta_extracts_meta_prefixed_keys(self) -> None:
        """Assert keys with 'meta_' prefix are extracted into meta dict."""
        req = TaskExecuteRequest.model_validate({"meta_foo": "bar", "meta_baz": "qux"})
        assert req.meta == {"foo": "bar", "baz": "qux"}

    def test_populate_meta_merges_with_existing(self) -> None:
        """Assert meta_ keys merge with explicitly provided meta."""
        req = TaskExecuteRequest.model_validate(
            {"meta": {"existing": "val"}, "meta_new": "val2"}
        )
        assert req.meta == {"existing": "val", "new": "val2"}

    def test_empty_str_to_none_for_eta(self) -> None:
        """Assert empty string for eta is converted to None."""
        req = TaskExecuteRequest.model_validate({"eta": ""})
        assert req.eta is None


class TestTaskHistoryBase:
    """Test TaskHistoryBase computed fields."""

    def test_duration_with_both_timestamps(self) -> None:
        """Assert duration returns seconds when both timestamps are set."""
        started = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        finished = datetime(2026, 1, 1, 12, 1, 30, tzinfo=UTC)
        req = TaskExecutionRequest(task="t", target="n")
        history = TaskHistoryBase(
            execution_request=req,
            started_at=started,
            finished_at=finished,
        )
        assert history.duration == DURATION_SECONDS

    def test_duration_missing_started_at(self) -> None:
        """Assert duration returns None when started_at is missing."""
        req = TaskExecutionRequest(task="t", target="n")
        history = TaskHistoryBase(
            execution_request=req,
            finished_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert history.duration is None

    def test_duration_missing_finished_at(self) -> None:
        """Assert duration returns None when finished_at is missing."""
        req = TaskExecutionRequest(task="t", target="n")
        history = TaskHistoryBase(
            execution_request=req,
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert history.duration is None


class TestTaskHistory:
    """Test TaskHistory model properties and methods."""

    @pytest.fixture
    def task_instance(self) -> Task:
        """Return a Task instance for TaskHistory construction."""
        return TaskFactory.build(id=1, name="test-task", data={"key": "val"})

    @pytest.fixture
    def execution_request(self) -> TaskExecutionRequest:
        """Return a TaskExecutionRequest for TaskHistory construction."""
        return TaskExecutionRequest(
            task="test-task",
            target="node-1",
            tracking={"allocation_id": None, "evaluation_id": None},
        )

    def test_is_running_true(
        self, task_instance: Task, execution_request: TaskExecutionRequest
    ) -> None:
        """Assert is_running returns True when status is RUNNING."""
        history = TaskHistory(
            id=1,
            task_id=task_instance.id,
            task=task_instance,
            execution_request=execution_request,
            status=TaskHistoryStatusEnum.RUNNING,
        )
        assert history.is_running is True

    def test_is_running_false(
        self, task_instance: Task, execution_request: TaskExecutionRequest
    ) -> None:
        """Assert is_running returns False for non-RUNNING statuses."""
        history = TaskHistory(
            id=1,
            task_id=task_instance.id,
            task=task_instance,
            execution_request=execution_request,
            status=TaskHistoryStatusEnum.SUCCESS,
        )
        assert history.is_running is False

    def test_anonymized_entities(
        self, task_instance: Task, execution_request: TaskExecutionRequest
    ) -> None:
        """Assert anonymized_entities decodes the bitmask correctly."""
        mask = PIIEntity.CREDIT_CARD | PIIEntity.PERSON
        history = TaskHistory(
            id=1,
            task_id=task_instance.id,
            task=task_instance,
            execution_request=execution_request,
            anonymize_mask=mask,
        )
        assert history.anonymized_entities == {PIIEntity.CREDIT_CARD, PIIEntity.PERSON}

    def test_task_logs_dict(
        self, task_instance: Task, execution_request: TaskExecutionRequest
    ) -> None:
        """Assert task_logs returns dict logs as-is."""
        logs_data = {"step1": {"stdout": "output", "stderr": ""}}
        execution_request.tracking["task_logs"] = logs_data
        history = TaskHistory(
            id=1,
            task_id=task_instance.id,
            task=task_instance,
            execution_request=execution_request,
        )
        assert history.task_logs == logs_data

    def test_task_logs_compressed(
        self, task_instance: Task, execution_request: TaskExecutionRequest
    ) -> None:
        """Assert task_logs decompresses gzip+base64 string logs."""
        logs_data = {"step1": {"stdout": "compressed output"}}
        compressed = base64.b64encode(
            gzip.compress(json.dumps(logs_data).encode())
        ).decode()
        execution_request.tracking["task_logs"] = compressed
        history = TaskHistory(
            id=1,
            task_id=task_instance.id,
            task=task_instance,
            execution_request=execution_request,
        )
        assert history.task_logs == logs_data

    def test_iter_logs_yields_chunks(
        self, task_instance: Task, execution_request: TaskExecutionRequest
    ) -> None:
        """Assert iter_logs yields TaskLog chunks from task_logs data."""
        logs_data = {"step1": {"stdout": "hello", "stderr": "err"}}
        execution_request.tracking["task_logs"] = logs_data
        history = TaskHistory(
            id=1,
            task_id=task_instance.id,
            task=task_instance,
            execution_request=execution_request,
        )
        logs = list(history.iter_logs())
        stdout_logs = [lg for lg in logs if lg.type == TaskLogType.STDOUT]
        stderr_logs = [lg for lg in logs if lg.type == TaskLogType.STDERR]
        assert len(stdout_logs) == 1
        assert stdout_logs[0].msg == "hello"
        assert stdout_logs[0].step == "step1"
        assert len(stderr_logs) == 1
        assert stderr_logs[0].msg == "err"

    def test_iter_logs_respects_start_offsets(
        self, task_instance: Task, execution_request: TaskExecutionRequest
    ) -> None:
        """Assert iter_logs respects start_offsets to skip content."""
        logs_data = {"step1": {"stdout": "0123456789"}}
        execution_request.tracking["task_logs"] = logs_data
        history = TaskHistory(
            id=1,
            task_id=task_instance.id,
            task=task_instance,
            execution_request=execution_request,
        )
        logs = list(history.iter_logs(start_offsets={"step1": {"stdout": 5}}))
        stdout_logs = [lg for lg in logs if lg.type == TaskLogType.STDOUT]
        assert stdout_logs[0].msg == "56789"

    def test_iter_logs_respects_step_filter(
        self, task_instance: Task, execution_request: TaskExecutionRequest
    ) -> None:
        """Assert iter_logs only yields logs for the specified step."""
        logs_data = {
            "step1": {"stdout": "s1 out"},
            "step2": {"stdout": "s2 out"},
        }
        execution_request.tracking["task_logs"] = logs_data
        history = TaskHistory(
            id=1,
            task_id=task_instance.id,
            task=task_instance,
            execution_request=execution_request,
        )
        logs = list(history.iter_logs(step="step1"))
        steps = {lg.step for lg in logs}
        assert steps == {"step1"}

    def test_iter_logs_chunk_size_splitting(
        self, task_instance: Task, execution_request: TaskExecutionRequest
    ) -> None:
        """Assert iter_logs splits messages into chunks of given size."""
        logs_data = {"step1": {"stdout": "A" * 10}}
        execution_request.tracking["task_logs"] = logs_data
        history = TaskHistory(
            id=1,
            task_id=task_instance.id,
            task=task_instance,
            execution_request=execution_request,
        )
        logs = list(history.iter_logs(chunk_size=CHUNK_SIZE))
        stdout_logs = [lg for lg in logs if lg.type == TaskLogType.STDOUT]
        assert len(stdout_logs) == EXPECTED_CHUNKS
        assert stdout_logs[0].msg == "AAA"
        assert stdout_logs[0].offset == CHUNK_SIZE
        assert stdout_logs[3].msg == "A"
        assert stdout_logs[3].offset == LAST_CHUNK_OFFSET

    @pytest.mark.asyncio
    async def test_alert_for_status_failed(
        self, task_instance: Task, execution_request: TaskExecutionRequest
    ) -> None:
        """Assert alert_for_status triggers ERROR alert for FAILED status."""
        history = TaskHistory(
            id=1,
            task_id=task_instance.id,
            task=task_instance,
            execution_request=execution_request,
            status=TaskHistoryStatusEnum.FAILED,
        )
        mock_trigger = AsyncMock()
        with patch.object(type(alert_service), "trigger", mock_trigger):
            await history.alert_for_status()
            mock_trigger.assert_called_once()
            alert_data = mock_trigger.call_args[0][0]
            assert alert_data["severity"] == AlertSeverity.ERROR
            assert alert_data["class"] == "task_failure"
            assert "failed" in alert_data["summary"]

    @pytest.mark.asyncio
    async def test_alert_for_status_lost(
        self, task_instance: Task, execution_request: TaskExecutionRequest
    ) -> None:
        """Assert alert_for_status triggers WARNING alert for LOST status."""
        history = TaskHistory(
            id=1,
            task_id=task_instance.id,
            task=task_instance,
            execution_request=execution_request,
            status=TaskHistoryStatusEnum.LOST,
        )
        mock_trigger = AsyncMock()
        with patch.object(type(alert_service), "trigger", mock_trigger):
            await history.alert_for_status()
            mock_trigger.assert_called_once()
            alert_data = mock_trigger.call_args[0][0]
            assert alert_data["severity"] == AlertSeverity.WARNING
            assert alert_data["class"] == "task_lost"

    @pytest.mark.asyncio
    async def test_alert_for_status_success_no_alert(
        self, task_instance: Task, execution_request: TaskExecutionRequest
    ) -> None:
        """Assert alert_for_status returns early for SUCCESS status."""
        history = TaskHistory(
            id=1,
            task_id=task_instance.id,
            task=task_instance,
            execution_request=execution_request,
            status=TaskHistoryStatusEnum.SUCCESS,
        )
        mock_trigger = AsyncMock()
        with patch.object(type(alert_service), "trigger", mock_trigger):
            await history.alert_for_status()
            mock_trigger.assert_not_called()


class TestTaskHistoryResponse:
    """Test TaskHistoryResponse._remove_logs validator."""

    def test_remove_logs_replaces_with_boolean(self) -> None:
        """Assert _remove_logs replaces task_logs in tracking with a boolean."""
        task_resp = TaskResponse(
            id=1,
            name="t",
            data={"key": "val"},
            backend=TaskBackendEnum.NOMAD,
            deleted_at=None,
            created_by=None,
            last_updated_by=None,
        )
        req = TaskExecutionRequest(
            task="t",
            target="n",
            tracking={"allocation_id": None, "task_logs": {"step1": {"stdout": "x"}}},
        )
        resp = TaskHistoryResponse(
            id=1,
            execution_request=req,
            task=task_resp,
        )
        assert resp.execution_request.tracking["task_logs"] is True

    def test_remove_logs_empty_logs(self) -> None:
        """Assert _remove_logs sets False when task_logs is empty or missing."""
        task_resp = TaskResponse(
            id=1,
            name="t",
            data={"key": "val"},
            backend=TaskBackendEnum.NOMAD,
            deleted_at=None,
            created_by=None,
            last_updated_by=None,
        )
        req = TaskExecutionRequest(
            task="t",
            target="n",
            tracking={"allocation_id": None},
        )
        resp = TaskHistoryResponse(
            id=1,
            execution_request=req,
            task=task_resp,
        )
        assert resp.execution_request.tracking["task_logs"] is False


class TestTaskStats:
    """Test TaskStats computed fields."""

    @pytest.fixture
    def task_instance(self) -> Task:
        """Return a Task instance for TaskStats construction."""
        return TaskFactory.build(id=1, name="stats-task", data={"key": "val"})

    def _make_history(
        self,
        task: Task,
        status: TaskHistoryStatusEnum,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        history_id: int = 1,
    ) -> TaskHistory:
        """Return a TaskHistory instance with given parameters.

        :param task: The parent task.
        :type task: Task
        :param status: The execution status.
        :type status: TaskHistoryStatusEnum
        :param started_at: Start timestamp.
        :type started_at: datetime | None
        :param finished_at: Finish timestamp.
        :type finished_at: datetime | None
        :param history_id: The history record ID.
        :type history_id: int
        :return: A configured TaskHistory.
        :rtype: TaskHistory
        """
        return TaskHistory(
            id=history_id,
            task_id=task.id,
            task=task,
            execution_request=TaskExecutionRequest(task=task.name, target="n"),
            status=status,
            started_at=started_at,
            finished_at=finished_at,
        )

    def test_total_count(self, task_instance: Task) -> None:
        """Assert total returns the count of the tasks list."""
        h1 = self._make_history(
            task_instance, TaskHistoryStatusEnum.SUCCESS, history_id=1
        )
        h2 = self._make_history(
            task_instance, TaskHistoryStatusEnum.FAILED, history_id=2
        )
        stats = TaskStats(tasks=[h1, h2])
        assert stats.total == STATS_EXPECTED_TOTAL

    def test_status_counts(self, task_instance: Task) -> None:
        """Assert status counts pass/fail correctly."""
        h1 = self._make_history(
            task_instance, TaskHistoryStatusEnum.SUCCESS, history_id=1
        )
        h2 = self._make_history(
            task_instance, TaskHistoryStatusEnum.FAILED, history_id=2
        )
        h3 = self._make_history(
            task_instance, TaskHistoryStatusEnum.RUNNING, history_id=3
        )
        stats = TaskStats(tasks=[h1, h2, h3])
        assert stats.status == {"pass": 1, "fail": 1}

    def test_duration_values(self, task_instance: Task) -> None:
        """Assert duration computes average, last, and total seconds."""
        t1_start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        t1_end = datetime(2026, 1, 1, 12, 0, 10, tzinfo=UTC)
        t2_start = datetime(2026, 1, 1, 13, 0, 0, tzinfo=UTC)
        t2_end = datetime(2026, 1, 1, 13, 0, 20, tzinfo=UTC)
        h1 = self._make_history(
            task_instance,
            TaskHistoryStatusEnum.SUCCESS,
            started_at=t1_start,
            finished_at=t1_end,
            history_id=1,
        )
        h2 = self._make_history(
            task_instance,
            TaskHistoryStatusEnum.SUCCESS,
            started_at=t2_start,
            finished_at=t2_end,
            history_id=2,
        )
        stats = TaskStats(tasks=[h1, h2])
        duration = stats.duration
        assert duration["average_seconds"] == STATS_AVERAGE_SECONDS
        assert duration["last_seconds"] == STATS_LAST_SECONDS
        assert duration["total_seconds"] == STATS_TOTAL_SECONDS

    def test_last_finished_at(self, task_instance: Task) -> None:
        """Assert last_finished_at returns the max finished_at timestamp."""
        t1_end = datetime(2026, 1, 1, 12, 0, 10, tzinfo=UTC)
        t2_end = datetime(2026, 1, 1, 13, 0, 20, tzinfo=UTC)
        h1 = self._make_history(
            task_instance,
            TaskHistoryStatusEnum.SUCCESS,
            started_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
            finished_at=t1_end,
            history_id=1,
        )
        h2 = self._make_history(
            task_instance,
            TaskHistoryStatusEnum.SUCCESS,
            started_at=datetime(2026, 1, 1, 13, 0, 0, tzinfo=UTC),
            finished_at=t2_end,
            history_id=2,
        )
        stats = TaskStats(tasks=[h1, h2])
        assert stats.last_finished_at == t2_end

    def test_empty_tasks_defaults(self) -> None:
        """Assert empty tasks list produces zero total and None durations."""
        stats = TaskStats(tasks=[])
        assert stats.total == 0
        assert stats.duration["average_seconds"] is None
        assert stats.duration["last_seconds"] is None
        assert stats.duration["total_seconds"] is None
        assert stats.last_finished_at is None


class TestTransformPayloadRequest:
    """Test TransformPayloadRequest validation."""

    def test_valid_construction(self) -> None:
        """Assert valid payload and fmt are accepted."""
        req = TransformPayloadRequest(payload="content", fmt="json")
        assert req.payload == "content"
        assert req.fmt == "json"

    @pytest.mark.parametrize("fmt", ["hcl", "json", "yaml"])
    def test_valid_formats(self, fmt: str) -> None:
        """Assert all allowed format values are accepted."""
        req = TransformPayloadRequest(payload="data", fmt=fmt)
        assert req.fmt == fmt

    def test_invalid_format_raises(self) -> None:
        """Assert invalid fmt raises ValidationError."""
        with pytest.raises(ValidationError):
            TransformPayloadRequest(payload="data", fmt="xml")


class TestDispatchLock:
    """Test DispatchLock model construction."""

    def test_construction(self) -> None:
        """Assert DispatchLock can be constructed with a name."""
        lock = DispatchLock(name="my-lock")
        assert lock.name == "my-lock"
