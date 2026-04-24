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

"""Define test cases for the task routes in the FastAPI application."""

import base64
import gzip
import json as json_lib
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import status
from httpx import ASGITransport, AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_user
from app.core.db.crud import DEFAULT_PAGINATION_LIMIT
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.pmm import _background_tasks
from app.core.utils import utc_now
from app.tasks.config import PreExecutionCheckMode
from app.tasks.connectivity.models import ConnectivityServiceType
from app.tasks.connectivity.service import _cached_check_connectivity
from app.tasks.crud import TaskHistoryLogManager, TaskHistoryManager, TaskManager
from app.tasks.deps import get_executor, get_session
from app.tasks.execution.executors.nomad.exceptions import AllocationNotFoundError
from app.tasks.execution.models import BaseExecutor
from app.tasks.logs.log_writer import TaskHistoryLogWriter
from app.tasks.main import tasks_app
from app.tasks.models import (
    DispatchLock,
    ExecutionEvent,
    Task,
    TaskBackendEnum,
    TaskExecutionRequest,
    TaskHistory,
    TaskHistoryStatusEnum,
    TaskLogType,
    TaskWrite,
)
from tests.app.factories import TaskFactory

MOCK_FILE_SIZE = 1024
PAGINATION_TASK_COUNT = 3


@pytest_asyncio.fixture
async def created_task(session) -> Task:
    """Return a fake created task saved in the database."""
    return await TaskManager.create(
        session,
        TaskWrite.model_validate(TaskFactory.build(name="test-task")),
    )


@pytest.mark.asyncio
async def test_list_tasks_only_returns_active(test_client, session, created_task):
    """Assert listing tasks only returns active (non-deleted) tasks."""
    response = test_client.get("/")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert [task["name"] for task in data["items"]] == [created_task.name]
    assert data["total"] == 1
    assert data["offset"] == 0
    assert data["limit"] == DEFAULT_PAGINATION_LIMIT

    await TaskManager.delete_by_name(session, created_task.name)

    response = test_client.get("/")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_get_task_active_and_get_task_deleted_404(
    test_client, session, created_task
):
    """Assert retrieving an active task works and a deleted task returns 404."""
    response = test_client.get(f"/{created_task.name}")
    assert response.status_code == status.HTTP_200_OK
    task_data = response.json()
    assert "name" in task_data
    assert task_data["name"] == created_task.name

    await TaskManager.delete_by_name(session, created_task.name)

    response = test_client.get("/baz")
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_delete_task_success_and_cannot_delete_twice(
    mocker, test_client, created_task
):
    """Assert deleting a task works and cannot be deleted twice."""
    mocker.patch("app.tasks.routes.PeriodicTaskManager.delete_where", return_value=True)
    response = test_client.delete(f"/{created_task.name}")
    assert response.status_code == status.HTTP_200_OK
    task_data = response.json()
    assert "name" in task_data
    assert task_data["name"] == created_task.name

    response = test_client.delete(f"/{created_task.name}")
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_delete_task_forbidden_when_protected(test_client, session):
    """Assert deleting a protected task returns 403 Forbidden."""
    task_name = "protected-task"
    await TaskManager.create(
        session,
        TaskWrite.model_validate(TaskFactory.build(name=task_name, protected=True)),
    )

    resp = test_client.delete(f"/{task_name}")
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_create_task_success(test_client):
    """Assert creating a valid task returns 201."""
    task_data = TaskFactory.build(name="new-task")
    payload = TaskWrite.model_validate(task_data).model_dump(mode="json")
    response = test_client.post("/", json=payload)
    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["name"] == "new-task"


@pytest.mark.asyncio
async def test_create_task_duplicate_name_conflict(test_client, created_task):
    """Assert creating a task with a duplicate name returns a conflict error."""
    payload = TaskWrite.model_validate(
        TaskFactory.build(name=created_task.name)
    ).model_dump(mode="json")
    response = test_client.post("/", json=payload)
    assert response.status_code == status.HTTP_409_CONFLICT


@pytest.mark.asyncio
async def test_update_task_success(test_client, created_task):
    """Assert updating an existing task returns 201."""
    updated_data = TaskWrite.model_validate(
        TaskFactory.build(name=created_task.name)
    ).model_dump(mode="json")
    updated_data["owner"] = "BACKUPS"
    response = test_client.put(f"/{created_task.name}", json=updated_data)
    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["owner"] == "BACKUPS"


@pytest.mark.asyncio
async def test_update_task_not_found(test_client):
    """Assert updating a non-existing task returns 404."""
    payload = TaskWrite.model_validate(
        TaskFactory.build(name="nonexistent")
    ).model_dump(mode="json")
    response = test_client.put("/nonexistent", json=payload)
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_list_task_history(test_client, created_task_with_history):
    """Assert listing task history returns paginated history records."""
    response = test_client.get("/history/")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total"] == 1
    assert data["offset"] == 0
    assert data["limit"] == DEFAULT_PAGINATION_LIMIT
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == created_task_with_history.id


@pytest.mark.asyncio
async def test_list_task_history_filter_by_status(
    test_client, created_task_with_history
):
    """Assert filtering task history by status works with pagination."""
    response = test_client.get("/history/", params={"status": "success"})
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1

    response = test_client.get("/history/", params={"status": "failed"})
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total"] == 0
    assert len(data["items"]) == 0


@pytest.mark.asyncio
async def test_get_task_history_by_task_name(test_client, created_task_with_history):
    """Assert retrieving task history by task name returns paginated records."""
    task_name = created_task_with_history.task.name
    response = test_client.get(f"/{task_name}/history/")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total"] == 1
    assert data["offset"] == 0
    assert data["limit"] == DEFAULT_PAGINATION_LIMIT
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == created_task_with_history.id


@pytest.mark.asyncio
async def test_get_task_history_by_task_name_filter_by_status(
    test_client, created_task_with_history
):
    """Assert filtering task history by task name and status returns paginated results."""
    task_name = created_task_with_history.task.name
    response = test_client.get(f"/{task_name}/history/", params={"status": "running"})
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total"] == 0
    assert len(data["items"]) == 0


@pytest.mark.asyncio
async def test_retrieve_task_history_by_id(test_client, created_task_with_history):
    """Assert retrieving task history by ID returns the correct record."""
    history_id = created_task_with_history.id
    response = test_client.get(f"/history/{history_id}")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["id"] == history_id


@pytest.mark.asyncio
async def test_retrieve_task_history_by_id_not_found(test_client):
    """Assert retrieving a non-existing task history returns 404."""
    response = test_client.get("/history/99999")
    assert response.status_code == status.HTTP_404_NOT_FOUND


async def _seed_legacy_blob(
    session: AsyncSession, history: TaskHistory, legacy: dict
) -> None:
    """Encode ``legacy`` as gzip+base64 and persist it in ``tracking["task_logs"]``.

    Mirrors the seeding pattern used by the stream-logs legacy fallback tests so
    both code paths exercise the same blob shape.
    """
    encoded = base64.b64encode(gzip.compress(json_lib.dumps(legacy).encode())).decode()
    history.execution_request.tracking["task_logs"] = encoded
    await TaskHistoryManager.save(
        session, history, flag_modified_fields=["execution_request"]
    )


@pytest.mark.asyncio
async def test_list_task_history_has_logs_false_by_default(
    test_client, created_task_with_history
):
    """Assert ``has_logs`` is ``False`` when no chunks and no legacy blob exist."""
    response = test_client.get("/history/")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["items"][0]["has_logs"] is False


@pytest.mark.asyncio
async def test_list_task_history_has_logs_true_from_chunk_store(
    test_client, session, created_task_with_history
):
    """Assert ``has_logs`` is ``True`` when the chunk store has rows."""
    await TaskHistoryLogWriter.append(
        session,
        created_task_with_history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"chunk output",
        force_flush=True,
        producer_offset_after=12,
    )

    response = test_client.get("/history/")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["items"][0]["has_logs"] is True


@pytest.mark.asyncio
async def test_list_task_history_has_logs_true_from_legacy_blob(
    test_client, session, created_task_with_history
):
    """Assert ``has_logs`` is ``True`` when only the legacy blob is present."""
    await _seed_legacy_blob(
        session,
        created_task_with_history,
        {"run-script": {"stdout": "legacy stdout", "stderr": ""}},
    )

    response = test_client.get("/history/")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["items"][0]["has_logs"] is True


@pytest.mark.asyncio
async def test_list_task_history_has_logs_mixed_rows(
    test_client, session, created_task_with_history
):
    """Assert ``has_logs`` is independently populated per row (chunk / legacy / none)."""
    task = created_task_with_history.task
    with_chunks = await TaskHistoryManager.save(
        session,
        TaskHistory(
            task_id=task.id,
            execution_request={
                "task": task.name,
                "target": "node2",
                "meta": {"target": "node2"},
                "tracking": {"allocation_id": None, "evaluation_id": None},
            },
            status=TaskHistoryStatusEnum.SUCCESS,
            executed_by="test-user",
        ),
    )
    without_logs = await TaskHistoryManager.save(
        session,
        TaskHistory(
            task_id=task.id,
            execution_request={
                "task": task.name,
                "target": "node3",
                "meta": {"target": "node3"},
                "tracking": {"allocation_id": None, "evaluation_id": None},
            },
            status=TaskHistoryStatusEnum.SUCCESS,
            executed_by="test-user",
        ),
    )
    await TaskHistoryLogWriter.append(
        session,
        with_chunks.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"chunk output",
        force_flush=True,
        producer_offset_after=12,
    )
    await _seed_legacy_blob(
        session,
        created_task_with_history,
        {"run-script": {"stdout": "legacy", "stderr": ""}},
    )

    response = test_client.get("/history/")

    assert response.status_code == status.HTTP_200_OK
    items_by_id = {item["id"]: item for item in response.json()["items"]}
    assert items_by_id[with_chunks.id]["has_logs"] is True
    assert items_by_id[created_task_with_history.id]["has_logs"] is True
    assert items_by_id[without_logs.id]["has_logs"] is False


@pytest.mark.asyncio
async def test_list_task_history_empty_does_not_crash(test_client):
    """Assert the empty-list case returns 200 and no SQL from ``ids_with_chunks``."""
    response = test_client.get("/history/")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["items"] == []


@pytest.mark.asyncio
async def test_get_task_history_populates_has_logs(
    test_client, session, created_task_with_history
):
    """Assert ``has_logs`` is populated on the ``/{task}/history/`` list endpoint."""
    await TaskHistoryLogWriter.append(
        session,
        created_task_with_history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"chunk output",
        force_flush=True,
        producer_offset_after=12,
    )

    response = test_client.get(f"/{created_task_with_history.task.name}/history/")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["items"][0]["has_logs"] is True


@pytest.mark.asyncio
async def test_retrieve_task_history_populates_has_logs_from_chunk_store(
    test_client, session, created_task_with_history
):
    """Assert ``has_logs`` is ``True`` on the retrieve-by-id endpoint for chunk rows."""
    await TaskHistoryLogWriter.append(
        session,
        created_task_with_history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"chunk output",
        force_flush=True,
        producer_offset_after=12,
    )

    response = test_client.get(f"/history/{created_task_with_history.id}")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["has_logs"] is True


@pytest.mark.asyncio
async def test_retrieve_task_history_populates_has_logs_from_legacy_blob(
    test_client, session, created_task_with_history
):
    """Assert ``has_logs`` is ``True`` on the retrieve endpoint for legacy-only rows."""
    await _seed_legacy_blob(
        session,
        created_task_with_history,
        {"run-script": {"stdout": "legacy", "stderr": ""}},
    )

    response = test_client.get(f"/history/{created_task_with_history.id}")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["has_logs"] is True


@pytest.mark.asyncio
async def test_retrieve_task_history_has_logs_false_when_neither(
    test_client, created_task_with_history
):
    """Assert ``has_logs`` is ``False`` when neither chunks nor legacy blob exist."""
    response = test_client.get(f"/history/{created_task_with_history.id}")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["has_logs"] is False


@pytest.mark.asyncio
async def test_list_task_history_events(
    test_client, created_task_with_history, mock_executor
):
    """Assert the events endpoint returns executor-provided events (oldest-first order)."""
    dt = utc_now()
    mock_executor.get_events.return_value = [
        ExecutionEvent(
            timestamp=dt,
            event_type="Terminated",
            description="Exit 1",
            step="run-script",
        )
    ]
    response = test_client.get(f"/history/{created_task_with_history.id}/events")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) == 1
    assert data[0]["type"] == "Terminated"
    assert data[0]["description"] == "Exit 1"
    assert data[0]["step"] == "run-script"
    assert "timestamp" in data[0]
    mock_executor.get_events.assert_called_once()


@pytest.mark.asyncio
async def test_list_task_history_events_empty_by_default(
    test_client, created_task_with_history, mock_executor
):
    """Assert the mock executor returns no events unless configured."""
    response = test_client.get(f"/history/{created_task_with_history.id}/events")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == []


@pytest.mark.asyncio
async def test_stream_logs_pending_returns_409(
    test_client, session, created_task_with_history
):
    """Assert streaming logs for a PENDING task history returns 409."""
    created_task_with_history.status = TaskHistoryStatusEnum.PENDING
    await TaskHistoryManager.save(session, created_task_with_history)

    response = test_client.get(f"/history/{created_task_with_history.id}/logs/")
    assert response.status_code == status.HTTP_409_CONFLICT


@pytest.mark.asyncio
async def test_stream_logs_finished_returns_logs(
    test_client, created_task_with_history
):
    """Assert streaming logs for a finished task history returns log content."""
    response = test_client.get(f"/history/{created_task_with_history.id}/logs/")
    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "application/json"


@pytest.mark.asyncio
async def test_stream_logs_finished_reads_chunks_from_taskhistory_log(
    test_client, session, created_task_with_history
):
    """Assert the finished branch streams from the chunk store when available."""
    await TaskHistoryLogWriter.append(
        session,
        created_task_with_history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"chunk store output",
        force_flush=True,
        producer_offset_after=18,
    )

    response = test_client.get(f"/history/{created_task_with_history.id}/logs/")
    assert response.status_code == status.HTTP_200_OK
    assert "chunk store output" in response.text


@pytest.mark.asyncio
async def test_stream_logs_finished_falls_back_to_legacy_blob(
    test_client, session, created_task_with_history
):
    """Assert the finished branch falls back to the legacy blob when no chunks exist."""
    legacy = {"run-script": {"stdout": "legacy from tracking", "stderr": ""}}
    encoded = base64.b64encode(gzip.compress(json_lib.dumps(legacy).encode())).decode()
    created_task_with_history.execution_request.tracking["task_logs"] = encoded
    await TaskHistoryManager.save(
        session,
        created_task_with_history,
        flag_modified_fields=["execution_request"],
    )
    response = test_client.get(f"/history/{created_task_with_history.id}/logs/")
    assert response.status_code == status.HTTP_200_OK
    assert "legacy from tracking" in response.text


@pytest.mark.asyncio
async def test_stream_logs_running_uses_executor(
    test_client, session, mock_executor, created_task_with_history
):
    """Assert streaming logs for a RUNNING task delegates to executor."""
    created_task_with_history.status = TaskHistoryStatusEnum.RUNNING
    await TaskHistoryManager.save(session, created_task_with_history)

    async def mock_stream():
        return
        yield

    mock_executor.stream_logs = MagicMock(return_value=mock_stream())
    response = test_client.get(f"/history/{created_task_with_history.id}/logs/")
    assert response.status_code == status.HTTP_200_OK
    mock_executor.preflight_stream_logs.assert_called_once_with(
        created_task_with_history
    )


@pytest.mark.asyncio
async def test_stream_logs_running_preflight_allocation_gone_returns_410(
    test_client, session, mock_executor, created_task_with_history
):
    """Assert TaskDataNotFound during preflight returns 410 before streaming starts."""
    created_task_with_history.status = TaskHistoryStatusEnum.RUNNING
    await TaskHistoryManager.save(session, created_task_with_history)
    mock_executor.preflight_stream_logs.side_effect = AllocationNotFoundError(
        "No allocations",
        executor_name="nomad",
        resource_type="allocation",
        resource_id='JobID == "j" and EvalID == "e"',
    )
    response = test_client.get(f"/history/{created_task_with_history.id}/logs/")
    assert response.status_code == status.HTTP_410_GONE
    detail = response.json()["detail"]
    assert detail["resource_type"] == "allocation"


@pytest.mark.asyncio
async def test_list_files_not_finished_returns_409(
    test_client, session, created_task_with_history
):
    """Assert listing files for a non-finished task returns 409."""
    created_task_with_history.status = TaskHistoryStatusEnum.RUNNING
    await TaskHistoryManager.save(session, created_task_with_history)

    response = test_client.get(f"/history/{created_task_with_history.id}/files/")
    assert response.status_code == status.HTTP_409_CONFLICT


@pytest.mark.asyncio
async def test_list_files_no_output_path_returns_400(
    test_client, session, created_task_with_history
):
    """Assert listing files when output_files_path is None returns 400."""
    created_task_with_history.task.output_files_path = None
    await TaskManager.save(session, created_task_with_history.task)

    response = test_client.get(f"/history/{created_task_with_history.id}/files/")
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_list_files_success(
    test_client, mock_executor, created_task_with_history
):
    """Assert listing files for a finished task with output path returns file metadata."""
    mock_executor.list_files.return_value = {
        "backup.sql": {"size": MOCK_FILE_SIZE, "is_dir": False}
    }
    response = test_client.get(f"/history/{created_task_with_history.id}/files/")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "backup.sql" in data
    assert data["backup.sql"]["size"] == MOCK_FILE_SIZE


@pytest.mark.asyncio
async def test_stream_file_not_finished_returns_409(
    test_client, session, created_task_with_history
):
    """Assert streaming a file for a non-finished task returns 409."""
    created_task_with_history.status = TaskHistoryStatusEnum.RUNNING
    await TaskHistoryManager.save(session, created_task_with_history)

    response = test_client.get(
        f"/history/{created_task_with_history.id}/file/",
        params={"path": "backup.sql"},
    )
    assert response.status_code == status.HTTP_409_CONFLICT


@pytest.mark.asyncio
async def test_stream_file_no_output_path_returns_400(
    test_client, session, created_task_with_history
):
    """Assert streaming a file when output_files_path is None returns 400."""
    created_task_with_history.task.output_files_path = None
    await TaskManager.save(session, created_task_with_history.task)

    response = test_client.get(
        f"/history/{created_task_with_history.id}/file/",
        params={"path": "backup.sql"},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_stream_file_success(
    test_client, mock_executor, created_task_with_history
):
    """Assert streaming a file for a finished task returns file content."""

    async def mock_stream():
        yield b"file content"

    mock_executor.stream_file = MagicMock(return_value=mock_stream())
    response = test_client.get(
        f"/history/{created_task_with_history.id}/file/",
        params={"path": "backup.sql"},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.content == b"file content"


@pytest.mark.asyncio
async def test_stop_task_pending_with_celery_id(
    test_client, session, created_task_with_history
):
    """Assert stopping a PENDING task with a celery_task_id revokes and deletes it."""
    created_task_with_history.status = TaskHistoryStatusEnum.PENDING
    created_task_with_history.execution_request.tracking["celery_task_id"] = (
        "celery-123"
    )
    await TaskHistoryManager.save(
        session,
        created_task_with_history,
        flag_modified_fields=["execution_request"],
    )

    with patch("app.tasks.routes.celery") as mock_celery:
        response = test_client.post(f"/history/{created_task_with_history.id}/stop/")

    assert response.status_code == status.HTTP_200_OK
    mock_celery.control.revoke.assert_called_once_with("celery-123")


@pytest.mark.asyncio
async def test_stop_task_pending_without_celery_id(
    test_client, session, created_task_with_history
):
    """Assert stopping a PENDING task without celery_task_id just deletes it."""
    created_task_with_history.status = TaskHistoryStatusEnum.PENDING
    created_task_with_history.execution_request.tracking.pop("celery_task_id", None)
    await TaskHistoryManager.save(
        session,
        created_task_with_history,
        flag_modified_fields=["execution_request"],
    )

    response = test_client.post(f"/history/{created_task_with_history.id}/stop/")
    assert response.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_stop_task_running_calls_executor(
    test_client, session, mock_executor, created_task_with_history
):
    """Assert stopping a RUNNING task calls executor.stop_task."""
    created_task_with_history.status = TaskHistoryStatusEnum.RUNNING
    await TaskHistoryManager.save(session, created_task_with_history)

    mock_executor.stop_task.return_value = created_task_with_history
    response = test_client.post(f"/history/{created_task_with_history.id}/stop/")
    assert response.status_code == status.HTTP_200_OK
    mock_executor.stop_task.assert_called_once()


@pytest.mark.asyncio
async def test_stop_task_finished_returns_400(test_client, created_task_with_history):
    """Assert stopping a finished task returns 400."""
    response = test_client.post(f"/history/{created_task_with_history.id}/stop/")
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_sync_task_history_running_calls_executor(
    test_client, session, mock_executor, created_task_with_history
):
    """Assert syncing a RUNNING task calls executor.sync_task_history and persists status."""
    created_task_with_history.status = TaskHistoryStatusEnum.RUNNING
    await TaskHistoryManager.save(session, created_task_with_history)

    async def fake_sync(item, writer_session=None):
        item.status = TaskHistoryStatusEnum.SUCCESS
        item.finished_at = utc_now()
        return item

    mock_executor.sync_task_history = AsyncMock(side_effect=fake_sync)
    response = test_client.post(f"/history/{created_task_with_history.id}/sync/")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == TaskHistoryStatusEnum.SUCCESS.value
    mock_executor.sync_task_history.assert_called_once()


@pytest.mark.asyncio
async def test_sync_task_history_not_running_skips_executor(
    test_client, mock_executor, created_task_with_history
):
    """Assert syncing a non-running task returns current status without calling the executor."""
    response = test_client.post(f"/history/{created_task_with_history.id}/sync/")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == TaskHistoryStatusEnum.SUCCESS.value
    mock_executor.sync_task_history.assert_not_called()


@pytest.mark.asyncio
async def test_sync_task_history_not_running_still_populates_has_logs(
    test_client, session, created_task_with_history
):
    """Assert the early-return branch (already-finished) still populates ``has_logs``.

    Regression: the sync endpoint short-circuits when the task has already
    finished. Before the fix, the early return skipped ``_populate_has_logs``
    so the response always had ``has_logs=False`` even when chunks existed,
    which broke the API contract relative to ``GET /history/{id}``.
    """
    await TaskHistoryLogWriter.append(
        session,
        created_task_with_history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"chunk output",
        force_flush=True,
        producer_offset_after=12,
    )

    response = test_client.post(f"/history/{created_task_with_history.id}/sync/")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["has_logs"] is True


@pytest.mark.asyncio
async def test_sync_task_history_populates_has_logs(
    test_client, session, mock_executor, created_task_with_history
):
    """Assert the sync endpoint populates ``has_logs`` when chunks exist."""
    created_task_with_history.status = TaskHistoryStatusEnum.RUNNING
    await TaskHistoryManager.save(session, created_task_with_history)
    await TaskHistoryLogWriter.append(
        session,
        created_task_with_history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"chunk output",
        force_flush=True,
        producer_offset_after=12,
    )

    async def fake_sync(item, writer_session=None):
        item.status = TaskHistoryStatusEnum.SUCCESS
        item.finished_at = utc_now()
        return item

    mock_executor.sync_task_history = AsyncMock(side_effect=fake_sync)
    response = test_client.post(f"/history/{created_task_with_history.id}/sync/")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["has_logs"] is True


@pytest.mark.asyncio
async def test_stop_task_running_populates_has_logs(
    test_client, session, mock_executor, created_task_with_history
):
    """Assert the stop endpoint populates ``has_logs`` on the running → stopped response."""
    created_task_with_history.status = TaskHistoryStatusEnum.RUNNING
    await TaskHistoryManager.save(session, created_task_with_history)
    await TaskHistoryLogWriter.append(
        session,
        created_task_with_history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"chunk output",
        force_flush=True,
        producer_offset_after=12,
    )
    mock_executor.stop_task.return_value = created_task_with_history

    response = test_client.post(f"/history/{created_task_with_history.id}/stop/")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["has_logs"] is True


@pytest.mark.asyncio
async def test_get_task_stats(test_client, created_task_with_history):
    """Assert retrieving task stats returns computed statistics."""
    task_name = created_task_with_history.task.name
    response = test_client.get(f"/stats/{task_name}")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "total" in data
    assert data["total"] == 1
    assert "status" in data
    assert "duration" in data


@pytest.mark.asyncio
async def test_get_task_stats_empty(test_client, created_task):
    """Assert retrieving stats for a task with no history returns zero total."""
    response = test_client.get(f"/stats/{created_task.name}")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["total"] == 0


@pytest.mark.asyncio
async def test_get_executor_hosts(test_client, mock_executor):
    """Assert retrieving executor hosts returns the enriched HostInfo shape.

    ``healthy`` and ``last_checked`` default to ``None`` when no
    ``NodeHealthCheck`` row has been upserted yet; that state is rendered
    as "Unknown" on the homepage.
    """
    response = test_client.get("/hosts/")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "node1": {
            "address": "10.0.0.1",
            "healthy": None,
            "last_checked": None,
            "error_message": None,
        }
    }


@pytest.mark.asyncio
async def test_transform_payload_proxy_backend(test_client):
    """Assert transforming a payload with PROXY backend calls parse_payload."""
    with patch(
        "app.tasks.routes.parse_payload", return_value={"key": "value"}
    ) as mock_parse:
        response = test_client.post(
            "/transform/",
            json={"payload": '{"key": "value"}', "fmt": "json"},
            params={"backend": "proxy"},
        )
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"key": "value"}
    mock_parse.assert_called_once_with('{"key": "value"}', "json")


@pytest.mark.asyncio
async def test_transform_payload_nomad_backend(test_client, mock_executor):
    """Assert transforming a payload with NOMAD backend calls executor."""
    with patch("app.tasks.routes.get_executor", return_value=mock_executor):
        mock_executor.transform_payload.return_value = {"parsed": True}
        response = test_client.post(
            "/transform/",
            json={"payload": '{"job": {}}', "fmt": "json"},
            params={"backend": "nomad"},
        )
    assert response.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_task_data_with_execution_request_keys_returned_as_dict(
    test_client, session
):
    """Test that Task.data with TaskExecutionRequest-like keys is returned as a dict."""
    conflicting_data = {
        "task": "run-python",
        "target": "mariadb",
        "payload": "SELECT 1",
        "meta": {"env": "staging"},
    }
    await TaskManager.create(
        session,
        TaskWrite.model_validate(
            TaskFactory.build(name="conflicting-task", data=conflicting_data),
        ),
    )

    response = test_client.get("/conflicting-task")
    assert response.status_code == status.HTTP_200_OK
    task_json = response.json()
    assert task_json["data"] == conflicting_data
    assert isinstance(task_json["data"], dict)


@pytest.mark.asyncio
async def test_list_tasks_custom_pagination(test_client, session):
    """Assert custom offset and limit are respected for task listing."""
    for i in range(PAGINATION_TASK_COUNT):
        await TaskManager.create(
            session,
            TaskWrite.model_validate(TaskFactory.build(name=f"task-{i}")),
        )

    response = test_client.get("/", params={"offset": 0, "limit": 1})
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data["items"]) == 1
    assert data["total"] == PAGINATION_TASK_COUNT
    assert data["offset"] == 0
    assert data["limit"] == 1


@pytest.mark.asyncio
async def test_list_tasks_offset_beyond_total(test_client, created_task):
    """Assert offset beyond total returns empty items with correct total."""
    response = test_client.get("/", params={"offset": 999})
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 1


@pytest.mark.asyncio
async def test_list_task_history_custom_pagination(
    test_client, created_task_with_history
):
    """Assert custom offset and limit are respected for task history listing."""
    response = test_client.get("/history/", params={"offset": 0, "limit": 1})
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data["items"]) == 1
    assert data["total"] == 1

    response = test_client.get("/history/", params={"offset": 999})
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 1


@pytest.mark.asyncio
async def test_get_task_history_custom_pagination(
    test_client, created_task_with_history
):
    """Assert custom offset and limit are respected for per-task history."""
    task_name = created_task_with_history.task.name
    response = test_client.get(
        f"/{task_name}/history/", params={"offset": 0, "limit": 1}
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data["items"]) == 1
    assert data["total"] == 1

    response = test_client.get(f"/{task_name}/history/", params={"offset": 999})
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 1


@pytest.mark.asyncio
async def test_list_tasks_filter_with_pagination(test_client, session):
    """Assert owner filter works together with pagination."""
    await TaskManager.create(
        session,
        TaskWrite.model_validate(TaskFactory.build(name="backup-1", owner="BACKUPS")),
    )
    await TaskManager.create(
        session,
        TaskWrite.model_validate(TaskFactory.build(name="alter-1", owner="ALTERS")),
    )

    response = test_client.get("/", params={"owner": "BACKUPS", "limit": 1})
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["name"] == "backup-1"


@pytest.mark.asyncio
async def test_list_task_history_status_filter_with_pagination(
    test_client, created_task_with_history
):
    """Assert status filter and pagination work together for task history."""
    response = test_client.get("/history/", params={"status": "success", "limit": 1})
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1

    response = test_client.get("/history/", params={"status": "failed", "offset": 0})
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.asyncio
async def test_get_task_history_status_filter_with_pagination(
    test_client, created_task_with_history
):
    """Assert status filter and pagination work together for per-task history."""
    task_name = created_task_with_history.task.name
    response = test_client.get(
        f"/{task_name}/history/", params={"status": "success", "limit": 1}
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1


@pytest.mark.asyncio
async def test_execute_task_name_response_serializes_deferred_execution_request(
    test_client, session, mocker
):
    """Assert POST /execute/{task_name} serializes the deferred ``execution_request``.

    Regression for a ``MissingGreenlet`` error: ``TaskHistory.execution_request`` is
    mapped as a deferred column, and ``TaskHistoryManager.save`` expires it via
    ``session.refresh`` after commit. The route must load it eagerly before
    returning, otherwise FastAPI serialization triggers a lazy load after the
    async session has closed.
    """
    task = await TaskManager.create(
        session,
        TaskWrite.model_validate(
            TaskFactory.build(name="execute-task", anonymize_mask=0)
        ),
    )

    async def fake_dispatch_queue_item(queue_item, passed_session):
        queue_item.status = TaskHistoryStatusEnum.RUNNING
        return await TaskHistoryManager.save(
            passed_session,
            queue_item,
            flag_modified_fields=["execution_request"],
        )

    fake_executor = MagicMock(spec=BaseExecutor)
    fake_executor.get_hosts.return_value = {"node1": "10.0.0.1"}
    mocker.patch("app.tasks.routes.get_executor_for_task", return_value=fake_executor)
    mocker.patch(
        "app.tasks.routes.dispatch_queue_item",
        side_effect=fake_dispatch_queue_item,
    )

    response = test_client.post(
        f"/execute/{task.name}",
        json={"meta_target": "node1"},
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["status"] == TaskHistoryStatusEnum.RUNNING.value
    assert data["execution_request"]["task"] == task.name
    assert data["execution_request"]["target"] == "node1"


@pytest.mark.asyncio
async def test_execute_task_name_with_eta_serializes_deferred_execution_request(
    test_client, session, mocker
):
    """Assert POST /execute/{task_name} with ETA serializes the deferred column.

    Regression for a ``MissingGreenlet`` error on the ETA scheduling path:
    after ``TaskHistoryManager.save`` the deferred ``execution_request`` column
    is expired. Accessing ``history_recorded.execution_request.eta`` before
    refreshing triggers a lazy load outside the greenlet context.
    """
    task = await TaskManager.create(
        session,
        TaskWrite.model_validate(TaskFactory.build(name="eta-task", anonymize_mask=0)),
    )

    fake_celery_result = MagicMock()
    fake_celery_result.id = "fake-celery-task-id"

    fake_executor = MagicMock(spec=BaseExecutor)
    fake_executor.get_hosts.return_value = {"node1": "10.0.0.1"}
    mocker.patch("app.tasks.routes.get_executor_for_task", return_value=fake_executor)
    mocker.patch(
        "app.tasks.routes.execute_task_queue.apply_async",
        return_value=fake_celery_result,
    )

    eta = (utc_now() + timedelta(seconds=30)).isoformat()
    response = test_client.post(
        f"/execute/{task.name}",
        json={"meta_target": "node1", "eta": eta},
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["execution_request"]["task"] == task.name
    assert data["execution_request"]["target"] == "node1"
    assert (
        data["execution_request"]["tracking"]["celery_task_id"] == "fake-celery-task-id"
    )


@pytest.mark.asyncio
async def test_execute_route_keeps_scheduled_at_out_of_meta(
    test_client, session, mocker
):
    """Assert POST /execute/{task_name} never writes ``scheduled_at`` to meta.

    The dispatch dedup path iterates every meta key to identify identical
    pending/running tasks, so a per-call timestamp would silently disable
    the guard. The staleness value is derived at dispatch time from ``eta``
    / ``created_at`` instead.
    """
    task = await TaskManager.create(
        session,
        TaskWrite.model_validate(
            TaskFactory.build(name="stale-meta-free", anonymize_mask=0)
        ),
    )

    async def fake_dispatch_queue_item(queue_item, passed_session):
        queue_item.status = TaskHistoryStatusEnum.RUNNING
        return await TaskHistoryManager.save(
            passed_session,
            queue_item,
            flag_modified_fields=["execution_request"],
        )

    fake_executor = MagicMock(spec=BaseExecutor)
    fake_executor.get_hosts.return_value = {"node1": "10.0.0.1"}
    mocker.patch("app.tasks.routes.get_executor_for_task", return_value=fake_executor)
    mocker.patch(
        "app.tasks.routes.dispatch_queue_item",
        side_effect=fake_dispatch_queue_item,
    )

    response = test_client.post(
        f"/execute/{task.name}",
        json={"meta_target": "node1", "meta_foo": "bar"},
    )

    assert response.status_code == status.HTTP_200_OK
    meta = response.json()["execution_request"]["meta"]
    assert meta["target"] == "node1"
    assert meta["foo"] == "bar"
    assert "scheduled_at" not in meta


@pytest.mark.asyncio
async def test_execute_task_name_refreshes_execution_request_before_annotation(
    test_client, session, mock_executor, mocker
):
    """Assert the STARTED annotation fires against a loaded ``execution_request``.

    Regression for SEP-1017. Exercise the full
    ``POST /execute/{task_name}`` → ``_dispatch_queue_item`` →
    ``schedule_annotation(result, "STARTED")`` flow with a real session
    and a fake executor whose ``dispatch_task`` runs the real
    ``TaskHistoryManager.save`` (which re-defers the deferred
    ``execution_request`` ``column_property``). Let the real
    ``schedule_annotation`` run so its precondition guard exercises
    against the refreshed instance; mock only
    ``create_pmm_annotation`` (the outermost HTTP boundary) and assert
    the annotation was scheduled with the expected primitives.

    Before the fix, this test reproduces ``MissingGreenlet`` against the
    async ``aiosqlite`` driver.
    """
    task = await TaskManager.create(
        session,
        TaskWrite.model_validate(
            TaskFactory.build(name="annotation-task", anonymize_mask=0)
        ),
    )

    async def fake_dispatch_task(passed_session, queue_item, _task=None):
        queue_item.status = TaskHistoryStatusEnum.RUNNING
        return await TaskHistoryManager.save(
            passed_session, queue_item, flag_modified_fields=["execution_request"]
        )

    mock_executor.dispatch_task = fake_dispatch_task

    mocker.patch(
        "app.tasks.celery.DispatchLockManager.delete_where",
        new_callable=AsyncMock,
    )
    mocker.patch(
        "app.tasks.celery.DispatchLockManager.create",
        new_callable=AsyncMock,
        return_value=MagicMock(spec=DispatchLock),
    )
    mocker.patch("app.tasks.celery.DispatchLockManager.delete", new_callable=AsyncMock)
    mocker.patch(
        "app.tasks.celery._raise_if_identical_task_conflict", new_callable=AsyncMock
    )
    mocker.patch("app.tasks.routes.get_executor_for_task", return_value=mock_executor)
    mocker.patch("app.tasks.celery.get_executor_for_task", return_value=mock_executor)
    mock_pmm_create = mocker.patch(
        "app.core.pmm.create_pmm_annotation", new_callable=AsyncMock
    )
    _background_tasks.clear()

    response = test_client.post(
        f"/execute/{task.name}",
        json={"meta_target": "node1"},
    )

    for bg_task in list(_background_tasks):
        await bg_task

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["status"] == TaskHistoryStatusEnum.RUNNING.value
    mock_pmm_create.assert_awaited_once()
    assert mock_pmm_create.await_args.kwargs["text"].endswith("- STARTED")
    assert mock_pmm_create.await_args.kwargs["node_name"] == "node1"


# Note: the corresponding regression for ``POST /history/{id}/stop/`` →
# ``BaseExecutor.stop_task`` → ``schedule_annotation(saved, "STOPPED")``
# lives at helper level in
# ``tests/app/tasks/execution/test_models.py::TestStopTaskRegression``.
# That test exercises the real ``BaseExecutor.stop_task`` against a real
# ``AsyncSession`` — the exact code path SEP-1017 fixes. An HTTP-level
# peer would additionally exercise response-model serialization, which
# hits a pre-existing deferred-relationship issue on ``TaskHistory.task``
# that is out of scope for SEP-1017; the existing
# ``test_stop_task_running_calls_executor`` already covers the route's
# 200 contract.


CONNECTIVITY_META = {
    "_connectivity_host": "db-host",
    "_connectivity_port": "3306",
    "_connectivity_service_type": ConnectivityServiceType.MYSQL.value,
}


async def _fake_dispatch_queue_item(
    queue_item: TaskHistory, passed_session: AsyncSession
) -> TaskHistory:
    """Persist the queue item so the route's ``session.refresh`` call succeeds.

    :param queue_item: The ``TaskHistory`` queue item dispatched by the route.
    :type queue_item: TaskHistory
    :param passed_session: The async database session the route passes along.
    :type passed_session: AsyncSession
    :return: The persisted ``TaskHistory`` instance.
    :rtype: TaskHistory
    """
    queue_item.status = TaskHistoryStatusEnum.RUNNING
    return await TaskHistoryManager.save(
        passed_session,
        queue_item,
        flag_modified_fields=["execution_request"],
    )


class TestPreExecutionConnectivityCheck:
    """Test the pre-execution connectivity check in execute_task_name."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        """Clear the connectivity result cache around each test."""
        _cached_check_connectivity.cache_clear()
        yield
        _cached_check_connectivity.cache_clear()

    @pytest_asyncio.fixture
    async def conn_task(self, session) -> Task:
        """Return a task with connectivity meta."""
        return await TaskManager.create(
            session,
            TaskWrite.model_validate(
                TaskFactory.build(
                    name="conn-task",
                    data={"Meta": CONNECTIVITY_META},
                )
            ),
        )

    @pytest.mark.asyncio
    async def test_disabled_skips_check(
        self, test_client, mocker, conn_task, mock_executor
    ):
        """Verify no connectivity check runs when mode is ``disabled``."""
        mocker.patch(
            "app.tasks.routes.tasks_settings.PRE_EXECUTION_CONNECTIVITY_CHECK",
            PreExecutionCheckMode.DISABLED,
        )
        mocker.patch(
            "app.tasks.routes.get_executor_for_task",
            return_value=mock_executor,
        )
        mock_dispatch = mocker.patch(
            "app.tasks.routes.dispatch_queue_item",
            side_effect=_fake_dispatch_queue_item,
        )
        mock_check = mocker.patch("app.tasks.routes.check_connectivity_with_cache")

        response = test_client.post(
            f"/execute/{conn_task.name}",
            json={"meta": {"target": "node1"}},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_check.assert_not_called()
        mock_dispatch.assert_called_once()

    @pytest.mark.asyncio
    async def test_warn_success_dispatches(
        self, test_client, mocker, conn_task, mock_executor
    ):
        """Verify dispatch proceeds when warn-mode check passes."""
        mocker.patch(
            "app.tasks.routes.tasks_settings.PRE_EXECUTION_CONNECTIVITY_CHECK",
            PreExecutionCheckMode.WARN,
        )
        mocker.patch(
            "app.tasks.routes.get_executor_for_task",
            return_value=mock_executor,
        )
        mocker.patch(
            "app.tasks.routes.check_connectivity_with_cache",
            new=AsyncMock(return_value=(True, None)),
        )
        mock_dispatch = mocker.patch(
            "app.tasks.routes.dispatch_queue_item",
            side_effect=_fake_dispatch_queue_item,
        )

        response = test_client.post(
            f"/execute/{conn_task.name}",
            json={"meta": {"target": "node1"}},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_dispatch.assert_called_once()

    @pytest.mark.asyncio
    async def test_warn_failure_logs_warning_and_dispatches(
        self, test_client, mocker, conn_task, mock_executor
    ):
        """Verify dispatch proceeds with a warning when warn-mode check fails."""
        mocker.patch(
            "app.tasks.routes.tasks_settings.PRE_EXECUTION_CONNECTIVITY_CHECK",
            PreExecutionCheckMode.WARN,
        )
        mocker.patch(
            "app.tasks.routes.get_executor_for_task",
            return_value=mock_executor,
        )
        mocker.patch(
            "app.tasks.routes.check_connectivity_with_cache",
            new=AsyncMock(return_value=(False, "Connection refused")),
        )
        mock_dispatch = mocker.patch(
            "app.tasks.routes.dispatch_queue_item",
            side_effect=_fake_dispatch_queue_item,
        )
        mock_logger = mocker.patch("app.tasks.routes.logger")

        response = test_client.post(
            f"/execute/{conn_task.name}",
            json={"meta": {"target": "node1"}},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_dispatch.assert_called_once()
        mock_logger.warning.assert_called_once()
        assert "Connection refused" in mock_logger.warning.call_args[0][0]

    @pytest.mark.asyncio
    async def test_block_success_dispatches(
        self, test_client, mocker, conn_task, mock_executor
    ):
        """Verify dispatch proceeds when block-mode check passes."""
        mocker.patch(
            "app.tasks.routes.tasks_settings.PRE_EXECUTION_CONNECTIVITY_CHECK",
            PreExecutionCheckMode.BLOCK,
        )
        mocker.patch(
            "app.tasks.routes.get_executor_for_task",
            return_value=mock_executor,
        )
        mocker.patch(
            "app.tasks.routes.check_connectivity_with_cache",
            new=AsyncMock(return_value=(True, None)),
        )
        mock_dispatch = mocker.patch(
            "app.tasks.routes.dispatch_queue_item",
            side_effect=_fake_dispatch_queue_item,
        )

        response = test_client.post(
            f"/execute/{conn_task.name}",
            json={"meta": {"target": "node1"}},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_dispatch.assert_called_once()

    @pytest.mark.asyncio
    async def test_block_failure_returns_400(
        self, test_client, mocker, conn_task, mock_executor
    ):
        """Verify dispatch is blocked with 400 when block-mode check fails."""
        mocker.patch(
            "app.tasks.routes.tasks_settings.PRE_EXECUTION_CONNECTIVITY_CHECK",
            PreExecutionCheckMode.BLOCK,
        )
        mocker.patch(
            "app.tasks.routes.get_executor_for_task",
            return_value=mock_executor,
        )
        mocker.patch(
            "app.tasks.routes.check_connectivity_with_cache",
            new=AsyncMock(return_value=(False, "Connection refused")),
        )
        mock_dispatch = mocker.patch(
            "app.tasks.routes.dispatch_queue_item",
            new=AsyncMock(),
        )

        response = test_client.post(
            f"/execute/{conn_task.name}",
            json={"meta": {"target": "node1"}},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Connection refused" in response.json()["detail"]
        mock_dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_connectivity_meta_skips_check(
        self, test_client, session, mocker, mock_executor
    ):
        """Verify check is skipped when task has no connectivity meta fields."""
        task = await TaskManager.create(
            session,
            TaskWrite.model_validate(TaskFactory.build(name="no-meta-task", data={})),
        )

        mocker.patch(
            "app.tasks.routes.tasks_settings.PRE_EXECUTION_CONNECTIVITY_CHECK",
            PreExecutionCheckMode.BLOCK,
        )
        mocker.patch(
            "app.tasks.routes.get_executor_for_task",
            return_value=mock_executor,
        )
        mock_check = mocker.patch("app.tasks.routes.check_connectivity_with_cache")
        mocker.patch(
            "app.tasks.routes.dispatch_queue_item",
            side_effect=_fake_dispatch_queue_item,
        )

        response = test_client.post(
            f"/execute/{task.name}",
            json={"meta": {"target": "node1"}},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_check.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_called_with_parsed_meta(
        self, test_client, mocker, conn_task, mock_executor
    ):
        """Verify ``check_connectivity_with_cache`` receives parsed meta args."""
        mocker.patch(
            "app.tasks.routes.tasks_settings.PRE_EXECUTION_CONNECTIVITY_CHECK",
            PreExecutionCheckMode.BLOCK,
        )
        mocker.patch(
            "app.tasks.routes.get_executor_for_task",
            return_value=mock_executor,
        )
        mock_check = mocker.patch(
            "app.tasks.routes.check_connectivity_with_cache",
            new=AsyncMock(return_value=(True, None)),
        )
        mock_dispatch = mocker.patch(
            "app.tasks.routes.dispatch_queue_item",
            side_effect=_fake_dispatch_queue_item,
        )

        response = test_client.post(
            f"/execute/{conn_task.name}",
            json={"meta": {"target": "node1"}},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_check.assert_awaited_once()
        kwargs = mock_check.await_args.kwargs
        assert kwargs["target"] == "node1"
        assert kwargs["host"] == CONNECTIVITY_META["_connectivity_host"]
        assert kwargs["port"] == int(CONNECTIVITY_META["_connectivity_port"])
        assert kwargs["service_type"] == ConnectivityServiceType(
            CONNECTIVITY_META["_connectivity_service_type"]
        )
        mock_dispatch.assert_called_once()

    @pytest.mark.asyncio
    async def test_failure_warn_logs_and_dispatches(
        self, test_client, mocker, conn_task, mock_executor
    ):
        """Verify failure from ``check_connectivity_with_cache`` in warn mode logs and proceeds."""
        mocker.patch(
            "app.tasks.routes.tasks_settings.PRE_EXECUTION_CONNECTIVITY_CHECK",
            PreExecutionCheckMode.WARN,
        )
        mocker.patch(
            "app.tasks.routes.get_executor_for_task",
            return_value=mock_executor,
        )
        mocker.patch(
            "app.tasks.routes.check_connectivity_with_cache",
            new=AsyncMock(return_value=(False, "Connection refused")),
        )
        mock_dispatch = mocker.patch(
            "app.tasks.routes.dispatch_queue_item",
            side_effect=_fake_dispatch_queue_item,
        )
        mock_logger = mocker.patch("app.tasks.routes.logger")

        response = test_client.post(
            f"/execute/{conn_task.name}",
            json={"meta": {"target": "node1"}},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_dispatch.assert_called_once()
        mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_failure_block_returns_400(
        self, test_client, mocker, conn_task, mock_executor
    ):
        """Verify failure from ``check_connectivity_with_cache`` in block mode returns 400."""
        mocker.patch(
            "app.tasks.routes.tasks_settings.PRE_EXECUTION_CONNECTIVITY_CHECK",
            PreExecutionCheckMode.BLOCK,
        )
        mocker.patch(
            "app.tasks.routes.get_executor_for_task",
            return_value=mock_executor,
        )
        mocker.patch(
            "app.tasks.routes.check_connectivity_with_cache",
            new=AsyncMock(return_value=(False, "Connection refused")),
        )
        mock_dispatch = mocker.patch(
            "app.tasks.routes.dispatch_queue_item",
            new=AsyncMock(),
        )

        response = test_client.post(
            f"/execute/{conn_task.name}",
            json={"meta": {"target": "node1"}},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_eta_task_skips_check(
        self, test_client, mocker, conn_task, mock_executor
    ):
        """Verify check is skipped for ETA-scheduled tasks regardless of mode."""
        mocker.patch(
            "app.tasks.routes.tasks_settings.PRE_EXECUTION_CONNECTIVITY_CHECK",
            PreExecutionCheckMode.BLOCK,
        )
        mocker.patch(
            "app.tasks.routes.get_executor_for_task",
            return_value=mock_executor,
        )
        mock_check = mocker.patch("app.tasks.routes.check_connectivity_with_cache")
        mocker.patch(
            "app.tasks.routes.execute_task_queue.apply_async",
            return_value=MagicMock(id="celery-123"),
        )

        eta = utc_now()
        response = test_client.post(
            f"/execute/{conn_task.name}",
            json={"meta": {"target": "node1"}, "eta": eta.isoformat()},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_check.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("bad_meta_override", "case_label"),
        [
            ({"_connectivity_port": "not-a-number"}, "invalid-port"),
            ({"_connectivity_service_type": "bogus-service"}, "invalid-service-type"),
        ],
    )
    async def test_malformed_meta_skips_check_and_dispatches(
        self,
        test_client,
        session,
        mocker,
        mock_executor,
        bad_meta_override,
        case_label,
    ):
        """Verify malformed connectivity meta is logged and dispatch proceeds.

        Regression guard: ``int(conn_port)`` and ``ConnectivityServiceType(conn_type)``
        must not raise ``ValueError`` out to the caller — the route should log a
        warning, skip the check, and dispatch normally even under ``block`` mode.
        """
        bad_meta = {**CONNECTIVITY_META, **bad_meta_override}
        task = await TaskManager.create(
            session,
            TaskWrite.model_validate(
                TaskFactory.build(
                    name=f"bad-meta-task-{case_label}",
                    data={"Meta": bad_meta},
                )
            ),
        )

        mocker.patch(
            "app.tasks.routes.tasks_settings.PRE_EXECUTION_CONNECTIVITY_CHECK",
            PreExecutionCheckMode.BLOCK,
        )
        mocker.patch(
            "app.tasks.routes.get_executor_for_task",
            return_value=mock_executor,
        )
        mock_check = mocker.patch("app.tasks.routes.check_connectivity_with_cache")
        mock_dispatch = mocker.patch(
            "app.tasks.routes.dispatch_queue_item",
            side_effect=_fake_dispatch_queue_item,
        )
        mock_logger = mocker.patch("app.tasks.routes.logger")

        response = test_client.post(
            f"/execute/{task.name}",
            json={"meta": {"target": "node1"}},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_check.assert_not_called()
        mock_dispatch.assert_called_once()
        assert any(
            "malformed connectivity metadata" in call.args[0]
            for call in mock_logger.warning.call_args_list
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "missing_field",
        ["_connectivity_host", "_connectivity_port", "_connectivity_service_type"],
    )
    @pytest.mark.parametrize("empty_value", [None, ""])
    async def test_partial_connectivity_meta_skips_check(
        self,
        test_client,
        session,
        mocker,
        mock_executor,
        missing_field,
        empty_value,
    ):
        """Verify check is skipped when any connectivity meta field is empty or None.

        Regression guard: the truthy short-circuit in ``execute_task_name`` is the
        only defense against half-populated task definitions. If a refactor ever
        replaces ``and conn_host`` with ``and conn_host is not None`` the empty
        string case silently breaks.
        """
        partial_meta = {**CONNECTIVITY_META, missing_field: empty_value}
        task = await TaskManager.create(
            session,
            TaskWrite.model_validate(
                TaskFactory.build(
                    name=f"partial-meta-task-{missing_field}-{empty_value!r}",
                    data={"Meta": partial_meta},
                )
            ),
        )

        mocker.patch(
            "app.tasks.routes.tasks_settings.PRE_EXECUTION_CONNECTIVITY_CHECK",
            PreExecutionCheckMode.BLOCK,
        )
        mocker.patch(
            "app.tasks.routes.get_executor_for_task",
            return_value=mock_executor,
        )
        mock_check = mocker.patch("app.tasks.routes.check_connectivity_with_cache")
        mock_dispatch = mocker.patch(
            "app.tasks.routes.dispatch_queue_item",
            side_effect=_fake_dispatch_queue_item,
        )

        response = test_client.post(
            f"/execute/{task.name}",
            json={"meta": {"target": "node1"}},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_check.assert_not_called()
        mock_dispatch.assert_called_once()


@pytest.mark.asyncio
class TestSyncTaskHistoryRealSession:
    """Integration coverage for POST /history/{id}/sync/ with a real session.

    Regression for SEP-1035: a real HTTP POST must open a fresh writer
    session, forward it to executor.sync_task_history, and let the Nomad
    executor's _persist_nomad_task_logs append chunks to taskhistory_log.
    """

    async def test_sync_running_persists_logs_via_writer_session(
        self,
        regular_user,
        session: AsyncSession,
        mock_executor: AsyncMock,
    ):
        """Verify the sync route drives log persistence through writer_session."""
        test_session_maker = get_async_session_maker_from_engine(session.bind)

        task = await TaskManager.create(
            session,
            TaskWrite.model_validate(
                TaskFactory.build(
                    name="run-python",
                    backend=TaskBackendEnum.NOMAD,
                    is_template=False,
                    protected=False,
                    alert_on_fail=False,
                )
            ),
        )
        history = TaskHistory(
            task_id=task.id,
            task=task,
            execution_request=TaskExecutionRequest(
                task=task.name,
                target="node1",
                meta={"target": "node1"},
                tracking={"evaluation_id": "eval-1", "allocation_id": "alloc-1"},
            ),
            status=TaskHistoryStatusEnum.RUNNING,
            executed_by="test-user",
        )
        saved_history = await TaskHistoryManager.save(session, history)

        stdout_bytes = b"fresh stdout chunk"

        async def fake_sync(
            queue_item: TaskHistory,
            writer_session: AsyncSession | None = None,
        ) -> TaskHistory:
            assert writer_session is not None
            await TaskHistoryLogWriter.append(
                writer_session,
                queue_item.id,
                source="run-script",
                stream=TaskLogType.STDOUT,
                new_bytes=stdout_bytes,
                force_flush=True,
                producer_offset_after=len(stdout_bytes),
            )
            queue_item.status = TaskHistoryStatusEnum.SUCCESS
            queue_item.finished_at = utc_now()
            return queue_item

        mock_executor.sync_task_history = AsyncMock(side_effect=fake_sync)

        tasks_app.dependency_overrides[get_current_user] = lambda: regular_user
        tasks_app.dependency_overrides[get_session] = lambda: session
        tasks_app.dependency_overrides[get_executor] = lambda: mock_executor

        try:
            with patch(
                "app.tasks.routes.get_async_session_maker",
                return_value=test_session_maker,
            ):
                transport = ASGITransport(app=tasks_app)
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    response = await client.post(f"/history/{saved_history.id}/sync/")
        finally:
            tasks_app.dependency_overrides = {}

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == TaskHistoryStatusEnum.SUCCESS.value
        mock_executor.sync_task_history.assert_awaited_once()
        call_kwargs = mock_executor.sync_task_history.await_args.kwargs
        assert "writer_session" in call_kwargs
        assert call_kwargs["writer_session"] is not None
        assert await TaskHistoryLogManager.exists_for_task(session, saved_history.id)
