"""Define tests for the Tasks API dependency injection functions."""

from collections import defaultdict
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from starlette.requests import Request

from app.core.exceptions import HTTPBadRequestException, HTTPNotFoundException
from app.tasks.config import tasks_settings
from app.tasks.crud import TaskManager
from app.tasks.deps import (
    get_active_task_by_name,
    get_executable_task_by_name,
    get_executor,
    get_logs_offsets,
    get_task_history,
    get_task_history_with_task,
    prepare_task_history,
)
from app.tasks.models import (
    Task,
    TaskBackendEnum,
    TaskExecuteRequest,
    TaskHistory,
    TaskHistoryStatusEnum,
    TaskWrite,
)
from tests.app.factories import TaskFactory

TASK_ANONYMIZE_MASK = 42
EXECUTION_ANONYMIZE_MASK = 77
DEFAULT_ANONYMIZE_MASK = 123
OFFSET_100 = 100
OFFSET_200 = 200
OFFSET_50 = 50


def _make_request(query_params: dict[str, str] | None = None) -> Request:
    """Build a minimal Starlette Request with the given query parameters.

    :param query_params: Query parameter key-value pairs.
    :type query_params: dict[str, str] | None
    :return: A Starlette Request instance.
    :rtype: Request
    """
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"&".join(
            f"{k}={v}".encode() for k, v in (query_params or {}).items()
        ),
    }
    return Request(scope)


class TestGetExecutor:
    """Test the get_executor dependency."""

    def test_nomad_backend_returns_executor(self) -> None:
        """Assert NOMAD backend returns the configured NomadExecutor."""
        result = get_executor(TaskBackendEnum.NOMAD)
        assert result is tasks_settings.NOMAD

    def test_non_nomad_backend_raises_value_error(self) -> None:
        """Assert non-NOMAD backend raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported backend"):
            get_executor(TaskBackendEnum.PROXY)


@pytest_asyncio.fixture
async def nomad_task(session) -> Task:
    """Return a persisted active NOMAD task."""
    return await TaskManager.create(
        session,
        TaskWrite.model_validate(
            TaskFactory.build(name="nomad-task", backend=TaskBackendEnum.NOMAD)
        ),
    )


@pytest_asyncio.fixture
async def proxy_task(session) -> Task:
    """Return a persisted active PROXY task."""
    return await TaskManager.create(
        session,
        TaskWrite.model_validate(
            TaskFactory.build(
                name="proxy-task",
                backend=TaskBackendEnum.PROXY,
                data={"task": "nomad-task", "meta": {"env": "prod"}, "payload": "p1"},
            )
        ),
    )


@pytest_asyncio.fixture
async def template_task(session) -> Task:
    """Return a persisted active template task."""
    return await TaskManager.create(
        session,
        TaskWrite.model_validate(
            TaskFactory.build(name="template-task", is_template=True)
        ),
    )


class TestGetActiveTaskByName:
    """Test the get_active_task_by_name dependency."""

    @pytest.mark.asyncio
    async def test_existing_active_task(self, session, nomad_task) -> None:
        """Assert an existing active task is returned."""
        result = await get_active_task_by_name(session, nomad_task.name)
        assert result.id == nomad_task.id
        assert result.name == nomad_task.name

    @pytest.mark.asyncio
    async def test_nonexistent_task_raises_404(self, session) -> None:
        """Assert a nonexistent task raises HTTPNotFoundException."""
        with pytest.raises(HTTPNotFoundException):
            await get_active_task_by_name(session, "no-such-task")

    @pytest.mark.asyncio
    async def test_deleted_task_raises_404(self, session, nomad_task) -> None:
        """Assert a soft-deleted task raises HTTPNotFoundException."""
        await TaskManager.delete_by_name(session, nomad_task.name)
        with pytest.raises(HTTPNotFoundException):
            await get_active_task_by_name(session, nomad_task.name)


class TestGetExecutableTaskByName:
    """Test the get_executable_task_by_name dependency."""

    @pytest.mark.asyncio
    async def test_active_non_template_task(self, session, nomad_task) -> None:
        """Assert an active non-template task is returned."""
        result = await get_executable_task_by_name(session, nomad_task.name)
        assert result.id == nomad_task.id

    @pytest.mark.asyncio
    async def test_template_task_raises_404(self, session, template_task) -> None:
        """Assert a template task raises HTTPNotFoundException."""
        with pytest.raises(HTTPNotFoundException):
            await get_executable_task_by_name(session, template_task.name)

    @pytest.mark.asyncio
    async def test_deleted_task_raises_404(self, session, nomad_task) -> None:
        """Assert a deleted task raises HTTPNotFoundException."""
        await TaskManager.delete_by_name(session, nomad_task.name)
        with pytest.raises(HTTPNotFoundException):
            await get_executable_task_by_name(session, nomad_task.name)


class TestPrepareTaskHistory:
    """Test the prepare_task_history dependency."""

    @pytest.mark.asyncio
    async def test_nomad_backend_with_target_in_meta(self, nomad_task) -> None:
        """Assert NOMAD task with target in meta creates valid TaskHistory."""
        execution_data = TaskExecuteRequest(meta={"target": "node-1"})
        result = await prepare_task_history(
            nomad_task, "user-1", AsyncMock(), execution_data
        )
        assert isinstance(result, TaskHistory)
        assert result.task_id == nomad_task.id
        assert result.execution_request.target == "node-1"
        assert result.executed_by == "user-1"
        assert result.status == TaskHistoryStatusEnum.PENDING

    @pytest.mark.asyncio
    async def test_nomad_backend_does_not_merge_task_data(self, nomad_task) -> None:
        """Assert NOMAD backend does not merge meta/payload from task.data."""
        nomad_task.data = {"meta": {"env": "staging"}, "payload": "override"}
        execution_data = TaskExecuteRequest(meta={"target": "node-1"})
        result = await prepare_task_history(
            nomad_task, "user-1", AsyncMock(), execution_data
        )
        assert "env" not in result.execution_request.meta
        assert result.execution_request.payload is None

    @pytest.mark.asyncio
    async def test_proxy_backend_merges_meta_and_payload(self, proxy_task) -> None:
        """Assert PROXY backend merges meta and payload from task.data."""
        execution_data = TaskExecuteRequest(meta={"target": "node-1"})
        result = await prepare_task_history(
            proxy_task, "user-1", AsyncMock(), execution_data
        )
        assert result.execution_request.meta["env"] == "prod"
        assert result.execution_request.payload == "p1"

    @pytest.mark.asyncio
    async def test_proxy_backend_execution_data_payload_kept_when_no_task_payload(
        self,
    ) -> None:
        """Assert PROXY keeps execution_data payload when task has no payload."""
        task = Task(
            id=99,
            name="proxy-no-payload",
            backend=TaskBackendEnum.PROXY,
            data={"task": "inner", "meta": {"target": "node-1"}},
        )
        execution_data = TaskExecuteRequest(
            meta={"target": "node-1"}, payload="my-payload"
        )
        result = await prepare_task_history(task, "user-1", AsyncMock(), execution_data)
        assert result.execution_request.payload == "my-payload"

    @pytest.mark.asyncio
    async def test_missing_target_raises_bad_request(self) -> None:
        """Assert missing target raises HTTPBadRequestException."""
        task = Task(
            id=1,
            name="no-target-task",
            backend=TaskBackendEnum.NOMAD,
            data={},
        )
        execution_data = TaskExecuteRequest(meta={})
        with pytest.raises(HTTPBadRequestException, match="target is required"):
            await prepare_task_history(task, "user-1", AsyncMock(), execution_data)

    @pytest.mark.asyncio
    async def test_target_from_constraints_rtarget(self) -> None:
        """Assert target is extracted from Constraints[0].RTarget when not in meta."""
        task = Task(
            id=2,
            name="constraints-task",
            backend=TaskBackendEnum.NOMAD,
            data={"Constraints": [{"RTarget": "constraint-node"}]},
        )
        execution_data = TaskExecuteRequest(meta={})
        result = await prepare_task_history(task, "user-1", AsyncMock(), execution_data)
        assert result.execution_request.target == "constraint-node"

    @pytest.mark.asyncio
    async def test_no_execution_data_defaults_to_empty_request(self) -> None:
        """Assert None execution_data defaults to an empty TaskExecuteRequest."""
        task = Task(
            id=3,
            name="default-exec",
            backend=TaskBackendEnum.NOMAD,
            data={"Constraints": [{"RTarget": "node-x"}]},
        )
        result = await prepare_task_history(task, "user-1", AsyncMock(), None)
        assert result.execution_request.target == "node-x"
        assert result.execution_request.payload is None

    @pytest.mark.asyncio
    async def test_anonymize_mask_task_takes_priority(self) -> None:
        """Assert task.anonymize_mask takes priority over execution_data mask."""
        task = Task(
            id=4,
            name="mask-priority-task",
            backend=TaskBackendEnum.NOMAD,
            data={"Constraints": [{"RTarget": "n"}]},
            anonymize_mask=TASK_ANONYMIZE_MASK,
        )
        execution_data = TaskExecuteRequest(meta={"target": "n"}, anonymize_mask=99)
        result = await prepare_task_history(task, "user-1", AsyncMock(), execution_data)
        assert result.anonymize_mask == TASK_ANONYMIZE_MASK

    @pytest.mark.asyncio
    async def test_anonymize_mask_uses_execution_data_when_task_is_none(self) -> None:
        """Assert execution_data mask is used when task mask is None."""
        task = Task(
            id=5,
            name="mask-exec-task",
            backend=TaskBackendEnum.NOMAD,
            data={"Constraints": [{"RTarget": "n"}]},
            anonymize_mask=None,
        )
        execution_data = TaskExecuteRequest(
            meta={"target": "n"}, anonymize_mask=EXECUTION_ANONYMIZE_MASK
        )
        result = await prepare_task_history(task, "user-1", AsyncMock(), execution_data)
        assert result.anonymize_mask == EXECUTION_ANONYMIZE_MASK

    @pytest.mark.asyncio
    @patch("app.tasks.deps.anonymizer_settings")
    async def test_anonymize_mask_falls_back_to_settings(
        self, mock_anonymizer_settings
    ) -> None:
        """Assert anonymizer_settings default is used when both masks are None."""
        mock_anonymizer_settings.get_anonymize_mask.return_value = (
            DEFAULT_ANONYMIZE_MASK
        )
        task = Task(
            id=6,
            name="mask-default-task",
            backend=TaskBackendEnum.NOMAD,
            data={"Constraints": [{"RTarget": "n"}]},
            anonymize_mask=None,
            owner="BACKUPS",
        )
        execution_data = TaskExecuteRequest(meta={"target": "n"}, anonymize_mask=None)
        result = await prepare_task_history(task, "user-1", AsyncMock(), execution_data)
        assert result.anonymize_mask == DEFAULT_ANONYMIZE_MASK
        mock_anonymizer_settings.get_anonymize_mask.assert_called_once_with("BACKUPS")

    @pytest.mark.asyncio
    async def test_chain_task_name_injected_in_meta(self) -> None:
        """Assert prepare_task_history stores chain_task_name in meta when set."""
        task = TaskFactory.build(
            name="test-task",
            backend=TaskBackendEnum.PROXY,
            data={"meta": {"target": "host1"}, "payload": None},
        )
        chain_task = TaskFactory.build(name="other-task")
        execution_data = TaskExecuteRequest(chain_task_name="other-task")
        with patch(
            "app.tasks.deps.TaskManager.first",
            new_callable=AsyncMock,
            return_value=chain_task,
        ):
            history = await prepare_task_history(
                task, "test-user", AsyncMock(), execution_data
            )
        assert history.execution_request.meta.get("chain_task_name") == "other-task"

    @pytest.mark.asyncio
    async def test_chain_task_name_not_found_raises_404(self) -> None:
        """Assert prepare_task_history raises HTTPNotFoundException for unknown chain task."""
        task = TaskFactory.build(
            name="test-task",
            backend=TaskBackendEnum.PROXY,
            data={"meta": {"target": "host1"}, "payload": None},
        )
        execution_data = TaskExecuteRequest(chain_task_name="nonexistent-task")
        with (
            patch(
                "app.tasks.deps.TaskManager.first",
                new_callable=AsyncMock,
                return_value=None,
            ),
            pytest.raises(HTTPNotFoundException, match="nonexistent-task"),
        ):
            await prepare_task_history(task, "test-user", AsyncMock(), execution_data)

    @pytest.mark.asyncio
    async def test_chain_task_name_not_injected_when_absent(self) -> None:
        """Assert prepare_task_history does not add chain_task_name when not set."""
        task = TaskFactory.build(
            name="test-task",
            backend=TaskBackendEnum.PROXY,
            data={"meta": {"target": "host1"}, "payload": None},
        )
        execution_data = TaskExecuteRequest()
        history = await prepare_task_history(
            task, "test-user", AsyncMock(), execution_data
        )
        assert "chain_task_name" not in history.execution_request.meta

    @pytest.mark.asyncio
    async def test_chain_task_name_overrides_task_meta(self) -> None:
        """Assert per-execution chain_task_name overrides the task's meta chain_task_name."""
        task = TaskFactory.build(
            name="test-task",
            backend=TaskBackendEnum.PROXY,
            data={
                "meta": {"target": "host1", "chain_task_name": "meta-task"},
                "payload": None,
            },
        )
        chain_task = TaskFactory.build(name="override-task")
        execution_data = TaskExecuteRequest(chain_task_name="override-task")
        with patch(
            "app.tasks.deps.TaskManager.first",
            new_callable=AsyncMock,
            return_value=chain_task,
        ):
            history = await prepare_task_history(
                task, "test-user", AsyncMock(), execution_data
            )
        assert history.execution_request.meta.get("chain_task_name") == "override-task"


@pytest_asyncio.fixture
async def task_history(session, nomad_task) -> TaskHistory:
    """Return a persisted TaskHistory for the nomad_task fixture."""
    history = TaskHistory(
        task_id=nomad_task.id,
        execution_request={
            "task": nomad_task.name,
            "target": "node-1",
            "meta": {},
            "payload": None,
            "tracking": {"evaluation_id": ""},
        },
        status=TaskHistoryStatusEnum.PENDING,
        executed_by="user-1",
    )
    session.add(history)
    await session.commit()
    await session.refresh(history)
    return history


class TestGetTaskHistory:
    """Test the get_task_history dependency."""

    @pytest.mark.asyncio
    async def test_existing_task_history(self, session, task_history) -> None:
        """Assert an existing task history is returned."""
        result = await get_task_history(session, task_history.id)
        assert result.id == task_history.id

    @pytest.mark.asyncio
    async def test_nonexistent_task_history_raises_404(self, session) -> None:
        """Assert a nonexistent task history raises HTTPNotFoundException."""
        with pytest.raises(HTTPNotFoundException):
            await get_task_history(session, 99999)


class TestGetTaskHistoryWithTask:
    """Test the get_task_history_with_task dependency."""

    @pytest.mark.asyncio
    async def test_returns_history_with_task_loaded(
        self, session, task_history, nomad_task
    ) -> None:
        """Assert task relationship is loaded on the returned history."""
        result = await get_task_history_with_task(session, task_history.id)
        assert result.id == task_history.id
        assert result.task.id == nomad_task.id
        assert result.task.name == nomad_task.name


class TestGetLogsOffsets:
    """Test the get_logs_offsets dependency."""

    def test_no_offset_params(self) -> None:
        """Assert empty query params return empty defaultdict."""
        request = _make_request()
        result = get_logs_offsets(request)
        assert isinstance(result, defaultdict)
        assert len(result) == 0

    def test_single_offset_param(self) -> None:
        """Assert a single offset param is parsed correctly."""
        request = _make_request({"step1_stdout_offset": str(OFFSET_100)})
        result = get_logs_offsets(request)
        assert result["step1"]["stdout"] == OFFSET_100

    def test_multiple_steps_and_types(self) -> None:
        """Assert multiple offset params are parsed correctly."""
        request = _make_request(
            {
                "step1_stdout_offset": str(OFFSET_100),
                "step1_stderr_offset": str(OFFSET_200),
                "step2_stdout_offset": str(OFFSET_50),
            }
        )
        result = get_logs_offsets(request)
        assert result["step1"]["stdout"] == OFFSET_100
        assert result["step1"]["stderr"] == OFFSET_200
        assert result["step2"]["stdout"] == OFFSET_50

    def test_negative_values_clamped_to_zero(self) -> None:
        """Assert negative offset values are clamped to 0."""
        request = _make_request({"step1_stdout_offset": "-50"})
        result = get_logs_offsets(request)
        assert result["step1"]["stdout"] == 0

    def test_malformed_key_skipped(self) -> None:
        """Assert keys that do not match the expected format are skipped."""
        request = _make_request({"bad_offset": "10"})
        result = get_logs_offsets(request)
        assert len(result) == 0

    def test_non_integer_value_skipped(self) -> None:
        """Assert non-integer offset values are skipped."""
        request = _make_request({"step1_stdout_offset": "abc"})
        result = get_logs_offsets(request)
        assert len(result) == 0

    def test_non_offset_params_ignored(self) -> None:
        """Assert query params not ending with _offset are ignored."""
        request = _make_request({"step1_stdout": "100", "other": "val"})
        result = get_logs_offsets(request)
        assert len(result) == 0
