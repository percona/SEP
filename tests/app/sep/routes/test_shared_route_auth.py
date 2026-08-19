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

"""Pin the auth contract of the three surviving non-``/api`` routers.

``/files``, ``/stream-logs`` and ``/execution-events`` used to authenticate via
the session cookie and answer a cookie failure with a 303 to the login page.
They now ride ``IsApiAuthenticated``, so a caller without a Bearer token gets a
structured 401 and a stale session cookie authenticates nothing. The SPA already
sends ``Authorization: Bearer`` on all three (``useTaskFileDownload.ts`` via
``apiClient``; the two event streams via ``@microsoft/fetch-event-source``), so
this is the contract its clients rely on. This module also pins the team-wide
read contract for task-history routes.
"""

from contextlib import contextmanager
from unittest.mock import AsyncMock

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from starlette.status import HTTP_200_OK, HTTP_404_NOT_FOUND

from app.core.requests import RemoteAPI
from app.sep.deps import get_tasks_api, get_tasks_client
from app.sep.main import sep_app

SHARED_ROUTES = [
    "/files/1",
    "/files/1/download",
    "/stream-logs/1",
    "/stream-logs/1/execution-events",
    "/execution-events/1",
]


@pytest.fixture
def anonymous_client() -> TestClient:
    """Yield a client with every authentication override cleared."""
    previous = sep_app.dependency_overrides
    sep_app.dependency_overrides = {}
    try:
        yield TestClient(sep_app, raise_server_exceptions=False)
    finally:
        sep_app.dependency_overrides = previous


@pytest.mark.parametrize("route", SHARED_ROUTES)
def test_no_credentials_returns_401(anonymous_client: TestClient, route: str) -> None:
    """Return a 401, never a 303 redirect, when no credentials are presented."""
    response = anonymous_client.get(route, follow_redirects=False)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.parametrize("route", SHARED_ROUTES)
def test_session_cookie_only_returns_401(
    anonymous_client: TestClient, route: str
) -> None:
    """Return a 401 for a cookie-only caller: the cookie is no longer read."""
    response = anonymous_client.get(
        route, cookies={"authToken": "stale-value"}, follow_redirects=False
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def _query_param_names(spec: dict, path: str) -> set[str]:
    """Return query-parameter names declared on a path's GET operation."""
    params = spec["paths"][path]["get"].get("parameters") or []
    return {p["name"] for p in params if p.get("in") == "query"}


async def _empty_bytes():
    """Yield no chunks."""
    return
    yield  # pragma: no cover — keep this an async generator


@pytest.fixture
def other_user_task_history(test_client, task_history_response):
    """Serve a BACKUPS history executed by alice through the real get_task_history.

    Override TaskAPI and TasksClient only. Leave get_task_history unresolved so
    the owner query parameter, if still declared, still reaches the dependency.
    """
    task_history_response.task.owner = "BACKUPS"
    task_history_response.executed_by = "alice"
    history_id = task_history_response.id
    history_dump = task_history_response.model_dump(mode="json")

    async def api_get(path: str, **_kwargs):
        if path == f"/history/{history_id}":
            return history_dump
        if path == f"/history/{history_id}/files/":
            return {}
        if path == f"/history/{history_id}/events":
            return []
        raise AssertionError(f"unexpected TaskAPI GET {path}")

    tasks_api = AsyncMock(spec=RemoteAPI)
    tasks_api.get.side_effect = api_get
    tasks_api.stream_chunks.return_value = _empty_bytes()

    @contextmanager
    def auth(_token: str):
        yield tasks_api

    tasks_client = AsyncMock(spec=RemoteAPI)
    tasks_client.auth = auth
    tasks_client.get.side_effect = api_get
    tasks_client.stream.side_effect = lambda *_a, **_k: _empty_bytes()
    tasks_client.stream_chunks.return_value = _empty_bytes()
    tasks_client.post.return_value = history_dump

    previous = dict(sep_app.dependency_overrides)
    sep_app.dependency_overrides[get_tasks_api] = lambda: tasks_api
    sep_app.dependency_overrides[get_tasks_client] = lambda: tasks_client
    try:
        yield task_history_response
    finally:
        sep_app.dependency_overrides.clear()
        sep_app.dependency_overrides.update(previous)


@pytest.mark.parametrize("route", SHARED_ROUTES)
def test_owner_is_not_a_query_parameter(test_client, route: str) -> None:
    """Omit owner from the published schema of every task-history read route."""
    spec = test_client.get("/openapi.json").json()
    template = route.replace("/1", "/{task_history_id}")
    assert "owner" not in _query_param_names(spec, template)


@pytest.mark.parametrize("route", SHARED_ROUTES)
def test_owner_query_does_not_hide_history(
    test_client, other_user_task_history, route: str
) -> None:
    """Answer ?owner= from the history itself, even when executed_by differs."""
    history_id = other_user_task_history.id
    path = route.replace("/1", f"/{history_id}")
    response = test_client.get(f"{path}?owner=ALTERS")

    assert response.status_code != HTTP_404_NOT_FOUND
    assert response.status_code == HTTP_200_OK
