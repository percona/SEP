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

"""Define tests for the CSRF protection for app.sep module."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from fastapi_csrf_protect import CsrfProtect
from fastapi_csrf_protect.exceptions import CsrfProtectError

from app.sep.config import CsrfSettings
from app.sep.deps import IsCsrfValidated
from app.sep.main import csrf_protect_exception_handler
from app.sep.middleware import CSRFMiddleware
from app.sep.utils.decorators import csrf_exempt


@pytest.fixture
def test_client() -> TestClient:
    """Provides a TestClient with CSRF protection and routes configured."""
    app = FastAPI()

    @app.get("/gen-token", response_class=JSONResponse)
    def generate(request: Request):
        response: JSONResponse = JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"detail": "OK", "csrf_token": request.state.csrf_token},
        )
        return response

    @app.post("/protected", dependencies=[IsCsrfValidated], response_class=JSONResponse)
    def protected(request: Request):
        response: JSONResponse = JSONResponse(
            status_code=status.HTTP_200_OK, content={"detail": "OK"}
        )
        return response

    @app.get("/stream-logs/data", response_class=JSONResponse)
    @csrf_exempt
    async def stream_logs_data(request: Request):
        return JSONResponse(
            status_code=status.HTTP_200_OK, content={"detail": "Stream OK"}
        )

    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.add_middleware(CSRFMiddleware)

    app.add_exception_handler(CsrfProtectError, csrf_protect_exception_handler)

    return TestClient(app)


def test_valid_csrf_token(test_client: TestClient):
    """Test the CSRF token generation and validation process."""

    @CsrfProtect.load_config
    def get_configs():
        return CsrfSettings()

    response = test_client.get("/gen-token")
    assert response.status_code == status.HTTP_200_OK

    csrf_token = response.json().get("csrf_token", None)
    assert csrf_token is not None

    csrf_cookie = test_client.cookies.get("fastapi-csrf-token", None)
    assert csrf_cookie is not None

    test_client.cookies["fastapi-csrf-token"] = csrf_cookie
    response = test_client.post(
        "/protected",
        data={"csrf-token": csrf_token},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"detail": "OK"}


def test_csrf_token_reuse_across_multiple_posts(test_client: TestClient):
    """Test that the same CSRF token can be used for multiple sequential POSTs."""

    @CsrfProtect.load_config
    def get_configs():
        return CsrfSettings()

    response = test_client.get("/gen-token")
    assert response.status_code == status.HTTP_200_OK
    csrf_token = response.json().get("csrf_token")
    assert csrf_token is not None
    csrf_cookie = test_client.cookies.get("fastapi-csrf-token")
    assert csrf_cookie is not None
    test_client.cookies["fastapi-csrf-token"] = csrf_cookie

    # First POST
    response1 = test_client.post(
        "/protected",
        data={"csrf-token": csrf_token},
    )
    assert response1.status_code == status.HTTP_200_OK
    assert response1.json() == {"detail": "OK"}

    # Second POST with the same token, no GET in between (token is reusable)
    response2 = test_client.post(
        "/protected",
        data={"csrf-token": csrf_token},
    )
    assert response2.status_code == status.HTTP_200_OK
    assert response2.json() == {"detail": "OK"}


def test_invalid_csrf_token(test_client: TestClient):
    """Test handling of invalid CSRF tokens and missing cookies."""

    @CsrfProtect.load_config
    def get_configs():
        return CsrfSettings()

    response = test_client.get("/gen-token")
    assert response.status_code == status.HTTP_200_OK

    csrf_token = response.json().get("csrf_token", None)
    assert csrf_token is not None

    csrf_cookie = test_client.cookies.get("fastapi-csrf-token", None)
    assert csrf_cookie is not None

    test_client.cookies = None

    response = test_client.post("/protected")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json() == {"detail": "Missing Cookie: `fastapi-csrf-token`."}

    test_client.cookies["fastapi-csrf-token"] = csrf_cookie
    response = test_client.post(
        "/protected",
        data={"csrf-token": "invalid token"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"detail": "The CSRF signatures submitted do not match."}

    test_client.cookies["fastapi-csrf-token"] = "invalid cookie"
    response = test_client.post(
        "/protected",
        data={"csrf-token": csrf_token},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"detail": "The CSRF token is invalid."}


@patch("fastapi.staticfiles.StaticFiles.get_response", new_callable=AsyncMock)
def test_excluded_paths(mock_get_response, test_client: TestClient):
    """Test that excluded paths do not involve CSRF protection."""

    @CsrfProtect.load_config
    def get_configs():
        return CsrfSettings()

    mock_response = JSONResponse(
        content="Static file content", status_code=status.HTTP_200_OK
    )
    mock_get_response.return_value = mock_response

    response = test_client.get("/static/example.txt")
    assert response.status_code == status.HTTP_200_OK
    assert test_client.cookies.get("fastapi-csrf-token") is None

    response = test_client.get("/stream-logs/data")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"detail": "Stream OK"}
    assert test_client.cookies.get("fastapi-csrf-token") is None
