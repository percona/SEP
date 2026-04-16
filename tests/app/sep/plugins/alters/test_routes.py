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

"""Define tests for the app.sep.plugins.alters.routes module."""

from datetime import datetime, timedelta, UTC
from unittest.mock import AsyncMock, call

import pytest
from fastapi import HTTPException, status

from app.sep.main import sep_app
from app.sep.plugins.alters.deps import (
    build_alters_task_payload,
    get_alters_index_context,
    get_alters_task,
)
from app.sep.plugins.alters.models import AltersCreate
from app.tasks.models import (
    TaskBackendEnum,
    TaskHistoryStatusEnum,
    TaskOwner,
)
from tests.app.factories import (
    AltersCreateFactory,
    GeneratedTaskFactory,
    TaskFactory,
)


@pytest.fixture
def created_alters() -> AltersCreate:
    """Return a fake created AltersCreate instance."""
    return AltersCreateFactory.build()


@pytest.fixture
def _mock_alters_task_payload(generated_task):
    """Mock the AltersGeneratedTask dependency."""
    sep_app.dependency_overrides[build_alters_task_payload] = lambda: generated_task
    yield
    sep_app.dependency_overrides = {}


@pytest.fixture
def created_task():
    """Return a fake created Task instance."""
    return TaskFactory.build(owner=TaskOwner.ALTERS)


@pytest.fixture
def _mock_get_alters_task_dep(created_task):
    """Mock the TaskDep dependency."""
    sep_app.dependency_overrides[get_alters_task] = lambda: created_task
    yield
    sep_app.dependency_overrides = {}


@pytest.fixture
def _mock_get_alters_index_context_dep():
    """Mock the get_alters_index_context dependency with default user context."""
    sep_app.dependency_overrides[get_alters_index_context] = lambda: {
        "user": "default_user"
    }
    yield
    sep_app.dependency_overrides = {}


@pytest.mark.usefixtures("_mock_get_alters_index_context_dep")
def test_alters_index(
    test_client,
):
    """Test listing alters tasks."""
    response = test_client.get("/alters/")
    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "text/html; charset=utf-8"


@pytest.mark.usefixtures("_mock_alters_task_payload")
def test_alters_create(
    test_client,
    mock_task_api_dep,
    created_alters,
    generated_task,
):
    """Test creating a new alters task."""
    response = test_client.post(
        "/alters/", data=created_alters.model_dump(), follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert (
        response.headers["location"]
        == f"{test_client.base_url}/alters/{generated_task.name}"
    )


@pytest.mark.parametrize(
    ("nomad_hosts", "expect_skip_in_pre_checks_yaml"),
    [
        ({"db1": "10.0.0.5"}, False),
        ({"db1": "10.0.0.99"}, True),
    ],
)
def test_alters_create_pre_checks_filesystem_skip_flag(
    test_client,
    mock_task_api_dep,
    created_alters,
    nomad_hosts,
    expect_skip_in_pre_checks_yaml,
):
    """SEP-764: pre-checks YAML skip_filesystem_checks follows executor vs DB host (Nomad /hosts/)."""
    task = GeneratedTaskFactory.build(
        name="sep764-alter",
        data={
            "task": "run-command",
            "meta": {
                "command": "pt-online-schema-change",
                "args": "--alter=ADD COLUMN c INT --execute",
                "target": "db1",
                "_schema_name": "db",
                "_table_name": "t",
                "_service_host": "10.0.0.5",
                "_service_port": 3306,
            },
        },
        backend=TaskBackendEnum.PROXY,
    )
    sep_app.dependency_overrides[build_alters_task_payload] = lambda: task
    try:
        mock_task_api_dep.post.return_value = AsyncMock()
        mock_task_api_dep.get = AsyncMock(return_value=nomad_hosts)
        response = test_client.post(
            "/alters/", data=created_alters.model_dump(), follow_redirects=False
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER
        mock_task_api_dep.get.assert_awaited_once_with("/hosts/")
        pre_checks_cfg = mock_task_api_dep.post.call_args_list[2].kwargs["json"][
            "data"
        ]["meta"]["config"]
        if expect_skip_in_pre_checks_yaml:
            assert "skip_filesystem_checks: true" in pre_checks_cfg
        else:
            assert "skip_filesystem_checks" not in pre_checks_cfg
    finally:
        sep_app.dependency_overrides.pop(build_alters_task_payload, None)


@pytest.mark.usefixtures("_mock_get_alters_task_dep", "mock_get_username_mapping")
def test_alters_detail(
    test_client,
    created_task,
    mock_task_api_dep,
    mock_inventory_api_dep,
):
    """Test retrieving an alters' detail page."""
    mock_data = {
        "task": "run-command",
        "meta": {
            "command": "pt-online-schema-change",
            "args": "--alter=ADD COLUMN new_column INT --execute",
            "target": "localhost",
            "_schema_name": "public",
            "_table_name": "example_table",
        },
    }
    created_task.data = mock_data
    mock_task_api_dep.get.side_effect = [
        {"address1": "host1", "address2": "host2"},  # for /hosts/ (dependency)
        {"items": [], "total": 0, "offset": 0, "limit": 50},
        {"items": [], "total": 0, "offset": 0, "limit": 50},
        {"items": [], "total": 0, "offset": 0, "limit": 50},
        {"items": [], "total": 0, "offset": 0, "limit": 50},
        {"items": [], "total": 0, "offset": 0, "limit": 50},
        {"items": [], "total": 0, "offset": 0, "limit": 50},
        {},
        {"items": [], "total": 0, "offset": 0, "limit": 50},  # chainable_tasks
    ]
    expected_awaits = [
        call("/hosts/"),
        call(f"/{created_task.name}/history/"),
        call(f"/{created_task.name}-dry-run/history/"),
        call(f"/{created_task.name}-pre-checks/history/"),
        call(
            f"/{created_task.name}/history/",
            params={"status": TaskHistoryStatusEnum.RUNNING},
        ),
        call(
            f"/{created_task.name}-dry-run/history/",
            params={"status": TaskHistoryStatusEnum.RUNNING},
        ),
        call(
            f"/{created_task.name}-pre-checks/history/",
            params={"status": TaskHistoryStatusEnum.RUNNING},
        ),
        call(f"/stats/{created_task.name}"),
        call(
            "/",
            params={"owner": created_task.owner, "target": "localhost"},
        ),
    ]

    response = test_client.get(f"/alters/{created_task.name}")

    assert response.status_code == status.HTTP_200_OK
    assert created_task.name in response.text
    assert mock_task_api_dep.get.await_count == len(expected_awaits)
    mock_task_api_dep.get.assert_has_awaits(expected_awaits)


@pytest.mark.usefixtures(
    "_mock_get_alters_task_dep", "_mock_check_for_conflicted_running_tasks"
)
def test_alters_execute(
    test_client,
    created_task,
    mock_task_api_dep,
):
    """Test executing a alters task."""
    mock_task_api_dep.post.return_value = AsyncMock()
    eta = datetime.now(tz=UTC) + timedelta(days=1)
    response = test_client.post(
        f"/alters/{created_task.name}", data={"eta": str(eta)}, follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert (
        response.headers["location"]
        == f"{test_client.base_url}/alters/{created_task.name}"
    )


@pytest.mark.usefixtures("_mock_get_alters_task_dep")
def test_alters_delete(
    test_client,
    created_task,
    mock_task_api_dep,
):
    """Test deleting a alters task."""
    mock_task_api_dep.delete.return_value = AsyncMock()

    response = test_client.post(
        f"/alters/{created_task.name}/delete", follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/alters"
    mock_task_api_dep.delete.assert_has_awaits(
        [
            call(f"/{created_task.name}"),
            call(f"/{created_task.name}-dry-run"),
            call(f"/{created_task.name}-pre-checks"),
        ]
    )


def test_get_table_details(
    test_client,
    mock_inventory_api_dep,
):
    """Test getting table details via XHR endpoint."""
    table_id = 123
    mock_table_data = {
        "id": table_id,
        "name": "test_table",
        "create": "CREATE TABLE test_table (id INT PRIMARY KEY, name VARCHAR(255))",
        "keys": {"PRIMARY": {"type": "PRIMARY", "columns": ["id"]}},
    }
    mock_inventory_api_dep.get.side_effect = [mock_table_data]

    response = test_client.get(f"/alters/table/{table_id}/details")

    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "application/json"

    data = response.json()
    assert data["id"] == table_id
    assert data["name"] == "test_table"
    assert data["create"] == mock_table_data["create"]
    assert data["keys"] == mock_table_data["keys"]

    mock_inventory_api_dep.get.assert_awaited_once_with(f"/tables/{table_id}")


def test_get_table_details_with_syntax_highlight(
    test_client,
    mock_inventory_api_dep,
):
    """syntax_highlight_style applies Pygments to the create statement."""
    table_id = 55
    create_sql = "CREATE TABLE t (id INT);"
    mock_inventory_api_dep.get = AsyncMock(
        return_value={
            "id": table_id,
            "name": "t",
            "create": create_sql,
            "keys": {},
        }
    )
    response = test_client.get(
        f"/alters/table/{table_id}/details?syntax_highlight_style=default"
    )
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["create"] != create_sql
    assert "highlight" in body["create"] or "<span" in body["create"]


def test_get_table_details_inventory_error(
    test_client,
    mock_inventory_api_dep,
):
    """Inventory failure returns JSON 500."""
    mock_inventory_api_dep.get = AsyncMock(
        side_effect=HTTPException(status_code=404, detail="missing")
    )
    response = test_client.get("/alters/table/999/details")
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json()["error"] == "Failed to fetch table details"


@pytest.mark.usefixtures("_mock_get_alters_task_dep", "mock_get_username_mapping")
def test_alters_detail_redirects_to_parent_task(
    test_client,
    created_task,
    mock_task_api_dep,
    mock_inventory_api_dep,
):
    """Child task (dry-run / pre-checks) redirects to parent detail."""
    mock_task_api_dep.get = AsyncMock(return_value={})
    mock_inventory_api_dep.get = AsyncMock(return_value=[])
    created_task.name = "child-alter"
    created_task.data = {
        "parent": "parent-alter",
        "task": "run-command",
        "meta": {
            "command": "pt-online-schema-change",
            "args": "--execute",
            "target": "localhost",
            "_schema_name": "db",
            "_table_name": "tbl",
        },
    }
    response = test_client.get("/alters/child-alter", follow_redirects=False)
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"].endswith("/alters/parent-alter")


@pytest.mark.usefixtures("_mock_get_alters_task_dep", "mock_get_username_mapping")
def test_alters_detail_when_hosts_api_fails(
    test_client,
    created_task,
    mock_task_api_dep,
    mock_inventory_api_dep,
):
    """Executor hosts failure yields empty host map; page still renders."""
    mock_data = {
        "task": "run-command",
        "meta": {
            "command": "pt-online-schema-change",
            "args": "--alter=x --execute",
            "target": "localhost",
            "_schema_name": "public",
            "_table_name": "t",
        },
    }
    created_task.data = mock_data

    async def tasks_api_get(path: str, *args, **kwargs) -> object:
        # Do not rely on call order of FastAPI deps — match by path.
        if path == "/hosts/":
            raise HTTPException(status_code=503)
        if path.startswith("/stats/"):
            return {}
        if "/history/" in path or path == "/":
            return {"items": [], "total": 0, "offset": 0, "limit": 50}
        return []

    mock_task_api_dep.get = AsyncMock(side_effect=tasks_api_get)
    mock_inventory_api_dep.get = AsyncMock(
        return_value={"items": [], "total": 0, "offset": 0, "limit": 50}
    )
    response = test_client.get(f"/alters/{created_task.name}")
    assert response.status_code == status.HTTP_200_OK
    assert created_task.name in response.text


@pytest.mark.usefixtures("_mock_get_alters_task_dep", "mock_get_username_mapping")
def test_alters_detail_when_services_api_fails(
    test_client,
    created_task,
    mock_task_api_dep,
    mock_inventory_api_dep,
):
    """MySQL services list failure yields empty services; page still renders."""
    mock_data = {
        "task": "run-command",
        "meta": {
            "command": "pt-online-schema-change",
            "args": "--execute",
            "target": "localhost",
            "_schema_name": "p",
            "_table_name": "t",
        },
    }
    created_task.data = mock_data

    async def tasks_api_get_ok(path: str, *args, **kwargs) -> object:
        if path == "/hosts/":
            return {}
        if path.startswith("/stats/"):
            return {}
        if "/history/" in path or path == "/":
            return {"items": [], "total": 0, "offset": 0, "limit": 50}
        return []

    async def inventory_api_get(path: str, *args, **kwargs) -> object:
        if path == "/":
            return []
        if path.startswith("/services"):
            raise HTTPException(status_code=500)
        return []

    mock_task_api_dep.get = AsyncMock(side_effect=tasks_api_get_ok)
    mock_inventory_api_dep.get = AsyncMock(side_effect=inventory_api_get)
    response = test_client.get(f"/alters/{created_task.name}")
    assert response.status_code == status.HTTP_200_OK


@pytest.mark.parametrize(
    ("nomad_hosts", "executor_hostname", "expect_skip_in_pre_checks_yaml"),
    [
        ({}, "localhost", False),
        ({"db1": "10.0.0.99"}, "db1", True),
    ],
)
def test_alters_update_refreshes_pre_checks_task(
    test_client,
    mock_task_api_dep,
    mock_inventory_api_dep,
    created_alters,
    created_service,
    created_schema,
    created_table,
    nomad_hosts,
    executor_hostname,
    expect_skip_in_pre_checks_yaml,
):
    """Update main/dry-run/pre-checks tasks; pre-checks YAML reflects executor vs DB."""
    created_alters.service_id = created_service.id
    created_alters.schema_id = created_schema.id
    created_alters.table_id = created_table.id
    created_alters.hostname = executor_hostname
    mock_inventory_api_dep.get.side_effect = [
        created_service.model_dump(),
        created_schema.model_dump(),
        created_table.model_dump(),
    ]
    mock_task_api_dep.put.return_value = AsyncMock()
    mock_task_api_dep.get = AsyncMock(return_value=nomad_hosts)
    name = created_alters.task_name
    response = test_client.post(
        f"/alters/{name}/update",
        data=created_alters.model_dump(),
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_task_api_dep.get.assert_awaited_once_with("/hosts/")
    update_puts = mock_task_api_dep.put.call_args_list
    assert len(update_puts) == len(["main", "dry_run", "pre_checks"])
    pre_checks_put = [c for c in update_puts if "pre-checks" in c.args[0]]
    assert len(pre_checks_put) == 1
    cfg = pre_checks_put[0].kwargs["json"]["data"]["meta"]["config"]
    assert "schema:" in cfg
    assert "table:" in cfg
    if expect_skip_in_pre_checks_yaml:
        assert "skip_filesystem_checks: true" in cfg
    else:
        assert "skip_filesystem_checks" not in cfg
