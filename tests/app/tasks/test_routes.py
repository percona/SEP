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

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import status

from app.core.utils import utc_now
from app.tasks.crud import TaskHistoryManager, TaskManager
from app.tasks.execution.executors.nomad.exceptions import AllocationNotFoundError
from app.tasks.execution.models import BaseExecutor
from app.tasks.models import (
    ExecutionEvent,
    Task,
    TaskHistoryStatusEnum,
    TaskWrite,
)
from tests.app.factories import TaskFactory

MOCK_FILE_SIZE = 1024


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
    assert [task["name"] for task in response.json()] == [created_task.name]

    await TaskManager.delete_by_name(session, created_task.name)

    response = test_client.get("/")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == []


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
    """Assert listing task history returns history records."""
    response = test_client.get("/history/")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == created_task_with_history.id


@pytest.mark.asyncio
async def test_list_task_history_filter_by_status(
    test_client, created_task_with_history
):
    """Assert filtering task history by status works."""
    response = test_client.get("/history/", params={"status": "success"})
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 1

    response = test_client.get("/history/", params={"status": "failed"})
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 0


@pytest.mark.asyncio
async def test_get_task_history_by_task_name(test_client, created_task_with_history):
    """Assert retrieving task history by task name returns matching records."""
    task_name = created_task_with_history.task.name
    response = test_client.get(f"/{task_name}/history/")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == created_task_with_history.id


@pytest.mark.asyncio
async def test_get_task_history_by_task_name_filter_by_status(
    test_client, created_task_with_history
):
    """Assert filtering task history by task name and status works."""
    task_name = created_task_with_history.task.name
    response = test_client.get(f"/{task_name}/history/", params={"status": "running"})
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 0


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

    async def fake_sync(item):
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
    """Assert retrieving executor hosts returns the expected hosts dict."""
    response = test_client.get("/hosts/")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"node1": "10.0.0.1"}


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
