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

"""Define tests for the CSRF protection for app.sep module."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from app.core.security import crypto_serializer
from app.sep.config import sep_settings
from app.sep.deps import IsCsrfValidated
from app.sep.middleware import CSRFMiddleware
from app.sep.middleware.csrf import CSRF_COOKIE_NAME
from app.sep.utils.decorators import csrf_exempt

SESSION_COOKIE_NAME = sep_settings.SESSION.COOKIE_NAME
NONCE_HEX_LENGTH = 64


@pytest.fixture
def test_client() -> TestClient:
    """Provide a TestClient with CSRF protection and routes configured."""
    app = FastAPI()

    @app.get("/gen-token", response_class=JSONResponse)
    def generate(request: Request):
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"detail": "OK", "csrf_token": request.state.csrf_token},
        )

    @app.post("/protected", dependencies=[IsCsrfValidated], response_class=JSONResponse)
    def protected(request: Request):
        return JSONResponse(status_code=status.HTTP_200_OK, content={"detail": "OK"})

    @app.get("/stream-logs/data", response_class=JSONResponse)
    @csrf_exempt
    async def stream_logs_data(request: Request):
        return JSONResponse(
            status_code=status.HTTP_200_OK, content={"detail": "Stream OK"}
        )

    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.add_middleware(CSRFMiddleware)

    return TestClient(app)


def test_authenticated_csrf_token_generation(test_client: TestClient):
    """Test GET with authToken produces a session-bound token in state and cookie."""
    session_value = "signed-session-token"
    test_client.cookies[SESSION_COOKIE_NAME] = session_value

    response = test_client.get("/gen-token")
    assert response.status_code == status.HTTP_200_OK

    csrf_token = response.json()["csrf_token"]
    assert csrf_token

    csrf_cookie = response.cookies.get(CSRF_COOKIE_NAME)
    assert csrf_cookie is not None
    assert csrf_cookie == csrf_token

    nonce = crypto_serializer.loads(csrf_token, salt=session_value)
    assert isinstance(nonce, str)
    assert len(nonce) == NONCE_HEX_LENGTH


def test_unauthenticated_csrf_token_generation(test_client: TestClient):
    """Test GET without authToken produces a signed token for the login page."""
    response = test_client.get("/gen-token")
    assert response.status_code == status.HTTP_200_OK

    csrf_token = response.json()["csrf_token"]
    assert csrf_token

    csrf_cookie = response.cookies.get(CSRF_COOKIE_NAME)
    assert csrf_cookie is not None

    nonce = crypto_serializer.loads(csrf_token)
    assert isinstance(nonce, str)
    assert len(nonce) == NONCE_HEX_LENGTH


def test_token_reuse_across_gets(test_client: TestClient):
    """Test that second GET reuses the token from the cookie."""
    session_value = "signed-session-token"
    test_client.cookies[SESSION_COOKIE_NAME] = session_value

    response1 = test_client.get("/gen-token")
    token1 = response1.json()["csrf_token"]

    response2 = test_client.get("/gen-token")
    token2 = response2.json()["csrf_token"]

    assert token1 == token2


def test_valid_authenticated_submission(test_client: TestClient):
    """Test POST with correct token and session cookie returns 200."""
    session_value = "signed-session-token"
    test_client.cookies[SESSION_COOKIE_NAME] = session_value

    response = test_client.get("/gen-token")
    csrf_token = response.json()["csrf_token"]

    response = test_client.post(
        "/protected",
        data={"csrf-token": csrf_token},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"detail": "OK"}


def test_valid_unauthenticated_submission(test_client: TestClient):
    """Test POST with matching form and cookie token on login returns 200."""
    response = test_client.get("/gen-token")
    csrf_token = response.json()["csrf_token"]

    response = test_client.post(
        "/protected",
        data={"csrf-token": csrf_token},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"detail": "OK"}


def test_missing_form_token(test_client: TestClient):
    """Test POST without token returns 400."""
    response = test_client.get("/gen-token")

    response = test_client.post("/protected")
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_invalid_form_token(test_client: TestClient):
    """Test POST with tampered token returns 403."""
    session_value = "signed-session-token"
    test_client.cookies[SESSION_COOKIE_NAME] = session_value

    response = test_client.get("/gen-token")

    response = test_client.post(
        "/protected",
        data={"csrf-token": "tampered-token"},
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_wrong_session_token(test_client: TestClient):
    """Test token from different session returns 403."""
    test_client.cookies[SESSION_COOKIE_NAME] = "session-A"

    response = test_client.get("/gen-token")
    csrf_token = response.json()["csrf_token"]

    test_client.cookies[SESSION_COOKIE_NAME] = "session-B"
    test_client.cookies[CSRF_COOKIE_NAME] = csrf_token

    response = test_client.post(
        "/protected",
        data={"csrf-token": csrf_token},
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_fresh_token_after_session_change(test_client: TestClient):
    """Test that clearing the CSRF cookie forces a fresh session-bound token."""
    response = test_client.get("/gen-token")
    unauth_token = response.json()["csrf_token"]

    test_client.cookies[SESSION_COOKIE_NAME] = "new-session"
    del test_client.cookies[CSRF_COOKIE_NAME]

    response = test_client.get("/gen-token")
    auth_token = response.json()["csrf_token"]
    assert auth_token != unauth_token

    response = test_client.post(
        "/protected",
        data={"csrf-token": auth_token},
    )
    assert response.status_code == status.HTTP_200_OK


def test_multi_tab_stability(test_client: TestClient):
    """Test two GETs share same token and both POSTs succeed."""
    session_value = "signed-session-token"
    test_client.cookies[SESSION_COOKIE_NAME] = session_value

    resp1 = test_client.get("/gen-token")
    token1 = resp1.json()["csrf_token"]

    resp2 = test_client.get("/gen-token")
    token2 = resp2.json()["csrf_token"]
    assert token1 == token2

    resp_post1 = test_client.post(
        "/protected",
        data={"csrf-token": token1},
    )
    assert resp_post1.status_code == status.HTTP_200_OK

    resp_post2 = test_client.post(
        "/protected",
        data={"csrf-token": token2},
    )
    assert resp_post2.status_code == status.HTTP_200_OK


@patch("fastapi.staticfiles.StaticFiles.get_response", new_callable=AsyncMock)
def test_static_files_excluded(mock_get_response, test_client: TestClient):
    """Test that static GET does not set a CSRF cookie."""
    mock_response = JSONResponse(
        content="Static file content", status_code=status.HTTP_200_OK
    )
    mock_get_response.return_value = mock_response

    response = test_client.get("/static/example.txt")
    assert response.status_code == status.HTTP_200_OK
    assert response.cookies.get(CSRF_COOKIE_NAME) is None


def test_csrf_exempt_endpoint(test_client: TestClient):
    """Test that exempt GET does not set a CSRF cookie."""
    response = test_client.get("/stream-logs/data")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"detail": "Stream OK"}
    assert response.cookies.get(CSRF_COOKIE_NAME) is None


def test_cookie_attributes(test_client: TestClient):
    """Test CSRF cookie has httponly, samesite=lax, and correct secure setting."""
    response = test_client.get("/gen-token")
    assert response.status_code == status.HTTP_200_OK

    cookie_header = response.headers.get("set-cookie", "")
    assert CSRF_COOKIE_NAME in cookie_header
    assert "httponly" in cookie_header.lower()
    assert "samesite=lax" in cookie_header.lower()

    if sep_settings.SESSION.SECURE:
        assert "secure" in cookie_header.lower()
