# Copyright 2026 Percona LLC
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
from fastapi import status

from app.sep.main import sep_app
from app.sep.plugins.alters.deps import (
    build_alters_task_payload,
    get_alters_index_context,
    get_alters_task,
)
from app.sep.plugins.alters.models import AltersCreate
from app.tasks.models import (
    TaskHistoryStatusEnum,
    TaskOwner,
)
from tests.app.factories import AltersCreateFactory, TaskFactory


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
        {},
        {},
        [],
        [],
        {},
        {},
        {},
        {"address1": "host1", "address2": "host2"},  # for /hosts/
    ]
    expected_awaits = [
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
        call("/hosts/"),
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
        [call(f"/{created_task.name}"), call(f"/{created_task.name}-dry-run")]
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
