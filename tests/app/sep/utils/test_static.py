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

"""Define tests for the app.sep.utils.static module."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette import status
from starlette.staticfiles import StaticFiles

from app.sep.utils.static import AuthenticatedStaticFiles


@pytest.fixture
def static_files(tmp_path):
    """Create an AuthenticatedStaticFiles instance with a temporary directory."""
    return AuthenticatedStaticFiles(directory=str(tmp_path))


@pytest.fixture
def http_scope():
    """Create an ASGI scope dict with type 'http'."""
    return {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [],
    }


@pytest.fixture
def websocket_scope():
    """Create an ASGI scope dict with type 'websocket'."""
    return {"type": "websocket"}


@pytest.fixture
def receive():
    """Create a mock ASGI receive callable."""
    return AsyncMock()


@pytest.fixture
def send():
    """Create a mock ASGI send callable."""
    return AsyncMock()


@pytest.mark.asyncio
async def test_non_http_scope_skips_auth(
    mocker, static_files, websocket_scope, receive, send
):
    """Assert non-HTTP scopes bypass authentication and call parent directly."""
    get_user_mock = mocker.patch(
        "app.sep.utils.static.get_current_user", new_callable=AsyncMock
    )
    parent_call = mocker.patch.object(StaticFiles, "__call__", new_callable=AsyncMock)

    await static_files(websocket_scope, receive, send)

    get_user_mock.assert_not_called()
    parent_call.assert_called_once_with(websocket_scope, receive, send)


@pytest.mark.asyncio
async def test_http_scope_authenticates_then_serves(
    mocker, static_files, http_scope, receive, send
):
    """Assert HTTP requests await get_current_user before serving static files."""
    get_user_mock = mocker.patch(
        "app.sep.utils.static.get_current_user", new_callable=AsyncMock
    )
    parent_call = mocker.patch.object(StaticFiles, "__call__", new_callable=AsyncMock)

    await static_files(http_scope, receive, send)

    get_user_mock.assert_awaited_once()
    parent_call.assert_called_once_with(http_scope, receive, send)


@pytest.mark.asyncio
async def test_auth_failure_propagates(mocker, static_files, http_scope, receive, send):
    """Assert HTTPException from get_current_user propagates."""
    mocker.patch(
        "app.sep.utils.static.get_current_user",
        new_callable=AsyncMock,
        side_effect=HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        ),
    )
    mocker.patch.object(StaticFiles, "__call__", new_callable=AsyncMock)

    with pytest.raises(HTTPException) as exc_info:
        await static_files(http_scope, receive, send)

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
