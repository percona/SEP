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

"""Exercise the derived archives JSON router over the real HTTP request stack.

Replaces the hand-written ``api_routes`` tests: the model-first
``TaskExecutionApp`` derives the schema / list / detail / create / update / delete
routes, so these tests drive them through ``build_contract_client`` (which
overrides only the Tasks-API / Inventory-API boundaries, never the create-body
dep) with the collapsed one-of create body.
"""

from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from fastapi import status

from app.core.auth.providers.casdoor.models import CasdoorUser
from app.sep.apps.archives import app as archives_app
from app.sep.apps.archives.models import ArchivesCreate
from app.sep.apps.framework.spec import RESERVED_FORM_KEY
from app.tasks.models import TaskHistoryStatusEnum
from tests.app.factories import MOCK_DESTINATION_TABLE_ID
from tests.app.sep.apps.framework.contract_suite import (
    app_base_url,
    build_contract_client,
    shared_contract_client,
)
from tests.app.sep.apps.framework.kit import MockInventoryAPI, MockTaskAPI

_BASE = app_base_url(archives_app)
_SEEDED = "existing-archive"


def _inventory() -> MockInventoryAPI:
    """Return an inventory mock that also seeds the distinct destination table."""
    api = MockInventoryAPI()
    api.seed_table(MOCK_DESTINATION_TABLE_ID)
    return api


def _create_body(**overrides: Any) -> dict[str, Any]:
    """Return a valid one-of create body (source/dest by inventory id)."""
    body: dict[str, Any] = {
        "task_name": "new-archive",
        "hostname": "exec-host",
        "service_id": 1,
        "swap_drop": 0,
        "source": {"mode": "table", "source_db": 1, "source_table": 1},
        "destination": {"mode": "table", "dest_table": MOCK_DESTINATION_TABLE_ID},
        "where": "id < 100",
    }
    body.update(overrides)
    return body


@pytest.fixture
def client(regular_user: CasdoorUser) -> Iterator[Any]:
    """Return an authenticated contract client with a seeded archive task."""
    tasks_api = MockTaskAPI()
    tasks_api.seed_task(_SEEDED, owner="ARCHIVER")
    yield from shared_contract_client(
        archives_app,
        user=regular_user,
        tasks_api=tasks_api,
        inventory_api=_inventory(),
    )


def _seeded_client(
    regular_user: CasdoorUser,
    *,
    statuses: Sequence[TaskHistoryStatusEnum] = (),
    protected: bool = False,
) -> Any:
    """Return a contract client whose seeded archive task carries the given state.

    :param regular_user: The authenticated user the client acts as.
    :param statuses: Execution statuses seeded on the task's history (RUNNING trips
        the framework default conflict guard).
    :param protected: Whether the seeded task is protected (trips the default
        protected-task guard).
    :return: An authenticated contract client for the archives app.
    """
    tasks_api = MockTaskAPI()
    tasks_api.seed_task(
        _SEEDED, owner=archives_app.owner, statuses=statuses, protected=protected
    )
    return build_contract_client(
        archives_app,
        user=regular_user,
        tasks_api=tasks_api,
        inventory_api=_inventory(),
    )


class TestArchivesApiReads:
    """Cover the derived schema / list / detail read routes."""

    def test_schema_returns_one_of_groups(self, client: Any) -> None:
        """Serve a derived schema carrying the source/destination/host one-of groups."""
        response = client.get(f"{_BASE}/schema")
        assert response.status_code == status.HTTP_200_OK
        body = response.text
        assert "source.mode" in body
        assert "destination.mode" in body
        assert "host.mode" in body

    def test_list_returns_seeded_task(self, client: Any) -> None:
        """List the archive tasks owned by the archiver."""
        response = client.get(f"{_BASE}/")
        assert response.status_code == status.HTTP_200_OK
        assert any(item["name"] == _SEEDED for item in response.json()["items"])

    def test_detail_returns_task(self, client: Any) -> None:
        """Return a single archive task by name."""
        response = client.get(f"{_BASE}/{_SEEDED}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == _SEEDED

    def test_detail_unknown_returns_404(self, client: Any) -> None:
        """Return 404 for an unknown task name."""
        assert client.get(f"{_BASE}/nope").status_code == status.HTTP_404_NOT_FOUND


class TestArchivesApiCreate:
    """Cover the derived create route over the real body-parsing graph."""

    def test_create_returns_201_with_connectivity_warning(self, client: Any) -> None:
        """Create an archive task and surface the connectivity-warning field."""
        response = client.post(f"{_BASE}/", json=_create_body())
        assert response.status_code == status.HTTP_201_CREATED
        assert "connectivity_warning" in response.json()

    def test_create_query_source(self, client: Any) -> None:
        """Create an archive task from a query source branch."""
        body = _create_body(source={"mode": "query", "source_query": "SELECT 1"})
        response = client.post(f"{_BASE}/", json=body)
        assert response.status_code == status.HTTP_201_CREATED

    def test_create_stamps_form_input(self, regular_user: CasdoorUser) -> None:
        """Persist the validated one-of create body under ``data['_form']``."""
        tasks_api = MockTaskAPI()
        client = build_contract_client(
            archives_app,
            user=regular_user,
            tasks_api=tasks_api,
            inventory_api=_inventory(),
        )
        body = _create_body()

        response = client.post(f"{_BASE}/", json=body)

        assert response.status_code == status.HTTP_201_CREATED
        expected = ArchivesCreate.model_validate(body).model_dump(mode="json")
        assert tasks_api.last_create_payload["data"][RESERVED_FORM_KEY] == expected

    def test_create_rejects_non_purge_swap_drop(self, client: Any) -> None:
        """Reject a create with an unsupported archive type."""
        response = client.post(f"{_BASE}/", json=_create_body(swap_drop=1))
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_create_rejects_missing_destination(self, client: Any) -> None:
        """Reject a create with no destination and no delete_data."""
        body = _create_body()
        del body["destination"]
        response = client.post(f"{_BASE}/", json=body)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_create_rejects_dsn_delimiter_in_manual_host(self, client: Any) -> None:
        """Reject a manual destination host carrying a DSN delimiter."""
        body = _create_body(host={"mode": "manual", "dest_host": "a,b"})
        response = client.post(f"{_BASE}/", json=body)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


class TestArchivesApiUpdateDelete:
    """Cover the derived update and delete routes."""

    def test_update_returns_200(self, client: Any) -> None:
        """Update an existing archive task through the derived PUT."""
        response = client.put(
            f"{_BASE}/{_SEEDED}", json=_create_body(task_name=_SEEDED)
        )
        assert response.status_code == status.HTTP_200_OK

    def test_delete_returns_204(self, client: Any) -> None:
        """Delete an existing archive task."""
        response = client.delete(f"{_BASE}/{_SEEDED}")
        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_delete_unknown_returns_404(self, client: Any) -> None:
        """Return 404 when deleting an unknown task."""
        assert client.delete(f"{_BASE}/nope").status_code == status.HTTP_404_NOT_FOUND

    def test_update_running_task_returns_409(self, regular_user: CasdoorUser) -> None:
        """Reject a PUT that would edit a task with a running execution."""
        client = _seeded_client(regular_user, statuses=(TaskHistoryStatusEnum.RUNNING,))
        response = client.put(
            f"{_BASE}/{_SEEDED}", json=_create_body(task_name=_SEEDED)
        )
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_delete_running_task_returns_409(self, regular_user: CasdoorUser) -> None:
        """Reject a DELETE of a task with a running execution."""
        client = _seeded_client(regular_user, statuses=(TaskHistoryStatusEnum.RUNNING,))
        response = client.delete(f"{_BASE}/{_SEEDED}")
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_update_protected_task_returns_409(self, regular_user: CasdoorUser) -> None:
        """Reject a PUT that would edit a protected task."""
        client = _seeded_client(regular_user, protected=True)
        response = client.put(
            f"{_BASE}/{_SEEDED}", json=_create_body(task_name=_SEEDED)
        )
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_delete_protected_task_returns_409(self, regular_user: CasdoorUser) -> None:
        """Reject a DELETE of a protected task."""
        client = _seeded_client(regular_user, protected=True)
        response = client.delete(f"{_BASE}/{_SEEDED}")
        assert response.status_code == status.HTTP_409_CONFLICT
