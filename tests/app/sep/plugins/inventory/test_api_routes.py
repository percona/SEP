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

"""Define tests for the inventory plugin JSON API routes under ``/api/plugins/inventory/``.

Path mapping, entity validation, list unwrapping, and query forwarding are
implemented in ``app.sep.plugins.inventory.deps``; see
``tests/app/sep/plugins/inventory/test_deps.py`` for direct unit coverage.
"""

import json
from unittest.mock import AsyncMock

import pytest
from fastapi import status

from app.sep.plugins.inventory.deps import INVENTORY_PLUGIN_ENTITY_NAMES

_EXPECTED_SCHEMA_ENTITY_COUNT = len(INVENTORY_PLUGIN_ENTITY_NAMES)
_CREATE_SERVICE_TEST_NODE_ID = 7


class TestInventorySchemaEndpoint:
    """Tests for GET /api/plugins/inventory/schema."""

    def test_schema_returns_200(self, test_client):
        """Ensure the schema endpoint returns HTTP 200 with the expected plugin body."""
        response = test_client.get("/api/plugins/inventory/schema")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["name"] == "inventory"
        assert len(body["entities"]) == _EXPECTED_SCHEMA_ENTITY_COUNT


class TestInventoryGateway:
    """Tests for inventory CRUD proxy routes under ``/api/plugins/inventory/``."""

    def test_list_nodes_unwraps_items(self, test_client, mock_inventory_api_dep):
        """Ensure GET ``/api/plugins/inventory/nodes/`` unwraps paginated ``items`` to a JSON array."""
        mock_inventory_api_dep.get.return_value = {
            "items": [{"id": 1, "name": "n"}],
            "total": 1,
            "offset": 0,
            "limit": 50,
        }
        response = test_client.get("/api/plugins/inventory/nodes/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == [{"id": 1, "name": "n"}]
        mock_inventory_api_dep.get.assert_awaited_once_with("/", params={})

    def test_list_forwards_query_params_to_inventory(
        self, test_client, mock_inventory_api_dep
    ):
        """Ensure list route forwards query params to the inventory API."""
        mock_inventory_api_dep.get.return_value = {"items": [], "total": 0}
        response = test_client.get(
            "/api/plugins/inventory/nodes/",
            params={"limit": 10},
        )
        assert response.status_code == status.HTTP_200_OK
        mock_inventory_api_dep.get.assert_awaited_once_with(
            "/",
            params={"limit": "10"},
        )

    def test_unknown_entity_404(self, test_client, mock_inventory_api_dep):
        """Ensure GET on an unknown entity segment returns HTTP 404."""
        response = test_client.get("/api/plugins/inventory/unknown/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_create_service_forwards_to_node_services(
        self, test_client, mock_inventory_api_dep
    ):
        """Ensure POST ``/api/plugins/inventory/services/`` maps to ``/{node_id}/services/`` on inventory."""
        mock_inventory_api_dep.post.return_value = {"id": 2, "name": "svc"}
        response = test_client.post(
            "/api/plugins/inventory/services/",
            json={
                "node_id": _CREATE_SERVICE_TEST_NODE_ID,
                "name": "db",
                "type": "mysql",
            },
        )
        assert response.status_code == status.HTTP_200_OK
        mock_inventory_api_dep.post.assert_awaited_once()
        call_args = mock_inventory_api_dep.post.await_args
        assert call_args[0][0] == f"/{_CREATE_SERVICE_TEST_NODE_ID}/services/"
        assert call_args[1]["json"]["node_id"] == _CREATE_SERVICE_TEST_NODE_ID

    def test_create_service_invalid_node_id_returns_422(
        self, test_client, mock_inventory_api_dep
    ):
        """Ensure non-numeric ``node_id`` returns HTTP 422 and does not call inventory."""
        response = test_client.post(
            "/api/plugins/inventory/services/",
            json={
                "node_id": "abc",
                "name": "db",
                "type": "mysql",
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_inventory_api_dep.post.assert_not_called()

    def test_create_schema_requires_service_id(
        self, test_client, mock_inventory_api_dep
    ):
        """Ensure POST ``/api/plugins/inventory/schemas/`` without ``service_id`` returns HTTP 422."""
        response = test_client.post(
            "/api/plugins/inventory/schemas/",
            json={"name": "db1"},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.parametrize(
        ("raw_content", "content_type"),
        [
            (b"", "application/json"),
            (b"{not-json", "application/json"),
            (b"\xff", "application/json; charset=utf-8"),
        ],
    )
    def test_post_rejects_empty_or_malformed_json_body_with_422(
        self,
        test_client,
        mock_inventory_api_dep,
        raw_content: bytes,
        content_type: str,
    ) -> None:
        """Ensure invalid JSON on POST returns HTTP 422 and does not call inventory."""
        response = test_client.post(
            "/api/plugins/inventory/nodes/",
            content=raw_content,
            headers={"Content-Type": content_type},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert response.json()["detail"] == "JSON object body required"
        mock_inventory_api_dep.post.assert_not_called()

    def test_delete_returns_204(self, test_client, mock_inventory_api_dep):
        """Ensure DELETE ``/api/plugins/inventory/nodes/{id}`` returns HTTP 204 with an empty body."""
        mock_inventory_api_dep.delete.return_value = None
        response = test_client.delete("/api/plugins/inventory/nodes/3")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert response.content == b""
        mock_inventory_api_dep.delete.assert_awaited_once_with("/3")

    @pytest.mark.parametrize(
        ("entity", "item_id", "inventory_path"),
        [
            ("nodes", 3, "/3"),
            ("services", 9, "/services/9"),
            ("schemas", 11, "/schemas/11"),
            ("tables", 42, "/tables/42"),
        ],
    )
    def test_get_entity_detail_forwards_inventory_path(
        self,
        test_client,
        mock_inventory_api_dep,
        entity: str,
        item_id: int,
        inventory_path: str,
    ):
        """Ensure GET ``…/{entity}/{id}`` proxies to the inventory service detail path."""
        payload = {"id": item_id, "name": "x"}
        mock_inventory_api_dep.get.return_value = payload
        response = test_client.get(f"/api/plugins/inventory/{entity}/{item_id}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == payload
        mock_inventory_api_dep.get.assert_awaited_once_with(inventory_path)

    @pytest.mark.parametrize(
        ("entity", "item_id", "inventory_path"),
        [
            ("nodes", 3, "/3"),
            ("services", 9, "/services/9"),
            ("schemas", 11, "/schemas/11"),
            ("tables", 42, "/tables/42"),
        ],
    )
    def test_put_entity_detail_forwards_inventory_path_and_body(
        self,
        test_client,
        mock_inventory_api_dep,
        entity: str,
        item_id: int,
        inventory_path: str,
    ):
        """Ensure PUT ``…/{entity}/{id}`` forwards JSON to the inventory service detail path."""
        request_body = {"name": "updated"}
        updated = {"id": item_id, **request_body}
        mock_inventory_api_dep.put.return_value = updated
        response = test_client.put(
            f"/api/plugins/inventory/{entity}/{item_id}",
            json=request_body,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == updated
        mock_inventory_api_dep.put.assert_awaited_once_with(
            inventory_path,
            json=request_body,
        )

    def test_get_unknown_entity_detail_returns_404(
        self, test_client, mock_inventory_api_dep
    ):
        """Ensure GET on an unknown entity segment returns HTTP 404 before inventory."""
        response = test_client.get("/api/plugins/inventory/unknown/1")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_inventory_api_dep.get.assert_not_called()


def _mysql_service(service_id: int, address: str, port: int = 3306) -> dict:
    return {
        "id": service_id,
        "name": f"svc-{service_id}",
        "type": "mysql",
        "port": port,
        "node": {"id": service_id, "name": address, "address": address},
    }


class TestTopologyCollect:
    """Tests for ``POST /api/plugins/inventory/topology/collect``."""

    def test_dispatches_one_task_per_shard(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep
    ):
        """Ensure topology collect splits hosts across shards and dispatches run-python tasks."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value={
                "items": [
                    _mysql_service(1, "10.0.0.1"),
                    _mysql_service(2, "10.0.0.2"),
                    _mysql_service(3, "10.0.0.3"),
                ]
            }
        )
        mock_task_api_dep.get = AsyncMock(
            return_value={"executor-a": "1.1.1.1", "executor-b": "2.2.2.2"}
        )
        mock_task_api_dep.post = AsyncMock(side_effect=[{"id": 101}, {"id": 102}])

        response = test_client.post(
            "/api/plugins/inventory/topology/collect", json={"shards": 2}
        )

        expected_shard_count = 2
        expected_host_count = 3
        assert response.status_code == status.HTTP_202_ACCEPTED
        body = response.json()
        assert body["task_history_ids"] == [101, 102]
        assert body["shard_count"] == expected_shard_count
        assert body["host_count"] == expected_host_count
        assert mock_task_api_dep.post.await_count == expected_shard_count

    def test_returns_404_when_no_mysql_services_exist(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep
    ):
        """Ensure topology collect 404s when the inventory has no MySQL services."""
        mock_inventory_api_dep.get = AsyncMock(return_value={"items": []})
        mock_task_api_dep.get = AsyncMock(return_value={"executor-a": "1.1.1.1"})
        response = test_client.post("/api/plugins/inventory/topology/collect", json={})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_rejects_unknown_executor_host(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep
    ):
        """Ensure an explicit, unknown executor_host yields 400."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value={"items": [_mysql_service(1, "10.0.0.1")]}
        )
        mock_task_api_dep.get = AsyncMock(return_value={"executor-a": "1.1.1.1"})
        response = test_client.post(
            "/api/plugins/inventory/topology/collect",
            json={"executor_host": "missing"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


def _stdout_stream(stdout: str):
    """Return an async-iterator factory producing the framed log stream."""

    async def _stream(_path, params=None):
        yield json.dumps({"type": "stdout", "msg": stdout}).encode("utf-8")

    return _stream


class TestTopologyResult:
    """Tests for ``GET /api/plugins/inventory/topology/result``."""

    def test_running_status_when_any_task_pending(self, test_client, mock_task_api_dep):
        """Ensure result endpoint reports ``running`` while any task is unfinished."""
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                {"id": 1, "status": "success"},
                {"id": 2, "status": "running"},
            ]
        )
        response = test_client.get(
            "/api/plugins/inventory/topology/result", params={"ids": "1,2"}
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status"] == "running"
        assert body["pending_task_ids"] == [2]
        assert body["graph"] is None

    @pytest.mark.parametrize("terminal_status", ["failed", "lost", "stopped", "stale"])
    def test_terminal_failure_with_no_stdout_returns_failed(
        self, test_client, mock_task_api_dep, terminal_status: str
    ):
        """Ensure unsuccessful terminal tasks with no graph data do not report ``ok``."""
        mock_task_api_dep.get = AsyncMock(
            return_value={"id": 9, "status": terminal_status}
        )
        mock_task_api_dep.stream = _stdout_stream("")

        response = test_client.get(
            "/api/plugins/inventory/topology/result", params={"ids": "9"}
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status"] == "failed"
        assert body["pending_task_ids"] == []
        assert body["graph"]["nodes"] == []

    def test_invalid_ids_yields_400(self, test_client, mock_task_api_dep):
        """Ensure non-integer ids in the query string return HTTP 400."""
        response = test_client.get(
            "/api/plugins/inventory/topology/result", params={"ids": "abc"}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_ids_yields_422(self, test_client, mock_task_api_dep):
        """Ensure the ids query parameter is required."""
        response = test_client.get("/api/plugins/inventory/topology/result")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
