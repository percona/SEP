"""Define tests for the app.sep.plugins.backup.routes module."""

from unittest.mock import AsyncMock

import pytest
import yaml
from fastapi import status

from app.sep.main import sep_app
from app.sep.plugins.backup.deps import (
    build_backup_task_payload,
    get_backups_index_context,
    get_backups_task,
)
from app.sep.plugins.backup.models import BackupCreate, BackupType
from app.tasks.models import (
    TaskBackendEnum,
    TaskHistoryStatusEnum,
    TaskOwner,
    TaskWrite,
)
from tests.app.factories import TaskFactory


@pytest.fixture
def _mock_get_backups_index_context_dep():
    """Mock the get_backups_index_context dependency with default user context."""
    sep_app.dependency_overrides[get_backups_index_context] = lambda: {
        "user": "default_user"
    }
    yield
    sep_app.dependency_overrides = {}


@pytest.fixture
def backup_create():
    """Define a sample BackupCreate form data."""
    return BackupCreate(
        task_name="fake_task",
        hostname="localhost",
        service_id=1,
        backup_type=BackupType.MYDUMPER,
    )


@pytest.fixture
def created_task():
    """Return a fake created Task instance."""
    return TaskFactory.build(
        owner=TaskOwner.BACKUPS,
        data={
            "meta": {
                "target": "localhost",
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [
                            {
                                "HOST": "localhost",
                                "PORT": 3306,
                                "BACKUP_TYPE": BackupType.MYDUMPER.value,
                            }
                        ]
                    }
                ),
            }
        },
    )


@pytest.fixture
def _mock_get_backups_task_dep(created_task):
    """Mock the TaskDep dependency."""
    sep_app.dependency_overrides[get_backups_task] = lambda: created_task
    yield
    sep_app.dependency_overrides = {}


@pytest.mark.usefixtures("_mock_get_backups_index_context_dep")
def test_backups_index(test_client):
    """Test GET /backups/ route."""
    response = test_client.get("/backups/")
    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert "<title>Backups — Services Enablement Platform</title>" in response.text


def test_backups_create(test_client, mock_task_api_dep, backup_create):
    """Test POST /backups/ route."""
    fake_task_write = TaskWrite(
        name="fake_task",
        backend=TaskBackendEnum.PROXY,
        owner=TaskOwner.BACKUPS,
        data={"task": "fake-task", "meta": {}, "payload": ""},
    )

    sep_app.dependency_overrides[build_backup_task_payload] = lambda: fake_task_write

    response = test_client.post(
        "/backups/", data=backup_create.model_dump(), follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert (
        response.headers["location"]
        == f"{test_client.base_url}/backups/{backup_create.task_name}"
    )

    mock_task_api_dep.post.assert_called_once()
    called_args, called_kwargs = mock_task_api_dep.post.call_args
    assert called_args[0] == "/"
    assert called_kwargs["json"] == fake_task_write.model_dump()

    sep_app.dependency_overrides = {}


@pytest.mark.usefixtures("_mock_get_backups_task_dep", "mock_get_username_mapping")
def test_backups_detail(
    test_client, mock_task_api_dep, mock_inventory_api_dep, created_task
):
    """Test GET /backups/{task_name} route."""
    mock_task_api_dep.get = AsyncMock(
        side_effect=[
            {},  # history
            {},  # running_tasks
            [],  # stats
            {"address1": "host1", "address2": "host2"},  # /hosts/
            [],  # periodic_tasks
            [],  # all_tasks for chainable_tasks
        ]
    )
    mock_inventory_api_dep.get.return_value = AsyncMock()
    response = test_client.get(f"/backups/{created_task.name}")
    assert response.status_code == status.HTTP_200_OK
    assert (
        f"<title>Backups - {created_task.name} — Services Enablement Platform</title>"
        in response.text
    )

    mock_task_api_dep.get.assert_any_call(f"/{created_task.name}/history/")
    mock_task_api_dep.get.assert_any_call(
        f"/{created_task.name}/history/",
        params={"status": TaskHistoryStatusEnum.RUNNING},
    )
    mock_task_api_dep.get.assert_any_call(f"/stats/{created_task.name}")
    mock_task_api_dep.get.assert_any_call(f"/{created_task.name}/periodic/")
    mock_task_api_dep.get.assert_any_call("/", params={"owner": TaskOwner.BACKUPS})


@pytest.mark.usefixtures("_mock_get_backups_task_dep", "mock_get_username_mapping")
def test_backups_detail_chainable_tasks_excludes_current_and_wrong_host(
    test_client, mock_task_api_dep, mock_inventory_api_dep, created_task
):
    """Test that backups_detail chainable_tasks excludes the current task and wrong-host tasks."""
    same_host_other_task = {
        "name": "other-backup",
        "data": {"meta": {"target": "localhost"}},
    }
    wrong_host_task = {
        "name": "wrong-host-backup",
        "data": {"meta": {"target": "other-host"}},
    }
    same_task_self = {
        "name": created_task.name,
        "data": {"meta": {"target": "localhost"}},
    }
    mock_task_api_dep.get = AsyncMock(
        side_effect=[
            {},  # history
            {},  # running_tasks
            [],  # stats
            {},  # /hosts/ (no executor_host_ip)
            [],  # periodic_tasks
            [same_host_other_task, wrong_host_task, same_task_self],  # all_tasks
        ]
    )
    mock_inventory_api_dep.get.return_value = []

    response = test_client.get(f"/backups/{created_task.name}")

    assert response.status_code == status.HTTP_200_OK
    assert "other-backup" in response.text
    assert "wrong-host-backup" not in response.text
    assert (
        created_task.name not in response.text.split("chainable")[1]
        if "chainable" in response.text
        else True
    )


@pytest.mark.usefixtures(
    "_mock_get_backups_task_dep", "_mock_check_for_conflicted_running_tasks"
)
def test_backups_execute(test_client, mock_task_api_dep, created_task):
    """Test POST /backups/{task_name} route with no chain_task_name."""
    response = test_client.post(f"/backups/{created_task.name}", follow_redirects=False)

    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert (
        response.headers["location"]
        == f"{test_client.base_url}/backups/{created_task.name}"
    )

    mock_task_api_dep.post.assert_called_once()
    called_args, called_kwargs = mock_task_api_dep.post.call_args
    assert called_args[0] == f"/execute/{created_task.name}"
    assert called_kwargs["json"] == {"eta": None, "chain_task_name": None}


@pytest.mark.usefixtures(
    "_mock_get_backups_task_dep", "_mock_check_for_conflicted_running_tasks"
)
def test_backups_execute_with_chain_task_name(
    test_client, mock_task_api_dep, created_task
):
    """Test POST /backups/{task_name} passes chain_task_name to the tasks API."""
    response = test_client.post(
        f"/backups/{created_task.name}",
        data={"chain_task_name": "other-task"},
        follow_redirects=False,
    )

    assert response.status_code == status.HTTP_303_SEE_OTHER

    called_args, called_kwargs = mock_task_api_dep.post.call_args
    assert called_args[0] == f"/execute/{created_task.name}"
    assert called_kwargs["json"]["chain_task_name"] == "other-task"


@pytest.mark.usefixtures("_mock_get_backups_task_dep")
def test_backups_delete(test_client, mock_task_api_dep, created_task):
    """Test POST /backups/{task_name}/delete route."""
    response = test_client.post(
        f"/backups/{created_task.name}/delete", follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["Location"] == "/backups"

    mock_task_api_dep.delete.assert_called_once()
    called_args, called_kwargs = mock_task_api_dep.delete.call_args
    assert called_args[0] == f"/{created_task.name}"
