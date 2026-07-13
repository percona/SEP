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

"""Define tests for the app.sep.apps.checksums.routes module."""

from unittest.mock import AsyncMock

import pytest
from fastapi import status

from app.inventory.models import ServiceTypeEnum
from app.sep.apps.checksums.deps import (
    build_checksums_task_payload,
    get_checksums_index_context,
    get_checksums_task,
)
from app.sep.apps.checksums.models import ChecksumsCreate
from app.sep.connectivity import (
    clear_connectivity_caches,
    get_latest_connectivity_result,
)
from app.sep.main import sep_app
from app.tasks.models import TaskBackendEnum
from tests.app.factories import (
    CreatedNodeFactory,
    CreatedServiceFactory,
    GeneratedTaskFactory,
    TaskFactory,
)


@pytest.fixture
def checksums_create():
    """Define a sample ChecksumsCreate form data."""
    return ChecksumsCreate(
        task_name="fake_checksum",
        hostname="localhost",
        service_id=1,
        recursion_method="processlist",
    )


def test_checksums_create_full_form_dependency_chain_without_payload_override(
    test_client,
    mock_task_api_dep,
    mock_inventory_api_dep,
    created_service,
):
    """Test POST /checksums/ route without overriding build_checksums_task_payload."""
    checksums_create = ChecksumsCreate(
        task_name="chk_full_chain",
        hostname="localhost",
        service_id=created_service.id,
        recursion_method="processlist",
    )
    mock_inventory_api_dep.get = AsyncMock(return_value=created_service.model_dump())
    mock_task_api_dep.post.return_value = AsyncMock()

    response = test_client.post(
        "/checksums/",
        data=checksums_create.model_dump(exclude_none=True),
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"].endswith("/checksums/chk_full_chain")
    mock_task_api_dep.post.assert_awaited_once()
    posted = mock_task_api_dep.post.await_args.kwargs["json"]
    assert posted["name"] == "chk_full_chain"
    assert posted["owner"] == "CHECKSUMS"


class TestChecksumsUpdateFormChain:
    """Exercise the real ``Form()`` dependency chain on POST /checksums/{task_name}/update."""

    def test_full_form_dependency_chain_without_payload_override(
        self,
        test_client,
        mock_task_api_dep,
        mock_inventory_api_dep,
        created_service,
    ):
        """Forward the submitted body to ``tasks_api.put`` through the real form chain."""
        task_name = "chk_update_full_chain"
        checksums_create = ChecksumsCreate(
            task_name=task_name,
            hostname="localhost",
            service_id=created_service.id,
            recursion_method="processlist",
        )
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        mock_task_api_dep.put.return_value = AsyncMock()

        response = test_client.post(
            f"/checksums/{task_name}/update",
            data=checksums_create.model_dump(exclude_none=True),
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"].endswith(f"/checksums/{task_name}")
        mock_task_api_dep.put.assert_awaited_once()
        assert mock_task_api_dep.put.await_args.args[0] == f"/{task_name}"
        put_payload = mock_task_api_dep.put.await_args.kwargs["json"]
        assert put_payload["name"] == task_name
        assert put_payload["owner"] == "CHECKSUMS"
        # Submitted ``recursion_method`` must survive the real form chain into the args.
        assert "--recursion-method=processlist" in put_payload["data"]["meta"]["args"]

    def test_forwards_path_name_but_redirects_to_form_name(
        self,
        test_client,
        mock_task_api_dep,
        mock_inventory_api_dep,
        created_service,
    ):
        """Forward the path ``task_name`` to put while the form name drives the redirect."""
        path_name = "chk_url_path"
        form_name = "chk_form_name"
        checksums_create = ChecksumsCreate(
            task_name=form_name,
            hostname="localhost",
            service_id=created_service.id,
            recursion_method="processlist",
        )
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        mock_task_api_dep.put.return_value = AsyncMock()

        response = test_client.post(
            f"/checksums/{path_name}/update",
            data=checksums_create.model_dump(exclude_none=True),
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert mock_task_api_dep.put.await_args.args[0] == f"/{path_name}"
        assert mock_task_api_dep.put.await_args.kwargs["json"]["name"] == form_name
        assert response.headers["location"].endswith(f"/checksums/{form_name}")

    def test_invalid_form_flashes_and_redirects_without_forwarding(
        self,
        test_client,
        mock_task_api_dep,
        mock_inventory_api_dep,
        created_service,
    ):
        """Flash and redirect (never forward) when the update form fails validation."""
        data = {
            "task_name": "chk_invalid",
            "hostname": "localhost",
            "service_id": created_service.id,
            # recursion_method intentionally omitted
        }
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )

        response = test_client.post(
            "/checksums/chk_invalid/update", data=data, follow_redirects=False
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/"
        assert "messages=" in response.headers.get("set-cookie", "")
        mock_task_api_dep.put.assert_not_awaited()


def test_checksums_create_skips_connectivity_check_when_opted_out(
    test_client, mock_task_api_dep, checksums_create
):
    """POST /checksums/ skips the connectivity check when the checkbox is unchecked."""
    clear_connectivity_caches()

    fake_task_write = GeneratedTaskFactory.build(
        name="fake_checksum",
        backend=TaskBackendEnum.PROXY,
        owner="CHECKSUMS",
        data={
            "task": "run-command",
            "meta": {
                "command": "pt-table-checksum",
                "args": "--recursion-method=processlist",
                "target": "node1",
                "_connectivity_host": "10.0.0.1",
                "_connectivity_port": 3306,
                "_connectivity_service_type": ServiceTypeEnum.MYSQL.value,
            },
        },
    )

    sep_app.dependency_overrides[build_checksums_task_payload] = lambda: fake_task_write

    response = test_client.post(
        "/checksums/", data=checksums_create.model_dump(), follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert (
        response.headers["location"]
        == f"{test_client.base_url}/checksums/{checksums_create.task_name}"
    )

    assert mock_task_api_dep.post.call_count == 1
    call = mock_task_api_dep.post.call_args_list[0]
    assert call.args[0] == "/"
    assert call.kwargs["json"] == fake_task_write.model_dump()
    assert get_latest_connectivity_result("node1", "mysql") is None

    clear_connectivity_caches()
    sep_app.dependency_overrides = {}


def _deterministic_mysql_service():
    """Build a MySQL service with a fixed host/port for byte-exact arg assertions."""
    return CreatedServiceFactory.build(
        node=CreatedNodeFactory.build(address="db-host"),
        type=ServiceTypeEnum.MYSQL,
        name="svc",
        port=3306,
    )


def test_legacy_create_assembles_exact_args(
    test_client, mock_task_api_dep, mock_inventory_api_dep
):
    """Assert POST /checksums/ (form) assembles the byte-exact pt-table-checksum args."""
    service = _deterministic_mysql_service()
    mock_inventory_api_dep.get = AsyncMock(return_value=service.model_dump())
    mock_task_api_dep.post.return_value = AsyncMock()

    response = test_client.post(
        "/checksums/",
        data={
            "task_name": "chk-legacy",
            "hostname": "exec-node",
            "service_id": service.id,
            "recursion_method": "processlist",
            "databases": "db1",
        },
        follow_redirects=False,
    )

    assert response.status_code == status.HTTP_303_SEE_OTHER
    posted = mock_task_api_dep.post.await_args.kwargs["json"]
    assert posted["data"]["meta"]["args"] == (
        "h=db-host,P=3306, --recursion-method=processlist --databases=db1"
    )


def test_legacy_update_assembles_exact_args(
    test_client, mock_task_api_dep, mock_inventory_api_dep
):
    """Assert POST /checksums/{task_name}/update (form) reuses the byte-exact args."""
    service = _deterministic_mysql_service()
    mock_inventory_api_dep.get = AsyncMock(return_value=service.model_dump())
    mock_task_api_dep.put.return_value = AsyncMock()

    response = test_client.post(
        "/checksums/chk-legacy/update",
        data={
            "task_name": "chk-legacy",
            "hostname": "exec-node",
            "service_id": service.id,
            "recursion_method": "hosts",
            "tables": "db.t1",
        },
        follow_redirects=False,
    )

    assert response.status_code == status.HTTP_303_SEE_OTHER
    put_json = mock_task_api_dep.put.await_args.kwargs["json"]
    assert put_json["data"]["meta"]["args"] == (
        "h=db-host,P=3306, --recursion-method=hosts --tables=db.t1"
    )


@pytest.fixture
def created_checksums_task():
    """Return a fake Checksums task with renderable detail-page data."""
    return TaskFactory.build(
        owner="CHECKSUMS",
        data={
            "meta": {
                "command": "pt-table-checksum",
                "args": "h=localhost,P=3306",
                "target": "localhost",
            }
        },
    )


@pytest.fixture
def _mock_get_checksums_task_dep(created_checksums_task):
    """Mock the checksums task dependency with a built task."""
    sep_app.dependency_overrides[get_checksums_task] = lambda: created_checksums_task
    yield
    sep_app.dependency_overrides = {}


@pytest.mark.usefixtures("_mock_get_checksums_task_dep", "mock_get_username_mapping")
def test_checksums_detail_uses_own_delete_route(
    test_client, mock_task_api_dep, mock_inventory_api_dep, created_checksums_task
):
    """Assert checksums_detail renders its own delete route, not tasks_delete.

    Regression guard: the shared ``run-python-form`` partial dropped its
    ``tasks_delete`` fallback, so the rendered delete form must point at the
    owner's ``checksums_delete`` URL carried on ``task.delete_url``.
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
    mock_inventory_api_dep.get = AsyncMock(
        return_value={"items": [], "total": 0, "offset": 0, "limit": 50}
    )

    response = test_client.get(f"/checksums/{created_checksums_task.name}")

    assert response.status_code == status.HTTP_200_OK
    assert f"/checksums/{created_checksums_task.name}/delete" in response.text
    assert f"/tasks/{created_checksums_task.name}/delete" not in response.text


@pytest.fixture
def _mock_get_checksums_index_context_dep():
    """Mock the get_checksums_index_context dependency with a stub context."""
    sep_app.dependency_overrides[get_checksums_index_context] = lambda: {
        "user": "default_user",
    }
    yield
    sep_app.dependency_overrides = {}


@pytest.mark.usefixtures("_mock_get_checksums_index_context_dep")
def test_checksums_index(test_client):
    """GET /checksums/ renders the index via the relocated ChecksumsIndexContext alias."""
    response = test_client.get("/checksums/")

    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "text/html; charset=utf-8"
