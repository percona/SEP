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

"""Tests for the PMM Extensions periodic-task JSON proxy at ``/api/extensions/periodic-tasks/``."""

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock
from urllib.parse import quote

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from app.core.exceptions import HTTPNotFoundException
from app.core.pagination import DEFAULT_PAGINATION_LIMIT, DEFAULT_PAGINATION_OFFSET
from app.extensions.apps.backup_mongo.restore.models import OWNER as RESTORE_MONGO_OWNER
from app.extensions.apps.mysql_backups.forms import OWNER as BACKUPS_OWNER
from app.extensions.apps.mysql_backups.restore.models import OWNER as RESTORES_OWNER
from app.tasks.models import ANY_OWNER
from tests.app.extensions.path_unsafe_task_names import (
    PATH_PARAM_UNSAFE_TASKS,
    PATH_UNSAFE_TASKS,
)
from tests.app.factories import TaskResponseFactory

PREVIEW_CASE = pytest.param(
    "post", "/api/extensions/periodic-tasks/schedule/preview/", "post", {}, id="preview"
)

ROUTE_CASES = [
    pytest.param("get", "/api/extensions/periodic-tasks/", "get", None, id="list"),
    pytest.param(
        "post", "/api/extensions/periodic-tasks/my-task/", "post", {}, id="create"
    ),
    pytest.param("put", "/api/extensions/periodic-tasks/42", "put", {}, id="update"),
    pytest.param(
        "delete", "/api/extensions/periodic-tasks/42", "delete", None, id="delete"
    ),
    PREVIEW_CASE,
]

MUTATION_CASES = [
    pytest.param(
        "post", "/api/extensions/periodic-tasks/my-task/", "post", {}, id="create"
    ),
    pytest.param("put", "/api/extensions/periodic-tasks/42", "put", {}, id="update"),
    pytest.param(
        "delete", "/api/extensions/periodic-tasks/42", "delete", None, id="delete"
    ),
    PREVIEW_CASE,
]

PROXY_PAGE_OFFSET = 10
PROXY_PAGE_LIMIT = 5
PROXY_PAGE_TOTAL = 2


def _empty_envelope(
    *,
    offset: int = DEFAULT_PAGINATION_OFFSET,
    limit: int = DEFAULT_PAGINATION_LIMIT,
) -> dict[str, Any]:
    """Build an empty paginated envelope echoing the requested window."""
    return {"items": [], "total": 0, "offset": offset, "limit": limit}


def _issue(
    client: TestClient,
    http_method: str,
    url: str,
    json_body: dict[str, Any] | None,
):
    """Issue ``http_method`` to ``url``, attaching ``json_body`` when present."""
    kwargs = {} if json_body is None else {"json": json_body}
    return client.request(http_method.upper(), url, **kwargs)


class TestExtensionsPeriodicTasksEndpoint:
    """Tests for the periodic-task CRUD proxy happy paths."""

    def test_list_returns_upstream_payload(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Forward the upstream paginated envelope unchanged."""
        payload = {
            "items": [{"id": 1, "name": "run_x"}, {"id": 2, "name": "run_y"}],
            "total": PROXY_PAGE_TOTAL,
            "offset": DEFAULT_PAGINATION_OFFSET,
            "limit": DEFAULT_PAGINATION_LIMIT,
        }
        mock_task_api_dep.get.return_value = payload
        response = test_client.get("/api/extensions/periodic-tasks/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == payload
        mock_task_api_dep.get.assert_awaited_once_with(
            "/periodic/",
            params={
                "offset": DEFAULT_PAGINATION_OFFSET,
                "limit": DEFAULT_PAGINATION_LIMIT,
            },
        )

    def test_list_forwards_offset_and_limit(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Forward client offset/limit to the upstream periodic-task list."""
        payload = {
            "items": [{"id": 1, "name": "run_x"}],
            "total": PROXY_PAGE_TOTAL,
            "offset": PROXY_PAGE_OFFSET,
            "limit": PROXY_PAGE_LIMIT,
        }
        mock_task_api_dep.get.return_value = payload
        response = test_client.get(
            "/api/extensions/periodic-tasks/",
            params={"offset": PROXY_PAGE_OFFSET, "limit": PROXY_PAGE_LIMIT},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == payload
        mock_task_api_dep.get.assert_awaited_once_with(
            "/periodic/",
            params={"offset": PROXY_PAGE_OFFSET, "limit": PROXY_PAGE_LIMIT},
        )

    def test_list_preserves_last_run_status(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Forward the upstream ``last_run_status`` field through the proxy."""
        payload = {
            "items": [
                {"id": 1, "name": "run_x", "last_run_status": "success"},
                {"id": 2, "name": "run_y", "last_run_status": None},
            ],
            "total": PROXY_PAGE_TOTAL,
            "offset": DEFAULT_PAGINATION_OFFSET,
            "limit": DEFAULT_PAGINATION_LIMIT,
        }
        mock_task_api_dep.get.return_value = payload
        response = test_client.get("/api/extensions/periodic-tasks/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == payload

    def test_list_empty_upstream_returns_empty_envelope(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Return an empty envelope when upstream has no rows."""
        payload = _empty_envelope()
        mock_task_api_dep.get.return_value = payload
        response = test_client.get("/api/extensions/periodic-tasks/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == payload

    def test_list_non_dict_upstream_coerced_to_empty(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Coerce a non-dict upstream payload to an empty envelope."""
        mock_task_api_dep.get.return_value = None
        response = test_client.get("/api/extensions/periodic-tasks/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == _empty_envelope()

    @pytest.mark.usefixtures("schedulable_upstream_task")
    def test_create_forwards_body_and_returns_201(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Forward the create body verbatim to the task-scoped upstream path."""
        body = {"period": 5, "kwargs": "{}"}
        upstream = {"id": 9, "name": "run_x", **body}
        mock_task_api_dep.post.return_value = upstream
        response = test_client.post(
            "/api/extensions/periodic-tasks/my-task/", json=body
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json() == upstream
        mock_task_api_dep.post.assert_awaited_once_with("/my-task/periodic/", json=body)

    @pytest.mark.usefixtures("schedulable_upstream_task")
    def test_update_forwards_body(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Forward the full-replacement update body to ``/periodic/{id}``."""
        body = {"period": 10, "kwargs": "{}"}
        upstream = {"id": 42, **body}
        mock_task_api_dep.put.return_value = upstream
        response = test_client.put("/api/extensions/periodic-tasks/42", json=body)
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == upstream
        mock_task_api_dep.put.assert_awaited_once_with("/periodic/42", json=body)

    def test_preview_forwards_body_to_the_schedule_preview_path(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Forward the preview body verbatim and return the upstream payload."""
        body = {"interval": {"every": 30, "period": "minutes"}}
        upstream = {
            "timezone": "UTC",
            "next_run_at": "2026-09-08T00:30:00Z",
            "next_runs": ["2026-09-08T00:30:00Z"],
        }
        mock_task_api_dep.post.return_value = upstream
        response = test_client.post(
            "/api/extensions/periodic-tasks/schedule/preview/", json=body
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == upstream
        mock_task_api_dep.post.assert_awaited_once_with(
            "/periodic/schedule/preview/", json=body
        )

    def test_a_task_named_preview_still_creates_normally(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Assert the two-segment preview path reserves no task name.

        A single-segment ``/preview/`` would be ambiguous with the sibling
        ``POST /{task_name}/``, making ``preview`` unschedulable through the
        proxy. Two segments remove the collision structurally.
        """
        body = {"interval": {"every": 30, "period": "minutes"}}
        upstream = {"id": 9, "name": "run_preview"}
        mock_task_api_dep.get.return_value = _task_payload("preview", BACKUPS_OWNER)
        mock_task_api_dep.post.return_value = upstream
        response = test_client.post(
            "/api/extensions/periodic-tasks/preview/", json=body
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json() == upstream
        mock_task_api_dep.post.assert_awaited_once_with("/preview/periodic/", json=body)

    def test_delete_returns_204_empty_body(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Return ``204`` with an empty body on deletion."""
        mock_task_api_dep.delete.return_value = None
        response = test_client.delete("/api/extensions/periodic-tasks/42")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert response.content == b""
        mock_task_api_dep.delete.assert_awaited_once_with("/periodic/42")


@pytest.mark.usefixtures("schedulable_upstream_task")
@pytest.mark.parametrize(("http_method", "url", "mock_attr", "json_body"), ROUTE_CASES)
class TestExtensionsPeriodicTasksErrorSplit:
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


class TestExtensionsPeriodicTasksAuth:
    """Cover ``/api/extensions/periodic-tasks/`` authentication enforcement."""

    def test_unauthenticated_returns_json_401(
        self, unauthenticated_client: TestClient
    ) -> None:
        """Reject anonymous requests with a JSON 401 response."""
        response = unauthenticated_client.get(
            "/api/extensions/periodic-tasks/", follow_redirects=False
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
        """Reject a cookie-only mutation that lacks a Bearer token with 401.

        The router-level gate resolves before the route's scheduling guard, so an
        unauthenticated mutation reaches no upstream read at all.
        """
        response = _issue(api_admin_client_no_bearer, http_method, url, json_body)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        getattr(mock_task_api_dep, mock_attr).assert_not_awaited()
        mock_task_api_dep.get.assert_not_awaited()

    def test_cookie_only_get_allowed(
        self, api_admin_client_no_bearer: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Allow a cookie-only GET: the Bearer gate covers mutations only."""
        mock_task_api_dep.get.return_value = _empty_envelope()
        response = api_admin_client_no_bearer.get("/api/extensions/periodic-tasks/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == _empty_envelope()


GUARD_READ_CASES = [
    pytest.param(
        "post", "/api/extensions/periodic-tasks/my-task/", "post", {}, id="create"
    ),
    pytest.param(
        "put", "/api/extensions/periodic-tasks/42", "put", {"task": ""}, id="update"
    ),
]

NON_STRING_TASKS = [None, 5, 0, False, [], {}, ["r1"]]


def _task_payload(name: str, owner: str) -> dict[str, Any]:
    """Build the upstream JSON for a task named ``name`` owned by ``owner``."""
    return TaskResponseFactory.build(name=name, owner=owner).model_dump(mode="json")


def _schedule_payload(task_name: str) -> dict[str, Any]:
    """Build the upstream JSON of a stored schedule running ``task_name``."""
    return {"id": 42, "name": "nightly", "task": task_name}


def _get_by_path(responses: dict[str, Any]) -> Callable[..., Any]:
    """Return an upstream ``get`` side effect answering per requested path."""

    def _get(path: str, **_kwargs: Any) -> Any:
        return responses[path]

    return _get


@pytest.fixture
def schedulable_upstream_task(mock_task_api_dep: AsyncMock) -> AsyncMock:
    """Answer every upstream read with a schedulable task the guard admits.

    The payload doubles as the stored schedule the update guard falls back to, so
    a body carrying no ``task`` resolves to the same allowed task.
    """
    mock_task_api_dep.get.return_value = _task_payload("my-task", BACKUPS_OWNER) | {
        "task": "my-task"
    }
    return mock_task_api_dep


@pytest.mark.usefixtures("schedulable_upstream_task")
class TestExtensionsPeriodicTasksSchedulingGuard:
    """Cover the gateway refusing a schedule whose task app offers no scheduling."""

    def test_create_refuses_a_mysql_restore_task(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Refuse creating a schedule for a MySQL restore with ``400``."""
        mock_task_api_dep.get.return_value = _task_payload("r1", RESTORES_OWNER)

        response = test_client.post("/api/extensions/periodic-tasks/r1/", json={})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_task_api_dep.post.assert_not_awaited()
        mock_task_api_dep.get.assert_awaited_once_with("/r1")

    def test_create_refuses_a_mongodb_restore_task(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Refuse creating a schedule for a MongoDB restore with ``400``."""
        mock_task_api_dep.get.return_value = _task_payload("m1", RESTORE_MONGO_OWNER)

        response = test_client.post("/api/extensions/periodic-tasks/m1/", json={})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_task_api_dep.post.assert_not_awaited()

    def test_create_accepts_a_mysql_backup_task(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Forward a schedule whose task belongs to an app offering scheduling."""
        body = {"period": 5, "kwargs": "{}"}
        mock_task_api_dep.get.return_value = _task_payload("b1", BACKUPS_OWNER)
        mock_task_api_dep.post.return_value = {"id": 9, **body}

        response = test_client.post("/api/extensions/periodic-tasks/b1/", json=body)

        assert response.status_code == status.HTTP_201_CREATED
        mock_task_api_dep.post.assert_awaited_once_with("/b1/periodic/", json=body)

    def test_create_refuses_a_task_with_an_unregistered_owner(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Fail closed for an owner no registered app claims."""
        mock_task_api_dep.get.return_value = _task_payload(
            "x1", "NOT_A_REGISTERED_OWNER"
        )

        response = test_client.post("/api/extensions/periodic-tasks/x1/", json={})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_task_api_dep.post.assert_not_awaited()

    def test_create_refuses_an_any_owner_task(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Fail closed for an unclaimed task defaulting to ``ANY_OWNER``."""
        mock_task_api_dep.get.return_value = _task_payload("inventory-sync", ANY_OWNER)

        response = test_client.post(
            "/api/extensions/periodic-tasks/inventory-sync/", json={}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_task_api_dep.post.assert_not_awaited()

    @pytest.mark.parametrize("task", PATH_PARAM_UNSAFE_TASKS)
    def test_create_refuses_a_task_name_that_is_not_one_path_segment(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock, task: str
    ) -> None:
        """Refuse a path task name that would restructure the upstream request URL.

        The create route reads the task through the same ``GET /{task_name}`` the
        update route does, so it refuses the same names. Each is sent
        percent-encoded, which is the only way such a name survives as one path
        segment; Starlette decodes it back before the guard sees it.
        """
        segment = quote(task, safe="")

        response = test_client.post(
            f"/api/extensions/periodic-tasks/{segment}/", json={}
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        mock_task_api_dep.get.assert_not_awaited()
        mock_task_api_dep.post.assert_not_awaited()

    def test_create_unknown_task_returns_upstream_404(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Pass the upstream ``404`` for an unknown task through unchanged."""
        mock_task_api_dep.get.side_effect = HTTPNotFoundException()

        response = test_client.post("/api/extensions/periodic-tasks/nope/", json={})

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_task_api_dep.post.assert_not_awaited()

    def test_update_refuses_editing_a_mysql_restore_schedule(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Refuse every edit of a restore schedule, a disable-only one included."""
        mock_task_api_dep.get.return_value = _task_payload("r1", RESTORES_OWNER)

        response = test_client.put(
            "/api/extensions/periodic-tasks/42", json={"task": "r1", "enabled": False}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_task_api_dep.put.assert_not_awaited()

    def test_update_refuses_repointing_a_backup_schedule_at_a_restore_task(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Guard on the task the body names, without reading the stored schedule."""
        mock_task_api_dep.get.side_effect = _get_by_path(
            {
                "/periodic/42": _schedule_payload("b1"),
                "/r1": _task_payload("r1", RESTORES_OWNER),
            }
        )

        response = test_client.put(
            "/api/extensions/periodic-tasks/42", json={"task": "r1", "enabled": True}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_task_api_dep.put.assert_not_awaited()
        mock_task_api_dep.get.assert_awaited_once_with("/r1")

    def test_update_falls_back_to_the_existing_schedule_task(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Resolve an empty body ``task`` from the stored schedule, as Tasks does."""
        mock_task_api_dep.get.side_effect = _get_by_path(
            {
                "/periodic/42": _schedule_payload("r1"),
                "/r1": _task_payload("r1", RESTORES_OWNER),
            }
        )

        response = test_client.put(
            "/api/extensions/periodic-tasks/42", json={"task": "", "enabled": True}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_task_api_dep.put.assert_not_awaited()

    def test_update_accepts_a_backup_schedule(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Forward an update whose task belongs to an app offering scheduling."""
        body = {"task": "b1", "period": 10}
        mock_task_api_dep.get.return_value = _task_payload("b1", BACKUPS_OWNER)
        mock_task_api_dep.put.return_value = {"id": 42, **body}

        response = test_client.put("/api/extensions/periodic-tasks/42", json=body)

        assert response.status_code == status.HTTP_200_OK
        mock_task_api_dep.put.assert_awaited_once_with("/periodic/42", json=body)

    def test_update_accepts_repointing_a_restore_schedule_at_a_backup_task(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Allow an edit that moves a schedule off a restore onto a backup task."""
        body = {"task": "b1", "period": 10}
        mock_task_api_dep.get.side_effect = _get_by_path(
            {
                "/periodic/42": _schedule_payload("r1"),
                "/b1": _task_payload("b1", BACKUPS_OWNER),
            }
        )
        mock_task_api_dep.put.return_value = {"id": 42, **body}

        response = test_client.put("/api/extensions/periodic-tasks/42", json=body)

        assert response.status_code == status.HTTP_200_OK
        mock_task_api_dep.put.assert_awaited_once_with("/periodic/42", json=body)

    @pytest.mark.parametrize("task", NON_STRING_TASKS)
    def test_update_refuses_a_non_string_task(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock, task: Any
    ) -> None:
        """Refuse a non-string ``task`` with ``422`` before any upstream call.

        The Tasks service writes a non-string one into the schedule's
        ``kwargs.task_name``, and an explicit ``null`` would otherwise reach the
        fallback as though the key were absent.
        """
        response = test_client.put(
            "/api/extensions/periodic-tasks/42", json={"task": task, "period": 10}
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        mock_task_api_dep.get.assert_not_awaited()
        mock_task_api_dep.put.assert_not_awaited()

    @pytest.mark.parametrize("task", PATH_UNSAFE_TASKS)
    def test_update_refuses_a_task_name_that_is_not_one_path_segment(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock, task: str
    ) -> None:
        """Refuse a body ``task`` that would restructure the upstream request URL.

        The guard reads the task through ``GET /{task_name}``, whose path is
        resolved with ``urljoin``, so a leading ``/`` turns the upstream call into
        an absolute URL aimed at another host and carries the caller's bearer
        token there. Such a name is refused, never escaped.
        """
        response = test_client.put(
            "/api/extensions/periodic-tasks/42", json={"task": task, "period": 10}
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        mock_task_api_dep.get.assert_not_awaited()
        mock_task_api_dep.put.assert_not_awaited()

    def test_update_refuses_a_stored_task_name_that_is_not_one_path_segment(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Refuse the same shape when it arrives from the stored schedule.

        A schedule written straight through the Tasks service can carry any
        ``kwargs.task_name``, so the fallback value is checked too.
        """
        mock_task_api_dep.get.return_value = _schedule_payload("/evil.example.com:80/x")

        response = test_client.put(
            "/api/extensions/periodic-tasks/42", json={"task": ""}
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        mock_task_api_dep.get.assert_awaited_once_with("/periodic/42")
        mock_task_api_dep.put.assert_not_awaited()

    def test_update_schedule_without_task_is_a_bad_gateway(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Fail with ``502`` when the stored schedule names no task."""
        mock_task_api_dep.get.return_value = {"id": 42}

        response = test_client.put(
            "/api/extensions/periodic-tasks/42", json={"task": ""}
        )

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        mock_task_api_dep.put.assert_not_awaited()

    def test_delete_is_not_guarded(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Leave deletion unguarded so a stored restore schedule stays removable."""
        mock_task_api_dep.delete.return_value = None

        response = test_client.delete("/api/extensions/periodic-tasks/42")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_task_api_dep.delete.assert_awaited_once_with("/periodic/42")
        mock_task_api_dep.get.assert_not_awaited()

    def test_list_is_not_guarded(
        self, test_client: TestClient, mock_task_api_dep: AsyncMock
    ) -> None:
        """Leave listing unguarded: the guard adds no upstream task read."""
        mock_task_api_dep.get.return_value = _empty_envelope()

        response = test_client.get("/api/extensions/periodic-tasks/")

        assert response.status_code == status.HTTP_200_OK
        mock_task_api_dep.get.assert_awaited_once_with(
            "/periodic/",
            params={
                "offset": DEFAULT_PAGINATION_OFFSET,
                "limit": DEFAULT_PAGINATION_LIMIT,
            },
        )


@pytest.mark.parametrize(
    ("http_method", "url", "mock_attr", "json_body"), GUARD_READ_CASES
)
class TestExtensionsPeriodicTasksGuardErrorSplit:
    """Cover the gateway 4xx/5xx error split on the guard's own upstream reads."""

    def test_upstream_client_error_passes_through(
        self,
        test_client: TestClient,
        mock_task_api_dep: AsyncMock,
        http_method: str,
        url: str,
        mock_attr: str,
        json_body: dict[str, Any] | None,
    ) -> None:
        """Return the guard read's upstream client error unchanged."""
        mock_task_api_dep.get.side_effect = HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="upstream detail"
        )

        response = _issue(test_client, http_method, url, json_body)

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json() == {"detail": "upstream detail"}
        getattr(mock_task_api_dep, mock_attr).assert_not_awaited()

    def test_upstream_server_error_becomes_502(
        self,
        test_client: TestClient,
        mock_task_api_dep: AsyncMock,
        http_method: str,
        url: str,
        mock_attr: str,
        json_body: dict[str, Any] | None,
    ) -> None:
        """Fail the guard read with ``502`` on an upstream server error."""
        mock_task_api_dep.get.side_effect = HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="tasks down"
        )

        response = _issue(test_client, http_method, url, json_body)

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        getattr(mock_task_api_dep, mock_attr).assert_not_awaited()

    def test_upstream_oserror_becomes_502(
        self,
        test_client: TestClient,
        mock_task_api_dep: AsyncMock,
        http_method: str,
        url: str,
        mock_attr: str,
        json_body: dict[str, Any] | None,
    ) -> None:
        """Fail the guard read with ``502`` on a connection-level ``OSError``."""
        mock_task_api_dep.get.side_effect = OSError("connection refused")

        response = _issue(test_client, http_method, url, json_body)

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        getattr(mock_task_api_dep, mock_attr).assert_not_awaited()
