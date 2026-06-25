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

"""Tests for the SEP periodic-task JSON proxy at ``/api/sep/periodic-tasks/``."""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

ROUTE_CASES = [
    pytest.param("get", "/api/sep/periodic-tasks/", "get", None, id="list"),
    pytest.param("post", "/api/sep/periodic-tasks/my-task/", "post", {}, id="create"),
    pytest.param("put", "/api/sep/periodic-tasks/42", "put", {}, id="update"),
    pytest.param("delete", "/api/sep/periodic-tasks/42", "delete", None, id="delete"),
]

MUTATION_CASES = [
    pytest.param("post", "/api/sep/periodic-tasks/my-task/", "post", {}, id="create"),
    pytest.param("put", "/api/sep/periodic-tasks/42", "put", {}, id="update"),
    pytest.param("delete", "/api/sep/periodic-tasks/42", "delete", None, id="delete"),
]


def _issue(
    client: TestClient,
    http_method: str,
    url: str,
    json_body: dict[str, Any] | None,
):
    """Issue ``http_method`` to ``url``, attaching ``json_body`` when present."""
    kwargs = {} if json_body is None else {"json": json_body}
    return client.request(http_method.upper(), url, **kwargs)


class TestSepPeriodicTasksEndpoint:
    """Tests for the periodic-task CRUD proxy happy paths."""

    def test_list_returns_upstream_payload(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Forward the upstream periodic-task list unchanged."""
        payload = [{"id": 1, "name": "run_x"}, {"id": 2, "name": "run_y"}]
        mock_task_api_dep.get.return_value = payload
        response = test_client.get("/api/sep/periodic-tasks/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == payload
        mock_task_api_dep.get.assert_awaited_once_with("/periodic/")

    def test_list_empty_upstream_returns_empty_list(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Return ``[]`` for an empty upstream list."""
        mock_task_api_dep.get.return_value = []
        response = test_client.get("/api/sep/periodic-tasks/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_list_non_list_upstream_coerced_to_empty(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Coerce a non-list upstream payload (e.g. ``None`` on 204) to ``[]``."""
        mock_task_api_dep.get.return_value = None
        response = test_client.get("/api/sep/periodic-tasks/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_create_forwards_body_and_returns_201(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Forward the create body verbatim to the task-scoped upstream path."""
        body = {"period": 5, "kwargs": "{}"}
        upstream = {"id": 9, "name": "run_x", **body}
        mock_task_api_dep.post.return_value = upstream
        response = test_client.post("/api/sep/periodic-tasks/my-task/", json=body)
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json() == upstream
        mock_task_api_dep.post.assert_awaited_once_with("/my-task/periodic/", json=body)

    def test_update_forwards_body(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Forward the full-replacement update body to ``/periodic/{id}``."""
        body = {"period": 10, "kwargs": "{}"}
        upstream = {"id": 42, **body}
        mock_task_api_dep.put.return_value = upstream
        response = test_client.put("/api/sep/periodic-tasks/42", json=body)
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == upstream
        mock_task_api_dep.put.assert_awaited_once_with("/periodic/42", json=body)

    def test_delete_returns_204_empty_body(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Return ``204`` with an empty body on deletion."""
        mock_task_api_dep.delete.return_value = None
        response = test_client.delete("/api/sep/periodic-tasks/42")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert response.content == b""
        mock_task_api_dep.delete.assert_awaited_once_with("/periodic/42")


@pytest.mark.parametrize(("http_method", "url", "mock_attr", "json_body"), ROUTE_CASES)
class TestSepPeriodicTasksErrorSplit:
    """The 4xx-passthrough / 5xx-502 error split applies to every periodic route."""

    @pytest.mark.parametrize(
        "upstream_status",
        [
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_404_NOT_FOUND,
            status.HTTP_409_CONFLICT,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        ],
    )
    def test_upstream_client_error_passes_through(
        self,
        test_client: TestClient,
        mock_task_api_dep: AsyncMock,
        http_method: str,
        url: str,
        mock_attr: str,
        json_body: dict[str, Any] | None,
        upstream_status: int,
    ) -> None:
        """Return an upstream client error (< 500) unchanged with its status and ``detail``."""
        getattr(mock_task_api_dep, mock_attr).side_effect = HTTPException(
            status_code=upstream_status, detail="upstream detail"
        )
        response = _issue(test_client, http_method, url, json_body)
        assert response.status_code == upstream_status
        assert response.json() == {"detail": "upstream detail"}

    @pytest.mark.parametrize(
        "upstream_status",
        [status.HTTP_500_INTERNAL_SERVER_ERROR, status.HTTP_503_SERVICE_UNAVAILABLE],
    )
    def test_upstream_server_error_becomes_502(
        self,
        test_client: TestClient,
        mock_task_api_dep: AsyncMock,
        http_method: str,
        url: str,
        mock_attr: str,
        json_body: dict[str, Any] | None,
        upstream_status: int,
    ) -> None:
        """Fail the proxy with ``502`` on an upstream server error (>= 500)."""
        getattr(mock_task_api_dep, mock_attr).side_effect = HTTPException(
            status_code=upstream_status, detail="tasks down"
        )
        response = _issue(test_client, http_method, url, json_body)
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.json() == {"detail": "tasks down"}

    def test_upstream_oserror_becomes_502(
        self,
        test_client: TestClient,
        mock_task_api_dep: AsyncMock,
        http_method: str,
        url: str,
        mock_attr: str,
        json_body: dict[str, Any] | None,
    ) -> None:
        """Fail the proxy with ``502`` on a connection-level ``OSError``."""
        getattr(mock_task_api_dep, mock_attr).side_effect = OSError(
            "connection refused"
        )
        response = _issue(test_client, http_method, url, json_body)
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.json() == {"detail": "connection refused"}


class TestSepPeriodicTasksAuth:
    """Tests for ``/api/sep/periodic-tasks/`` authentication enforcement."""

    def test_unauthenticated_returns_json_401(
        self, unauthenticated_client: TestClient
    ) -> None:
        """Reject anonymous requests with a JSON 401 response."""
        response = unauthenticated_client.get(
            "/api/sep/periodic-tasks/", follow_redirects=False
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["content-type"].startswith("application/json")
        assert "detail" in response.json()

    @pytest.mark.parametrize(
        ("http_method", "url", "mock_attr", "json_body"), MUTATION_CASES
    )
    def test_cookie_only_mutation_unauthorized(
        self,
        api_admin_client_no_bearer: TestClient,
        mock_task_api_dep: AsyncMock,
        http_method: str,
        url: str,
        mock_attr: str,
        json_body: dict[str, Any] | None,
    ) -> None:
        """Reject a cookie-only mutation that lacks a Bearer token with 401."""
        response = _issue(api_admin_client_no_bearer, http_method, url, json_body)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        getattr(mock_task_api_dep, mock_attr).assert_not_awaited()

    def test_cookie_only_get_allowed(
        self, api_admin_client_no_bearer: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Allow a cookie-only GET: the Bearer gate covers mutations only."""
        mock_task_api_dep.get.return_value = []
        response = api_admin_client_no_bearer.get("/api/sep/periodic-tasks/")
        assert response.status_code == status.HTTP_200_OK
