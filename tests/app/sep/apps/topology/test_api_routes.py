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

"""Tests for the Topology plugin JSON API under ``/api/apps/topology/``.

App enablement is exercised generically by the framework's
``require_app_enabled`` suite; ``test_client`` reads an empty ``appstate``
table (every app enabled), so these tests focus on the collect/result
behaviour rather than the enable/disable gate.
"""

from __future__ import annotations

import json

import pytest
from fastapi import status

from app.inventory.constants import DEFAULT_MYSQL_PORT
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.topology.models import MAX_TOPOLOGY_SHARDS
from app.sep.apps.topology.topology import TOPOLOGY_JOB_PREFIX


def _mysql_service(
    service_id: int, address: str, port: int = DEFAULT_MYSQL_PORT
) -> dict:
    return {
        "id": service_id,
        "name": f"svc-{service_id}",
        "type": ServiceTypeEnum.MYSQL.value,
        "port": port,
        "node": {"id": service_id, "name": address, "address": address},
    }


def _topology_history(history_id: int, status_value: str, user_id: str) -> dict:
    return {
        "id": history_id,
        "status": status_value,
        "executed_by": user_id,
        "execution_request": {
            "task": "run-python",
            "meta": {"_job_id_prefix": TOPOLOGY_JOB_PREFIX},
        },
    }


class TestTopologyCollect:
    """Tests for ``POST /api/apps/topology/collect``."""

    def test_dispatches_one_task_per_shard(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep
    ):
        """Ensure topology collect splits hosts across shards and dispatches run-python tasks."""
        mock_inventory_api_dep.get.return_value = {
            "items": [
                _mysql_service(1, "10.0.0.1"),
                _mysql_service(2, "10.0.0.2"),
                _mysql_service(3, "10.0.0.3"),
            ]
        }
        mock_task_api_dep.get.return_value = {
            "executor-a": "1.1.1.1",
            "executor-b": "2.2.2.2",
        }
        mock_task_api_dep.post.side_effect = [{"id": 101}, {"id": 102}]

        response = test_client.post(
            "/api/apps/topology/collect", json={"shards": 2}
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
        mock_inventory_api_dep.get.return_value = {"items": []}
        mock_task_api_dep.get.return_value = {"executor-a": "1.1.1.1"}
        response = test_client.post("/api/apps/topology/collect", json={})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_rejects_unknown_executor_host(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep
    ):
        """Ensure an explicit, unknown executor_host yields 400."""
        mock_inventory_api_dep.get.return_value = {
            "items": [_mysql_service(1, "10.0.0.1")]
        }
        mock_task_api_dep.get.return_value = {"executor-a": "1.1.1.1"}
        response = test_client.post(
            "/api/apps/topology/collect",
            json={"executor_host": "missing"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_rejects_executor_host_with_multiple_shards(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep
    ):
        """Ensure explicit executor mode cannot silently ignore shards."""
        response = test_client.post(
            "/api/apps/topology/collect",
            json={"executor_host": "executor-a", "shards": 4},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert "executor_host requires shards=1" in response.text
        mock_inventory_api_dep.get.assert_not_called()
        mock_task_api_dep.post.assert_not_called()

    @pytest.mark.parametrize("hosts_payload", [None, []])
    def test_rejects_invalid_executor_hosts_payload(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep, hosts_payload
    ):
        """Ensure malformed Tasks API hosts payloads produce a friendly 502."""
        mock_inventory_api_dep.get.return_value = {
            "items": [_mysql_service(1, "10.0.0.1")]
        }
        mock_task_api_dep.get.return_value = hosts_payload

        response = test_client.post("/api/apps/topology/collect", json={})

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.json()["detail"] == (
            "Tasks API returned an invalid executor hosts payload."
        )


def _stdout_stream(stdout: str):
    """Return an async-iterator factory producing the framed log stream."""

    async def _stream(_path, params=None):
        yield json.dumps({"type": "stdout", "msg": stdout}).encode("utf-8")

    return _stream


def _host_done_stdout(host: str) -> str:
    return json.dumps(
        {
            "event": "host_done",
            "host": host,
            "data": {
                "address": host.rsplit(":", 1)[0],
                "port": DEFAULT_MYSQL_PORT,
                "server": {"server_hash": f"hash-{host}", "server_id": 1},
                "replication": {},
                "cluster": {},
                "gtid_mode": "",
            },
        }
    )


class TestTopologyResult:
    """Tests for ``GET /api/apps/topology/result``."""

    def test_running_status_when_any_task_pending(
        self, test_client, mock_task_api_dep, regular_user
    ):
        """Ensure result endpoint reports ``running`` while any task is unfinished."""
        user_id = str(regular_user.id)
        mock_task_api_dep.get.side_effect = [
            _topology_history(1, "success", user_id),
            _topology_history(2, "running", user_id),
        ]
        response = test_client.get(
            "/api/apps/topology/result", params={"ids": "1,2"}
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status"] == "running"
        assert body["pending_task_ids"] == [2]
        assert body["graph"] is None

    @pytest.mark.parametrize("terminal_status", ["failed", "lost", "stopped", "stale"])
    def test_terminal_failure_with_no_stdout_returns_failed(
        self, test_client, mock_task_api_dep, regular_user, terminal_status: str
    ):
        """Ensure unsuccessful terminal tasks with no graph data do not report ``ok``."""
        mock_task_api_dep.get.return_value = _topology_history(
            9, terminal_status, str(regular_user.id)
        )
        mock_task_api_dep.stream = _stdout_stream("")

        response = test_client.get(
            "/api/apps/topology/result", params={"ids": "9"}
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status"] == "failed"
        assert body["pending_task_ids"] == []
        assert body["failed_task_ids"] == [9]
        assert body["graph"]["nodes"] == []

    def test_partial_shard_failure_returns_failed_task_ids(
        self, test_client, mock_task_api_dep, regular_user
    ):
        """Ensure whole-shard failures remain visible when other shards return a graph."""
        user_id = str(regular_user.id)
        mock_task_api_dep.get.side_effect = [
            _topology_history(1, "success", user_id),
            _topology_history(2, "failed", user_id),
        ]

        async def _stream(path, params=None):
            if "/history/1/" in path:
                yield json.dumps(
                    {"type": "stdout", "msg": _host_done_stdout("h1:3306")}
                ).encode("utf-8")

        mock_task_api_dep.stream = _stream

        response = test_client.get(
            "/api/apps/topology/result", params={"ids": "1,2"}
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status"] == "ok"
        assert body["failed_task_ids"] == [2]
        assert body["graph"]["nodes"]

    def test_rejects_too_many_ids(self, test_client, mock_task_api_dep):
        """Ensure the result endpoint caps task fan-out."""
        ids = ",".join(str(i) for i in range(1, MAX_TOPOLOGY_SHARDS + 2))
        response = test_client.get(
            "/api/apps/topology/result", params={"ids": ids}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "task history ids are allowed" in response.text
        mock_task_api_dep.get.assert_not_called()

    def test_rejects_other_users_task_history(self, test_client, mock_task_api_dep):
        """Ensure the result endpoint does not expose another user's task output."""
        mock_task_api_dep.get.return_value = _topology_history(
            77, "success", "other-user-id"
        )
        response = test_client.get(
            "/api/apps/topology/result", params={"ids": "77"}
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Task history is not accessible" in response.text
        mock_task_api_dep.stream.assert_not_called()

    def test_rejects_non_topology_task_history(
        self, test_client, mock_task_api_dep, regular_user
    ):
        """Ensure guessed non-topology task ids cannot be reused by topology result."""
        history = _topology_history(77, "success", str(regular_user.id))
        history["execution_request"]["meta"]["_job_id_prefix"] = "backup"
        mock_task_api_dep.get.return_value = history
        response = test_client.get(
            "/api/apps/topology/result", params={"ids": "77"}
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Task history is not accessible" in response.text
        mock_task_api_dep.stream.assert_not_called()

    def test_invalid_ids_yields_400(self, test_client, mock_task_api_dep):
        """Ensure non-integer ids in the query string return HTTP 400."""
        response = test_client.get(
            "/api/apps/topology/result", params={"ids": "abc"}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_ids_yields_422(self, test_client, mock_task_api_dep):
        """Ensure the ids query parameter is required."""
        response = test_client.get("/api/apps/topology/result")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
