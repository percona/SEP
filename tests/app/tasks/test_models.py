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

"""Define test cases for the tasks data models and validation."""

from collections import defaultdict
from datetime import datetime, UTC
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.core.alerts.models import AlertService, AlertSeverity
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
    TaskHistoryStatusEnum,
    TaskLogType,
    TaskOwner,
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


class TestTaskBackendEnum:
    """Test TaskBackendEnum values."""

    def test_nomad_value(self) -> None:
        """Assert NOMAD has the expected auto-generated value."""
        assert TaskBackendEnum.NOMAD == "nomad"

    def test_proxy_value(self) -> None:
        """Assert PROXY has the expected auto-generated value."""
        assert TaskBackendEnum.PROXY == "proxy"

    def test_celery_value(self) -> None:
        """Assert CELERY has the expected auto-generated value."""
        assert TaskBackendEnum.CELERY == "celery"

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

    def test_celery_backend_protected_passes(self) -> None:
        """Assert CELERY backend passes validation when protected."""
        task = TaskBase(
            name="test",
            data={"callable": "some.module.func", "target": "local"},
            backend=TaskBackendEnum.CELERY,
            protected=True,
        )
        assert task.backend == TaskBackendEnum.CELERY

    def test_celery_backend_unprotected_raises(self) -> None:
        """Assert CELERY backend raises when not protected."""
        with pytest.raises(ValidationError, match="protected"):
            TaskBase(
                name="test",
                data={"callable": "some.module.func", "target": "local"},
                backend=TaskBackendEnum.CELERY,
                protected=False,
            )


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

    def test_chain_task_names_valid_json_list(self) -> None:
        """Assert valid JSON list is parsed correctly."""
        req = TaskExecuteRequest(chain_task_names='["a","b"]')
        assert req.chain_task_names == ["a", "b"]

    def test_chain_task_names_invalid_json_falls_back(self) -> None:
        """Assert invalid JSON string is treated as a single task name."""
        req = TaskExecuteRequest(chain_task_names="[broken")
        assert req.chain_task_names == ["[broken"]

    def test_chain_task_names_empty_string_returns_none(self) -> None:
        """Assert empty string normalizes to None."""
        req = TaskExecuteRequest(chain_task_names="")
        assert req.chain_task_names is None

    def test_chain_task_names_empty_list_returns_none(self) -> None:
        """Assert empty list normalizes to None."""
        req = TaskExecuteRequest(chain_task_names=[])
        assert req.chain_task_names is None

    def test_chain_task_names_single_string(self) -> None:
        """Assert single string is wrapped in a list."""
        req = TaskExecuteRequest(chain_task_names="task-a")
        assert req.chain_task_names == ["task-a"]

    def test_chain_task_names_list_with_empties_filtered(self) -> None:
        """Assert empty strings are filtered from a list."""
        req = TaskExecuteRequest(chain_task_names=["a", "", "b"])
        assert req.chain_task_names == ["a", "b"]

    def test_chain_on_failure_defaults_to_false(self) -> None:
        """Assert chain_on_failure defaults to False."""
        req = TaskExecuteRequest()
        assert req.chain_on_failure is False

    @pytest.mark.parametrize("value", ["true", "on", "1", True])
    def test_chain_on_failure_truthy_values(self, value) -> None:
        """Assert truthy form values normalize to True."""
        req = TaskExecuteRequest(chain_on_failure=value)
        assert req.chain_on_failure is True

    @pytest.mark.parametrize("value", ["false", "off", "0", "", False])
    def test_chain_on_failure_falsy_values(self, value) -> None:
        """Assert falsy form values normalize to False."""
        req = TaskExecuteRequest(chain_on_failure=value)
        assert req.chain_on_failure is False


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

    @pytest.mark.asyncio
    async def test_alert_for_status_failed(
        self, task_instance: Task, execution_request: TaskExecutionRequest
    ) -> None:
        """Assert alert_for_status triggers ERROR alert with dedup key for FAILED."""
        history = TaskHistory(
            id=1,
            task_id=task_instance.id,
            task=task_instance,
            execution_request=execution_request,
            status=TaskHistoryStatusEnum.FAILED,
        )
        mock_trigger = AsyncMock()
        with patch.object(AlertService, "trigger", mock_trigger):
            await history.alert_for_status()
            mock_trigger.assert_called_once()
            alert_data = mock_trigger.call_args[0][0]
            assert alert_data["severity"] == AlertSeverity.ERROR
            assert alert_data["class"] == "task_failure"
            assert "failed" in alert_data["summary"]
            assert alert_data["dedup_key"] == "task:test-task:node-1"

    @pytest.mark.asyncio
    async def test_alert_for_status_lost(
        self, task_instance: Task, execution_request: TaskExecutionRequest
    ) -> None:
        """Assert alert_for_status triggers WARNING alert with dedup key for LOST."""
        history = TaskHistory(
            id=1,
            task_id=task_instance.id,
            task=task_instance,
            execution_request=execution_request,
            status=TaskHistoryStatusEnum.LOST,
        )
        mock_trigger = AsyncMock()
        with patch.object(AlertService, "trigger", mock_trigger):
            await history.alert_for_status()
            mock_trigger.assert_called_once()
            alert_data = mock_trigger.call_args[0][0]
            assert alert_data["severity"] == AlertSeverity.WARNING
            assert alert_data["class"] == "task_lost"
            assert alert_data["dedup_key"] == "task:test-task:node-1"

    @pytest.mark.asyncio
    async def test_alert_for_status_success_resolves(
        self, task_instance: Task, execution_request: TaskExecutionRequest
    ) -> None:
        """Assert alert_for_status resolves the alert on SUCCESS status."""
        history = TaskHistory(
            id=1,
            task_id=task_instance.id,
            task=task_instance,
            execution_request=execution_request,
            status=TaskHistoryStatusEnum.SUCCESS,
        )
        mock_trigger = AsyncMock()
        mock_resolve = AsyncMock()
        with (
            patch.object(AlertService, "trigger", mock_trigger),
            patch.object(AlertService, "resolve", mock_resolve),
        ):
            await history.alert_for_status()
            mock_trigger.assert_not_called()
            mock_resolve.assert_called_once_with("task:test-task:node-1")

    @pytest.mark.asyncio
    async def test_alert_for_status_stopped_no_action(
        self, task_instance: Task, execution_request: TaskExecutionRequest
    ) -> None:
        """Assert alert_for_status takes no action for STOPPED status."""
        history = TaskHistory(
            id=1,
            task_id=task_instance.id,
            task=task_instance,
            execution_request=execution_request,
            status=TaskHistoryStatusEnum.STOPPED,
        )
        mock_trigger = AsyncMock()
        mock_resolve = AsyncMock()
        with (
            patch.object(AlertService, "trigger", mock_trigger),
            patch.object(AlertService, "resolve", mock_resolve),
        ):
            await history.alert_for_status()
            mock_trigger.assert_not_called()
            mock_resolve.assert_not_called()

    @pytest.mark.asyncio
    async def test_alert_for_status_dedup_key_consistent(
        self, task_instance: Task, execution_request: TaskExecutionRequest
    ) -> None:
        """Assert dedup key is identical for FAILED and SUCCESS of same task."""
        failed_history = TaskHistory(
            id=1,
            task_id=task_instance.id,
            task=task_instance,
            execution_request=execution_request,
            status=TaskHistoryStatusEnum.FAILED,
        )
        success_history = TaskHistory(
            id=2,
            task_id=task_instance.id,
            task=task_instance,
            execution_request=execution_request,
            status=TaskHistoryStatusEnum.SUCCESS,
        )
        mock_trigger = AsyncMock()
        mock_resolve = AsyncMock()
        with (
            patch.object(AlertService, "trigger", mock_trigger),
            patch.object(AlertService, "resolve", mock_resolve),
        ):
            await failed_history.alert_for_status()
            await success_history.alert_for_status()
            trigger_dedup = mock_trigger.call_args[0][0]["dedup_key"]
            resolve_dedup = mock_resolve.call_args[0][0]
            assert trigger_dedup == resolve_dedup


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
