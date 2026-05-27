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

"""Tests for the alters plugin JSON API routes under /api/plugins/alters/."""

from typing import Any
from unittest.mock import AsyncMock, call

import pytest
from fastapi import HTTPException, status

from app.core.exceptions import HTTPNotFoundException
from app.inventory.models import ServiceTypeEnum
from app.sep.connectivity import clear_connectivity_caches
from app.sep.inventory import CreatedService
from app.tasks.models import TaskBackendEnum, TaskHistoryStatusEnum, TaskOwner
from tests.app.factories import TaskFactory

API_BASE = "/api/plugins/alters"
DEFAULT_TASK_NAME = "alter-task"
DEFAULT_PARENT_NAME = "parent-alter"
EXPECTED_CASCADE_CREATE_POSTS = 4
EXPECTED_CASCADE_UPDATE_PUTS = 3
NOMAD_HOSTS = {"host1": "127.0.0.1"}


def build_alters_task(
    name: str = DEFAULT_TASK_NAME,
    *,
    parent: str | None = None,
    protected: bool = False,
    **overrides: Any,
) -> dict:
    """Build a fake alters task payload shaped like the Tasks API response."""
    data_overrides = overrides.pop("data", {})
    meta_overrides = data_overrides.pop("meta", {})
    task = TaskFactory.build(
        name=name,
        owner=TaskOwner.ALTERS,
        backend=TaskBackendEnum.PROXY,
        protected=protected,
        **overrides,
    )
    payload = task.model_dump(mode="json")
    payload["data"] = {
        "task": "run-command",
        "meta": {
            "command": "pt-online-schema-change",
            "args": (
                "--alter=ADD COLUMN x INT "
                "h=127.0.0.1,P=3306,D=test_schema,t=test_table "
                "--recursion-method=processlist --execute"
            ),
            "target": "host1",
            "_schema_name": "test_schema",
            "_table_name": "test_table",
            "_service_host": "127.0.0.1",
            "_service_port": 3306,
            **meta_overrides,
        },
        **data_overrides,
    }
    if parent is not None:
        payload["data"]["parent"] = parent
    return payload


def build_alters_task_group(parent_name: str = DEFAULT_PARENT_NAME) -> dict[str, dict]:
    """Return parent, dry-run, and pre-checks task payloads for one group."""
    return {
        "parent": build_alters_task(parent_name),
        "dry_run": build_alters_task(f"{parent_name}-dry-run", parent=parent_name),
        "pre_checks": build_alters_task(
            f"{parent_name}-pre-checks", parent=parent_name
        ),
    }


def build_alters_write_body(
    task_name: str = DEFAULT_TASK_NAME,
    hostname: str = "host1",
    service_id: int = 1,
    **kwargs: Any,
) -> dict:
    """Build a valid AltersTaskWrite-compatible request body."""
    return {
        "task_name": task_name,
        "hostname": hostname,
        "service_id": service_id,
        "schema_name": "test_schema",
        "table_name": "test_table",
        "alter": "ADD COLUMN x INT",
        **kwargs,
    }


def build_execute_response(
    task_id: int | None = 99, task_name: str = DEFAULT_TASK_NAME
) -> dict:
    """Build a minimal TaskHistoryResponse-shaped dict for execute endpoint tests."""
    return {
        "id": task_id,
        "execution_request": {"task": "run-command", "target": "host1"},
        "task": {**build_alters_task(task_name), "deleted_at": None},
    }


def cascade_create_post_side_effect(
    task_name: str,
    *,
    execute_result: Any = None,
) -> list[Any]:
    """Build ``tasks_api.post`` side effects for a successful cascade create."""
    return [
        build_alters_task(task_name),
        build_alters_task(f"{task_name}-dry-run", parent=task_name),
        build_alters_task(f"{task_name}-pre-checks", parent=task_name),
        execute_result,
    ]


def configure_cascade_create_mocks(
    mock_task_api_dep: AsyncMock,
    mock_inventory_api_dep: AsyncMock,
    created_service: CreatedService,
    task_name: str = DEFAULT_TASK_NAME,
    *,
    execute_result: Any = None,
    fetch_created_task: bool = True,
) -> None:
    """Wire inventory, cascade POST, and Nomad hosts mocks for create-route tests."""
    mock_inventory_api_dep.get = AsyncMock(return_value=created_service.model_dump())
    mock_task_api_dep.post = AsyncMock(
        side_effect=cascade_create_post_side_effect(
            task_name,
            execute_result=execute_result,
        )
    )
    get_side_effects: list[Any] = [NOMAD_HOSTS]
    if fetch_created_task:
        get_side_effects.append(build_alters_task(task_name))
    mock_task_api_dep.get = AsyncMock(side_effect=get_side_effects)


@pytest.fixture(autouse=True)
def _clear_connectivity_caches():
    """Clear the connectivity alru_cache and snapshot between tests."""
    clear_connectivity_caches()
    yield
    clear_connectivity_caches()


class TestAltersPluginSchemaEndpoint:
    """Tests for GET /api/plugins/alters/schema."""

    def test_schema_returns_200(self, test_client):
        """Ensure the schema endpoint returns HTTP 200 with JSON content."""
        response = test_client.get(f"{API_BASE}/schema")

        assert response.status_code == status.HTTP_200_OK
        assert "application/json" in response.headers["content-type"]

    def test_schema_declares_cascade_primitives(self, test_client):
        """Ensure the schema exposes dry-run derived and pre-checks predecessor legs."""
        response = test_client.get(f"{API_BASE}/schema")

        payload = response.json()
        assert [item["name_suffix"] for item in payload["derived"]] == ["-dry-run"]
        assert payload["derived"][0]["arg_substitutions"] == {"--execute": "--dry-run"}
        assert [item["name_suffix"] for item in payload["predecessors"]] == [
            "-pre-checks"
        ]
        assert payload["predecessors"][0]["on_failure"] == "halt"


class TestAltersApiList:
    """Tests for GET /api/plugins/alters/."""

    def test_list_returns_parent_tasks_only(
        self, test_client, mock_task_api_dep
    ) -> None:
        """List only parent execute tasks, not dry-run or pre-checks siblings."""
        group = build_alters_task_group(DEFAULT_PARENT_NAME)
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                {
                    "items": [group["parent"], group["dry_run"]],
                    "total": 2,
                    "offset": 0,
                    "limit": 50,
                },
                {"items": [{"status": TaskHistoryStatusEnum.SUCCESS.value}]},
            ]
        )

        response = test_client.get(f"{API_BASE}/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == DEFAULT_PARENT_NAME
        assert data[0]["service_type"] == ServiceTypeEnum.MYSQL.value

    def test_list_returns_empty_for_non_mysql_service_type(
        self, test_client, mock_task_api_dep
    ) -> None:
        """Non-MySQL service_type returns empty without calling the Tasks API."""
        response = test_client.get(
            f"{API_BASE}/",
            params={"service_type": ServiceTypeEnum.POSTGRESQL.value},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []
        mock_task_api_dep.get.assert_not_called()


class TestAltersApiDetail:
    """Tests for GET /api/plugins/alters/{task_name}."""

    def test_detail_returns_parent_task(self, test_client, mock_task_api_dep) -> None:
        """Ensure the detail endpoint returns the parent task with status."""
        group = build_alters_task_group(DEFAULT_PARENT_NAME)
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                group["parent"],
                {"items": [{"status": TaskHistoryStatusEnum.RUNNING.value}]},
            ]
        )

        response = test_client.get(f"{API_BASE}/{DEFAULT_PARENT_NAME}")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["name"] == DEFAULT_PARENT_NAME
        assert body["status"] == TaskHistoryStatusEnum.RUNNING.value

    def test_detail_resolves_satellite_name_to_parent(
        self, test_client, mock_task_api_dep
    ) -> None:
        """Requesting a satellite name returns the parent task."""
        group = build_alters_task_group(DEFAULT_PARENT_NAME)
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                group["dry_run"],
                group["parent"],
                {"items": []},
            ]
        )

        response = test_client.get(f"{API_BASE}/{DEFAULT_PARENT_NAME}-dry-run")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == DEFAULT_PARENT_NAME


class TestAltersApiCreate:
    """Tests for POST /api/plugins/alters/."""

    def test_create_posts_parent_derived_predecessor_and_chains(
        self,
        test_client,
        mock_task_api_dep,
        mock_inventory_api_dep,
        created_service,
    ) -> None:
        """POST creates parent, dry-run, pre-checks, and fires the pre-checks chain."""
        configure_cascade_create_mocks(
            mock_task_api_dep,
            mock_inventory_api_dep,
            created_service,
            DEFAULT_TASK_NAME,
        )

        response = test_client.post(
            f"{API_BASE}/?check_connectivity=false",
            json=build_alters_write_body(
                task_name=DEFAULT_TASK_NAME,
                service_id=created_service.id,
            ),
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert mock_task_api_dep.post.await_count == EXPECTED_CASCADE_CREATE_POSTS
        assert mock_task_api_dep.post.await_args_list[-1] == call(
            f"/execute/{DEFAULT_TASK_NAME}-pre-checks",
            json={
                "chain_task_names": [DEFAULT_TASK_NAME],
                "chain_on_failure": False,
            },
        )
        first_post = mock_task_api_dep.post.await_args_list[0].kwargs["json"]
        assert first_post["owner"] == TaskOwner.ALTERS.value
        assert "--execute" in first_post["data"]["meta"]["args"]
        dry_run_post = mock_task_api_dep.post.await_args_list[1].kwargs["json"]
        assert dry_run_post["name"] == f"{DEFAULT_TASK_NAME}-dry-run"
        assert "--dry-run" in dry_run_post["data"]["meta"]["args"]
        assert dry_run_post["data"]["parent"] == DEFAULT_TASK_NAME

    def test_create_continue_on_pre_check_failure_sets_chain_on_failure(
        self,
        test_client,
        mock_task_api_dep,
        mock_inventory_api_dep,
        created_service,
    ) -> None:
        """continue_on_pre_check_failure maps to chain_on_failure on pre-checks execute."""
        configure_cascade_create_mocks(
            mock_task_api_dep,
            mock_inventory_api_dep,
            created_service,
            DEFAULT_TASK_NAME,
        )

        response = test_client.post(
            f"{API_BASE}/?check_connectivity=false",
            json=build_alters_write_body(
                task_name=DEFAULT_TASK_NAME,
                service_id=created_service.id,
                continue_on_pre_check_failure=True,
            ),
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert mock_task_api_dep.post.await_args_list[-1] == call(
            f"/execute/{DEFAULT_TASK_NAME}-pre-checks",
            json={
                "chain_task_names": [DEFAULT_TASK_NAME],
                "chain_on_failure": True,
            },
        )

    def test_create_rolls_back_on_execute_chain_failure(
        self,
        test_client,
        mock_task_api_dep,
        mock_inventory_api_dep,
        created_service,
    ) -> None:
        """Rollback DELETEs created tasks when the pre-checks execute POST fails."""
        configure_cascade_create_mocks(
            mock_task_api_dep,
            mock_inventory_api_dep,
            created_service,
            DEFAULT_TASK_NAME,
            execute_result=HTTPException(status_code=status.HTTP_502_BAD_GATEWAY),
            fetch_created_task=False,
        )
        mock_task_api_dep.delete = AsyncMock(return_value=None)

        response = test_client.post(
            f"{API_BASE}/?check_connectivity=false",
            json=build_alters_write_body(
                task_name=DEFAULT_TASK_NAME,
                service_id=created_service.id,
            ),
        )

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert mock_task_api_dep.delete.await_args_list == [
            call(f"/{DEFAULT_TASK_NAME}-pre-checks"),
            call(f"/{DEFAULT_TASK_NAME}-dry-run"),
            call(f"/{DEFAULT_TASK_NAME}"),
        ]

    def test_create_returns_422_missing_required_fields(
        self, test_client, mock_task_api_dep
    ) -> None:
        """POST returns 422 when required fields are absent."""
        response = test_client.post(f"{API_BASE}/", json={})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()


class TestAltersApiUpdate:
    """Tests for PUT /api/plugins/alters/{task_name}."""

    @pytest.mark.usefixtures("_mock_check_for_conflicted_running_tasks")
    def test_update_puts_parent_and_satellites(
        self,
        test_client,
        mock_task_api_dep,
        mock_inventory_api_dep,
        created_service,
    ) -> None:
        """PUT updates parent, dry-run sibling, and pre-checks predecessor."""
        group = build_alters_task_group(DEFAULT_PARENT_NAME)
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                group["parent"],
                NOMAD_HOSTS,
                group["parent"],
                {"items": []},
            ]
        )
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        mock_task_api_dep.put = AsyncMock(return_value=group["parent"])

        response = test_client.put(
            f"{API_BASE}/{DEFAULT_PARENT_NAME}?check_connectivity=false",
            json=build_alters_write_body(
                task_name=DEFAULT_PARENT_NAME,
                service_id=created_service.id,
            ),
        )

        assert response.status_code == status.HTTP_200_OK
        assert mock_task_api_dep.put.await_count == EXPECTED_CASCADE_UPDATE_PUTS
        put_paths = [c.args[0] for c in mock_task_api_dep.put.await_args_list]
        assert put_paths == [
            f"/{DEFAULT_PARENT_NAME}",
            f"/{DEFAULT_PARENT_NAME}-dry-run",
            f"/{DEFAULT_PARENT_NAME}-pre-checks",
        ]

    @pytest.mark.usefixtures("_mock_check_for_conflicted_running_tasks")
    def test_update_returns_409_for_protected_task(
        self, test_client, mock_task_api_dep
    ) -> None:
        """PUT returns 409 when the parent task is protected."""
        parent = build_alters_task("protected-alter", protected=True)
        mock_task_api_dep.get = AsyncMock(return_value=parent)

        response = test_client.put(
            f"{API_BASE}/protected-alter",
            json=build_alters_write_body(task_name="protected-alter"),
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        mock_task_api_dep.put.assert_not_called()


class TestAltersApiDelete:
    """Tests for DELETE /api/plugins/alters/{task_name}."""

    def test_delete_removes_satellites_then_parent(
        self, test_client, mock_task_api_dep
    ) -> None:
        """DELETE cascades to dry-run and pre-checks before the parent."""
        group = build_alters_task_group(DEFAULT_PARENT_NAME)
        mock_task_api_dep.get = AsyncMock(return_value=group["parent"])
        mock_task_api_dep.delete = AsyncMock(return_value=None)

        response = test_client.delete(f"{API_BASE}/{DEFAULT_PARENT_NAME}")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert mock_task_api_dep.delete.await_args_list == [
            call(f"/{DEFAULT_PARENT_NAME}-dry-run"),
            call(f"/{DEFAULT_PARENT_NAME}-pre-checks"),
            call(f"/{DEFAULT_PARENT_NAME}"),
        ]

    def test_delete_resolves_satellite_name_to_parent_group(
        self, test_client, mock_task_api_dep
    ) -> None:
        """DELETE by satellite name still removes the whole task group."""
        group = build_alters_task_group(DEFAULT_PARENT_NAME)
        mock_task_api_dep.get = AsyncMock(
            side_effect=[group["pre_checks"], group["parent"]]
        )
        mock_task_api_dep.delete = AsyncMock(return_value=None)

        response = test_client.delete(f"{API_BASE}/{DEFAULT_PARENT_NAME}-pre-checks")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert mock_task_api_dep.delete.await_args_list[-1] == call(
            f"/{DEFAULT_PARENT_NAME}"
        )

    def test_delete_returns_500_when_cascade_delete_partially_fails(
        self, test_client, mock_task_api_dep
    ) -> None:
        """Return 500 when a satellite DELETE fails with a non-404 error."""
        group = build_alters_task_group(DEFAULT_PARENT_NAME)
        mock_task_api_dep.get = AsyncMock(return_value=group["parent"])
        derived_exc = HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

        async def _delete(path: str) -> None:
            if path == f"/{DEFAULT_PARENT_NAME}-pre-checks":
                raise derived_exc

        mock_task_api_dep.delete = AsyncMock(side_effect=_delete)

        response = test_client.delete(f"{API_BASE}/{DEFAULT_PARENT_NAME}")

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert f"{DEFAULT_PARENT_NAME}-pre-checks" in response.json()["detail"]


class TestAltersApiExecute:
    """Tests for POST /api/plugins/alters/{task_name}/execute."""

    @pytest.mark.usefixtures("_mock_check_for_conflicted_running_tasks")
    def test_execute_returns_201_with_task_name_and_id(
        self, test_client, mock_task_api_dep
    ) -> None:
        """Executing an alters task returns 201 with task_name and task_id."""
        expected_task_id = 42
        task = build_alters_task(DEFAULT_PARENT_NAME)
        mock_task_api_dep.get = AsyncMock(return_value=task)
        mock_task_api_dep.post = AsyncMock(
            return_value=build_execute_response(
                expected_task_id, task_name=DEFAULT_PARENT_NAME
            )
        )

        response = test_client.post(
            f"{API_BASE}/{DEFAULT_PARENT_NAME}/execute", json={}
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["task_name"] == DEFAULT_PARENT_NAME
        assert data["task_id"] == expected_task_id
        mock_task_api_dep.post.assert_awaited_once_with(
            f"/execute/{DEFAULT_PARENT_NAME}", json={}
        )

    @pytest.mark.usefixtures("_mock_check_for_conflicted_running_tasks")
    def test_execute_returns_404_for_unknown_task(
        self, test_client, mock_task_api_dep
    ) -> None:
        """Executing an unknown task name returns 404."""
        mock_task_api_dep.get = AsyncMock(side_effect=HTTPNotFoundException())

        response = test_client.post(f"{API_BASE}/ghost-task/execute", json={})

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestAltersApiAuth:
    """Tests for API authentication."""

    def test_unauthenticated_list_returns_401(self, unauthenticated_client) -> None:
        """Reject unauthenticated access to the alters API."""
        response = unauthenticated_client.get(f"{API_BASE}/")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
