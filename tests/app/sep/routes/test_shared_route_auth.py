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
this is the contract its clients rely on.
"""

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.sep.main import sep_app

SHARED_ROUTES = ["/files/1", "/stream-logs/1", "/execution-events/1"]


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
