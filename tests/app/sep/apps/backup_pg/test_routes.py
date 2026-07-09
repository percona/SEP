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

"""Define tests for the app.sep.apps.backup_pg.routes module."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status

from app.core.pagination import MAX_PAGINATION_LIMIT
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.backup_pg.deps import (
    build_backup_task_payload,
    get_backups_index_context,
)
from app.sep.connectivity import (
    clear_connectivity_caches,
    get_latest_connectivity_result,
)
from app.sep.main import sep_app
from app.tasks.models import (
    TaskBackendEnum,
    TaskHistoryStatusEnum,
)
from tests.app.factories import CreatedServiceFactory, GeneratedTaskFactory


@pytest.mark.usefixtures("_mock_get_backups_index_context_dep")
def test_backups_index(test_client):
    """Test GET /backup_pg/ route."""
    response = test_client.get("/backup_pg/")

    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert (
        "<title>PostgreSQL Backups — Services Enablement Platform</title>"
        in response.text
    )


def test_backups_create(
    test_client, mock_task_api_dep, backup_create, mock_build_backup_task_payload_dep
):
    """Test POST /backup_pg/ route."""
    response = test_client.post(
        "/backup_pg/", data=backup_create.model_dump(), follow_redirects=False
    )

    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert (
        response.headers["location"]
        == f"{test_client.base_url}/backup_pg/{backup_create.task_name}"
    )

    mock_task_api_dep.post.assert_called_once()
    called_args, called_kwargs = mock_task_api_dep.post.call_args
    assert called_args[0] == "/"
    assert called_kwargs["json"] == mock_build_backup_task_payload_dep.model_dump()


@pytest.mark.usefixtures("_mock_get_backups_index_context_dep")
def test_pg_backups_create_full_form_dependency_chain_without_payload_override(
    test_client,
    mock_task_api_dep,
    mock_inventory_api_dep,
    backup_create,
    created_node,
):
    """Test POST /backup_pg/ route without overriding build_backup_task_payload."""
    pg_service = CreatedServiceFactory.build(
        node=created_node, type=ServiceTypeEnum.POSTGRESQL
    )
    backup_create.service_id = pg_service.id
    mock_inventory_api_dep.get = AsyncMock(return_value=pg_service.model_dump())
    mock_task_api_dep.post.return_value = AsyncMock()

    response = test_client.post(
        "/backup_pg/",
        data=backup_create.model_dump(),
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"].endswith(
        f"/backup_pg/{backup_create.task_name}"
    )
    mock_task_api_dep.post.assert_awaited_once()
    assert mock_task_api_dep.post.await_args.args[0] == "/"
    posted = mock_task_api_dep.post.await_args.kwargs["json"]
    assert posted["name"] == backup_create.task_name
    assert posted["owner"] == "BACKUP_PG"
    assert posted["data"]["meta"]["_service_name"] == pg_service.name


def test_pg_backups_create_skips_connectivity_check_when_opted_out(
    test_client, mock_task_api_dep, backup_create
):
    """POST /backup_pg/ skips the connectivity check when the checkbox is unchecked."""
    clear_connectivity_caches()

    fake_task_write = GeneratedTaskFactory.build(
        name="fake_task",
        backend=TaskBackendEnum.PROXY,
        owner="BACKUP_PG",
        data={
            "task": "fake-task",
            "meta": {
                "target": "node1",
                "_connectivity_host": "10.0.0.1",
                "_connectivity_port": 5432,
                "_connectivity_service_type": ServiceTypeEnum.POSTGRESQL.value,
            },
            "payload": "",
        },
    )

    sep_app.dependency_overrides[build_backup_task_payload] = lambda: fake_task_write

    response = test_client.post(
        "/backup_pg/", data=backup_create.model_dump(), follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert (
        response.headers["location"]
        == f"{test_client.base_url}/backup_pg/{backup_create.task_name}"
    )

    assert mock_task_api_dep.post.call_count == 1
    call = mock_task_api_dep.post.call_args_list[0]
    assert call.args[0] == "/"
    assert call.kwargs["json"] == fake_task_write.model_dump()
    assert get_latest_connectivity_result("node1", "postgresql") is None

    clear_connectivity_caches()
    sep_app.dependency_overrides = {}


@pytest.mark.usefixtures("_mock_get_backups_task_dep", "mock_get_username_mapping")
def test_backups_detail(
    test_client, mock_task_api_dep, mock_inventory_api_dep, created_task
):
    """Test GET /backup_pg/{task_name} route."""
    mock_task_api_dep.get = AsyncMock(
        side_effect=[
            {},
            {"items": [], "total": 0, "offset": 0, "limit": 50},
            {"items": [], "total": 0, "offset": 0, "limit": 50},
            [],
            {"items": [], "total": 0, "offset": 0, "limit": 50},
        ]
    )
    mock_inventory_api_dep.get = AsyncMock(
        return_value={"items": [], "total": 0, "offset": 0, "limit": 50}
    )

    response = test_client.get(f"/backup_pg/{created_task.name}")

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


@pytest.mark.usefixtures("_mock_get_backups_task_dep", "mock_get_username_mapping")
def test_backups_detail_handles_inventory_error(
    test_client, mock_task_api_dep, mock_inventory_api_dep, created_task
):
    """Test detail route continues when inventory service lookup fails."""
    mock_task_api_dep.get = AsyncMock(
        side_effect=[
            {},
            {"items": [], "total": 0, "offset": 0, "limit": 50},
            {"items": [], "total": 0, "offset": 0, "limit": 50},
            [],
            {"items": [], "total": 0, "offset": 0, "limit": 50},
        ]
    )
    mock_inventory_api_dep.get = AsyncMock(
        side_effect=HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    )

    response = test_client.get(f"/backup_pg/{created_task.name}")

    assert response.status_code == status.HTTP_200_OK
    mock_inventory_api_dep.get.assert_any_call(
        "/services/",
        params={
            "service_type": ServiceTypeEnum.POSTGRESQL,
            "offset": 0,
            "limit": MAX_PAGINATION_LIMIT,
        },
    )


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
    """Test POST /backup_pg/{task_name} forwards the form payload to the tasks API."""
    response = test_client.post(
        f"/backup_pg/{created_task.name}",
        data=form_data,
        follow_redirects=False,
    )

    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert (
        response.headers["location"]
        == f"{test_client.base_url}/backup_pg/{created_task.name}"
    )

    mock_task_api_dep.post.assert_called_once()
    called_args, called_kwargs = mock_task_api_dep.post.call_args
    assert called_args[0] == f"/execute/{created_task.name}"
    assert called_kwargs["json"] == expected_json


@pytest.mark.usefixtures("_mock_get_backups_task_dep")
def test_pg_backups_delete(test_client, mock_task_api_dep, created_task):
    """Test POST /backup_pg/{task_name}/delete route."""
    response = test_client.post(
        f"/backup_pg/{created_task.name}/delete", follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["Location"] == "/backup_pg"

    mock_task_api_dep.delete.assert_awaited_once()
    called_args, _ = mock_task_api_dep.delete.await_args
    assert called_args[0] == f"/{created_task.name}"


@pytest.mark.usefixtures("_mock_get_backups_task_dep", "mock_get_username_mapping")
def test_pg_backups_detail_uses_own_delete_route(
    test_client, mock_task_api_dep, mock_inventory_api_dep, created_task
):
    """Test pg_backups_detail uses its own delete route.

    Regression guard: pg_backups_detail must use pg_backups_delete,
    not mysql_backups_delete, so the page renders even when mysql_backups
    plugin is disabled.
    """
    mock_task_api_dep.get = AsyncMock(
        side_effect=[
            {},
            {"items": [], "total": 0, "offset": 0, "limit": 50},
            {"items": [], "total": 0, "offset": 0, "limit": 50},
            [],
            {"items": [], "total": 0, "offset": 0, "limit": 50},
        ]
    )
    mock_inventory_api_dep.get = AsyncMock(
        return_value={"items": [], "total": 0, "offset": 0, "limit": 50}
    )

    response = test_client.get(f"/backup_pg/{created_task.name}")

    assert response.status_code == status.HTTP_200_OK
    assert f"/backup_pg/{created_task.name}/delete" in response.text
    # No cross-plugin URLs that include the task name (delete/update/detail).
    # The page may still contain `/mysql_backups/` from the global plugin nav
    # sidebar when mysql_backups is mounted; we only guard the task-specific
    # URLs that historically used `url_for("mysql_backups_*", task_name=...)`.
    assert f"/mysql_backups/{created_task.name}" not in response.text
    # The PG details page does not ship an edit form, so the Edit button must
    # be hidden (gated on `is_edit_form_present`). The Delete button must
    # still render so users can delete tasks via the UI.
    assert "delete-tasks-button" in response.text
    assert "edit-tasks-button" not in response.text


def test_pg_backups_index_links_periodic_tasks_to_own_detail_route(test_client):
    """Test the index page links periodic tasks to its own detail route.

    Regression guard: the periodic-task rows on the PG backups index
    page must link to pg_backups_detail, not mysql_backups_detail, so the page
    renders even when the mysql_backups plugin is disabled.
    """
    sep_app.dependency_overrides[get_backups_index_context] = lambda: {
        "user": "default_user",
        "executor_hosts": ["host1"],
        "services": [],
        # A non-empty `tasks` list forces the template to render the "Saved"
        # branch, which is what includes the Periodic Tasks partial we need
        # to exercise for this regression.
        "tasks": [{"name": "pg_periodic_task"}],
        "pending_tasks": [],
        "history_tasks": [],
        "running_tasks": [],
        "periodic_tasks": [
            {
                "id": 1,
                "task": "pg_periodic_task",
                "interval": {"every": 5, "period": "minutes"},
                "crontab": None,
                "period": "every 5 minutes",
                "start_time": None,
                "last_run_at": None,
                "next_run_at": None,
                "total_run_count": 0,
                "enabled": True,
                "execute_request": None,
            },
        ],
        "chainable_tasks": [],
        "AVAILABLE_TIMEZONES": ["UTC"],
        "alert_on_fail_default": False,
        "alert_on_fail_available": False,
        "connectivity_check_default": True,
    }

    response = test_client.get("/backup_pg/")

    assert response.status_code == status.HTTP_200_OK
    assert "/backup_pg/pg_periodic_task" in response.text
    assert "/mysql_backups/pg_periodic_task" not in response.text

    sep_app.dependency_overrides = {}


def test_jinja_routes_omitted_from_openapi(test_client):
    """Verify migrated Jinja routes are excluded from the OpenAPI schema.

    Regression guard: routes using ``DeprecatedJinja2Route`` must not appear
    in the generated OpenAPI spec now that the React ``backup_pg`` plugin
    replaces them.
    """
    spec = test_client.get("/openapi.json").json()

    legacy_paths = [
        ("/backup_pg/", "get"),
        ("/backup_pg/", "post"),
        ("/backup_pg/{task_name}", "get"),
        ("/backup_pg/{task_name}", "post"),
        ("/backup_pg/{task_name}/delete", "post"),
    ]
    for path, method in legacy_paths:
        operations = spec["paths"].get(path, {})
        assert method not in operations, (
            f"{method.upper()} {path} should be omitted from OpenAPI spec"
        )
