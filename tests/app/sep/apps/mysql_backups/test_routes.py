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

"""Define tests for the app.sep.apps.mysql_backups.routes module."""

from unittest.mock import AsyncMock

import pytest
import yaml
from fastapi import status

from app.inventory.models import ServiceTypeEnum
from app.sep.apps.mysql_backups.deps import (
    build_backup_task_payload,
    get_backups_index_context,
    get_backups_task,
)
from app.sep.apps.mysql_backups.models import (
    BackupCreate,
    BackupType,
    UploadProvider,
)
from app.sep.connectivity import (
    CHECK_TIMEOUT,
    clear_connectivity_caches,
    get_latest_connectivity_result,
)
from app.sep.main import sep_app
from app.tasks.models import (
    TaskBackendEnum,
    TaskHistoryStatusEnum,
)
from tests.app.factories import GeneratedTaskFactory, TaskFactory


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
        upload=[UploadProvider.S3],
        s3_bucket="test-bucket",
    )


@pytest.fixture
def created_task():
    """Return a fake created Task instance."""
    return TaskFactory.build(
        owner="BACKUPS",
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
    response = test_client.get("/mysql_backups/")
    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert "<title>Backups — Services Enablement Platform</title>" in response.text


def test_backups_create(test_client, mock_task_api_dep, backup_create):
    """Test POST /backups/ route."""
    fake_task_write = GeneratedTaskFactory.build(
        name="fake_task",
        backend=TaskBackendEnum.PROXY,
        owner="BACKUPS",
        data={"task": "fake-task", "meta": {}, "payload": ""},
    )

    sep_app.dependency_overrides[build_backup_task_payload] = lambda: fake_task_write

    response = test_client.post(
        "/mysql_backups/", data=backup_create.model_dump(), follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert (
        response.headers["location"]
        == f"{test_client.base_url}/mysql_backups/{backup_create.task_name}"
    )

    mock_task_api_dep.post.assert_called_once()
    called_args, called_kwargs = mock_task_api_dep.post.call_args
    assert called_args[0] == "/"
    assert called_kwargs["json"] == fake_task_write.model_dump()

    sep_app.dependency_overrides = {}


def test_backups_create_no_upload(
    test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
):
    """Assert POST /backups/ with no upload provider succeeds (upload is optional).

    Exercises the real ``build_backup_task_payload`` dependency (no override) so the
    ``BackupCreate`` validation this PR relaxes is actually run: omitting ``upload``
    from the form must not 422.
    """
    no_upload = BackupCreate(
        task_name="fake_task",
        hostname="localhost",
        service_id=created_service.id,
        backup_type=BackupType.MYDUMPER,
        upload=[],
    )
    mock_inventory_api_dep.get = AsyncMock(return_value=created_service.model_dump())
    mock_task_api_dep.post.return_value = AsyncMock()

    response = test_client.post(
        "/mysql_backups/",
        data=no_upload.model_dump(exclude={"upload"}),
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"].endswith(
        f"/mysql_backups/{no_upload.task_name}"
    )
    mock_task_api_dep.post.assert_awaited_once()
    assert mock_task_api_dep.post.await_args.args[0] == "/"
    posted = mock_task_api_dep.post.await_args.kwargs["json"]
    assert posted["name"] == no_upload.task_name
    assert posted["owner"] == "BACKUPS"


def test_backups_create_full_form_dependency_chain_without_payload_override(
    test_client,
    mock_task_api_dep,
    mock_inventory_api_dep,
    backup_create,
    created_service,
):
    """Test POST /backups/ route without overriding build_backup_task_payload."""
    backup_create.service_id = created_service.id
    mock_inventory_api_dep.get = AsyncMock(return_value=created_service.model_dump())
    mock_task_api_dep.post.return_value = AsyncMock()

    response = test_client.post(
        "/mysql_backups/",
        data=backup_create.model_dump(),
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"].endswith(
        f"/mysql_backups/{backup_create.task_name}"
    )
    mock_task_api_dep.post.assert_awaited_once()
    assert mock_task_api_dep.post.await_args.args[0] == "/"
    posted = mock_task_api_dep.post.await_args.kwargs["json"]
    assert posted["name"] == backup_create.task_name
    assert posted["owner"] == "BACKUPS"
    assert posted["data"]["meta"]["_service_name"] == created_service.name


class TestBackupsUpdateFormChain:
    """Exercise the real ``Form()`` dependency chain on POST /mysql_backups/{task_name}/update."""

    def test_full_form_dependency_chain_without_payload_override(
        self,
        test_client,
        mock_task_api_dep,
        mock_inventory_api_dep,
        backup_create,
        created_service,
    ):
        """Forward the submitted body to ``tasks_api.put`` through the real form chain."""
        backup_create.service_id = created_service.id
        task_name = backup_create.task_name
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        mock_task_api_dep.put.return_value = AsyncMock()

        response = test_client.post(
            f"/mysql_backups/{task_name}/update",
            data=backup_create.model_dump(),
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"].endswith(f"/mysql_backups/{task_name}")
        mock_task_api_dep.put.assert_awaited_once()
        assert mock_task_api_dep.put.await_args.args[0] == f"/{task_name}"
        put_payload = mock_task_api_dep.put.await_args.kwargs["json"]
        assert put_payload["name"] == task_name
        assert put_payload["owner"] == "BACKUPS"
        assert put_payload["data"]["meta"]["_service_name"] == created_service.name
        # Submitted ``backup_type`` must survive the real form chain into the YAML config.
        server_config = yaml.safe_load(put_payload["data"]["meta"]["config"])[
            "SERVER_LIST"
        ][0]
        assert server_config["BACKUP_TYPE"] == BackupType.MYDUMPER.value

    def test_forwards_path_name_but_redirects_to_form_name(
        self,
        test_client,
        mock_task_api_dep,
        mock_inventory_api_dep,
        created_service,
    ):
        """Forward the path ``task_name`` to put while the form name drives the redirect."""
        path_name = "backup_url_path"
        form_name = "backup_form_name"
        form = BackupCreate(
            task_name=form_name,
            hostname="localhost",
            service_id=created_service.id,
            backup_type=BackupType.MYDUMPER,
        )
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        mock_task_api_dep.put.return_value = AsyncMock()

        response = test_client.post(
            f"/mysql_backups/{path_name}/update",
            data=form.model_dump(),
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert mock_task_api_dep.put.await_args.args[0] == f"/{path_name}"
        assert mock_task_api_dep.put.await_args.kwargs["json"]["name"] == form_name
        assert response.headers["location"].endswith(f"/mysql_backups/{form_name}")

    def test_invalid_form_flashes_and_redirects_without_forwarding(
        self,
        test_client,
        mock_task_api_dep,
        mock_inventory_api_dep,
        created_service,
    ):
        """Flash and redirect (never forward) when the update form fails validation."""
        data = {
            "task_name": "backup_invalid",
            "hostname": "localhost",
            "service_id": created_service.id,
            # backup_type intentionally omitted
        }
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )

        response = test_client.post(
            "/mysql_backups/backup_invalid/update", data=data, follow_redirects=False
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/"
        assert "messages=" in response.headers.get("set-cookie", "")
        mock_task_api_dep.put.assert_not_awaited()


EXPECTED_CONNECTIVITY_POST_CALLS = 2


def test_backups_create_triggers_connectivity_check(
    test_client, mock_task_api_dep, backup_create
):
    """POST /backups/ runs a connectivity check when meta carries connectivity data."""
    clear_connectivity_caches()

    fake_task_write = GeneratedTaskFactory.build(
        name="fake_task",
        backend=TaskBackendEnum.PROXY,
        owner="BACKUPS",
        data={
            "task": "fake-task",
            "meta": {
                "target": "node1",
                "_connectivity_host": "10.0.0.1",
                "_connectivity_port": 3306,
                "_connectivity_service_type": ServiceTypeEnum.MYSQL.value,
            },
            "payload": "",
        },
    )

    sep_app.dependency_overrides[build_backup_task_payload] = lambda: fake_task_write

    mock_task_api_dep.post.side_effect = [
        None,
        {"success": True, "error": None},
    ]

    response = test_client.post(
        "/mysql_backups/",
        data={**backup_create.model_dump(), "check_connectivity": "true"},
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert (
        response.headers["location"]
        == f"{test_client.base_url}/mysql_backups/{backup_create.task_name}"
    )

    assert mock_task_api_dep.post.call_count == EXPECTED_CONNECTIVITY_POST_CALLS
    first_call, second_call = mock_task_api_dep.post.call_args_list
    assert first_call.args[0] == "/"
    assert first_call.kwargs["json"] == fake_task_write.model_dump()
    assert second_call.args[0] == "/connectivity-check/"
    assert second_call.kwargs["json"] == {
        "target": "node1",
        "host": "10.0.0.1",
        "port": 3306,
        "service_type": "mysql",
        "timeout": CHECK_TIMEOUT,
    }

    clear_connectivity_caches()
    sep_app.dependency_overrides = {}


def test_backups_create_skips_connectivity_check_when_opted_out(
    test_client, mock_task_api_dep, backup_create
):
    """POST /backups/ skips the connectivity check when the checkbox is unchecked."""
    clear_connectivity_caches()

    fake_task_write = GeneratedTaskFactory.build(
        name="fake_task",
        backend=TaskBackendEnum.PROXY,
        owner="BACKUPS",
        data={
            "task": "fake-task",
            "meta": {
                "target": "node1",
                "_connectivity_host": "10.0.0.1",
                "_connectivity_port": 3306,
                "_connectivity_service_type": ServiceTypeEnum.MYSQL.value,
            },
            "payload": "",
        },
    )

    sep_app.dependency_overrides[build_backup_task_payload] = lambda: fake_task_write

    response = test_client.post(
        "/mysql_backups/", data=backup_create.model_dump(), follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert (
        response.headers["location"]
        == f"{test_client.base_url}/mysql_backups/{backup_create.task_name}"
    )

    assert mock_task_api_dep.post.call_count == 1
    call = mock_task_api_dep.post.call_args_list[0]
    assert call.args[0] == "/"
    assert call.kwargs["json"] == fake_task_write.model_dump()
    assert get_latest_connectivity_result("node1", "mysql") is None

    clear_connectivity_caches()
    sep_app.dependency_overrides = {}


@pytest.mark.usefixtures("_mock_get_backups_task_dep", "mock_get_username_mapping")
def test_backups_detail(
    test_client, mock_task_api_dep, mock_inventory_api_dep, created_task
):
    """Test GET /backups/{task_name} route."""
    mock_task_api_dep.get = AsyncMock(
        side_effect=[
            {},  # /hosts/
            {"items": [], "total": 0, "offset": 0, "limit": 50},  # history
            {"items": [], "total": 0, "offset": 0, "limit": 50},  # running_tasks
            [],  # stats
            {"items": [], "total": 0, "offset": 0, "limit": 50},  # chainable_tasks
        ]
    )
    mock_inventory_api_dep.get.return_value = {
        "items": [],
        "total": 0,
        "offset": 0,
        "limit": 50,
    }
    response = test_client.get(f"/mysql_backups/{created_task.name}")
    assert response.status_code == status.HTTP_200_OK
    assert (
        f"<title>Backups - {created_task.name} — Services Enablement Platform</title>"
        in response.text
    )
    assert f"/mysql_backups/{created_task.name}/delete" in response.text
    assert f"/tasks/{created_task.name}/delete" not in response.text

    mock_task_api_dep.get.assert_any_call(f"/{created_task.name}/history/")
    mock_task_api_dep.get.assert_any_call(
        f"/{created_task.name}/history/",
        params={"status": TaskHistoryStatusEnum.RUNNING},
    )
    mock_task_api_dep.get.assert_any_call(f"/stats/{created_task.name}")


@pytest.mark.usefixtures("_mock_get_backups_task_dep", "mock_get_username_mapping")
def test_backups_detail_renders_backup_configuration(
    test_client, mock_task_api_dep, mock_inventory_api_dep, created_task
):
    """Render the detail_view: executor target + YAML config on the detail page.

    The always-rendered "Task information" card shows the list columns; the
    detail_view must surface the config that is *not* a column — the executor
    target (``data.meta.target``) and the YAML config (``data.meta.config``).
    """
    mock_task_api_dep.get = AsyncMock(
        side_effect=[
            {},  # /hosts/
            {"items": [], "total": 0, "offset": 0, "limit": 50},  # history
            {"items": [], "total": 0, "offset": 0, "limit": 50},  # running_tasks
            [],  # stats
            {"items": [], "total": 0, "offset": 0, "limit": 50},  # chainable_tasks
        ]
    )
    mock_inventory_api_dep.get.return_value = {
        "items": [],
        "total": 0,
        "offset": 0,
        "limit": 50,
    }
    response = test_client.get(f"/mysql_backups/{created_task.name}")
    assert response.status_code == status.HTTP_200_OK
    assert "Backup Configuration" in response.text
    assert "Executor Host" in response.text
    assert created_task.data["meta"]["target"] in response.text
    assert "SERVER_LIST" in response.text


@pytest.mark.parametrize(
    ("form_data", "expected_json"),
    [
        (
            {},
            {"eta": None, "chain_task_names": None, "chain_on_failure": None},
        ),
        (
            {"chain_task_names": ["task-a", "task-b"]},
            {
                "eta": None,
                "chain_task_names": ["task-a", "task-b"],
                "chain_on_failure": None,
            },
        ),
    ],
    ids=["no_chain", "with_chain"],
)
@pytest.mark.usefixtures(
    "_mock_get_backups_task_dep", "_mock_check_for_conflicted_running_tasks"
)
def test_backups_execute(
    test_client, mock_task_api_dep, created_task, form_data, expected_json
):
    """Test POST /mysql_backups/{task_name} forwards the form payload to the tasks API."""
    response = test_client.post(
        f"/mysql_backups/{created_task.name}",
        data=form_data,
        follow_redirects=False,
    )

    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert (
        response.headers["location"]
        == f"{test_client.base_url}/mysql_backups/{created_task.name}"
    )

    mock_task_api_dep.post.assert_called_once()
    called_args, called_kwargs = mock_task_api_dep.post.call_args
    assert called_args[0] == f"/execute/{created_task.name}"
    assert called_kwargs["json"] == expected_json


@pytest.mark.usefixtures("_mock_get_backups_task_dep")
def test_backups_delete(test_client, mock_task_api_dep, created_task):
    """Test POST /backups/{task_name}/delete route."""
    response = test_client.post(
        f"/mysql_backups/{created_task.name}/delete", follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["Location"] == "/mysql_backups"

    mock_task_api_dep.delete.assert_called_once()
    called_args, called_kwargs = mock_task_api_dep.delete.call_args
    assert called_args[0] == f"/{created_task.name}"
