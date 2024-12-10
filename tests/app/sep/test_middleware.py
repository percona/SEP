"""Define tests for the CSRF protection for app.sep module."""

from http import HTTPStatus

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from fastapi_csrf_protect import CsrfProtect
from fastapi_csrf_protect.exceptions import CsrfProtectError

from app.sep.config import CsrfSettings
from app.sep.deps import IsCsrfValidated
from app.sep.main import csrf_protect_exception_handler
from app.sep.middleware import CSRFMiddleware


@pytest.fixture
def test_client() -> TestClient:
    """Provides a TestClient with CSRF protection and routes configured."""
    app = FastAPI()

    @app.get("/gen-token", response_class=JSONResponse)
    def generate(request: Request):
        response: JSONResponse = JSONResponse(
            status_code=200,
            content={"detail": "OK", "csrf_token": request.state.csrf_token},
        )
        return response

    @app.post("/protected", dependencies=[IsCsrfValidated], response_class=JSONResponse)
    def protected(request: Request):
        response: JSONResponse = JSONResponse(status_code=200, content={"detail": "OK"})
        return response

    app.add_middleware(CSRFMiddleware)

    app.add_exception_handler(CsrfProtectError, csrf_protect_exception_handler)

    return TestClient(app)


def test_valid_csrf_token(test_client: TestClient):
    """Test the CSRF token generation and validation process."""

    @CsrfProtect.load_config
    def get_configs():
        return CsrfSettings()

    response = test_client.get("/gen-token")
    assert response.status_code == HTTPStatus.OK

    csrf_token = response.json().get("csrf_token", None)
    assert csrf_token is not None

    csrf_cookie = test_client.cookies.get("fastapi-csrf-token", None)
    assert csrf_cookie is not None

    test_client.cookies["fastapi-csrf-token"] = csrf_cookie
    response = test_client.post(
        "/protected",
        data={"csrf-token": csrf_token},
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"detail": "OK"}


def test_invalid_csrf_token(test_client: TestClient):
    """Test handling of invalid CSRF tokens and missing cookies."""

    @CsrfProtect.load_config
    def get_configs():
        return CsrfSettings()

    response = test_client.get("/gen-token")
    assert response.status_code == HTTPStatus.OK

    csrf_token = response.json().get("csrf_token", None)
    assert csrf_token is not None

    csrf_cookie = test_client.cookies.get("fastapi-csrf-token", None)
    assert csrf_cookie is not None

    test_client.cookies = None

    response = test_client.post("/protected")
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json() == {"detail": "Missing Cookie: `fastapi-csrf-token`."}

    test_client.cookies["fastapi-csrf-token"] = csrf_cookie
    response = test_client.post(
        "/protected",
        data={"csrf-token": "invalid token"},
    )
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json() == {"detail": "The CSRF signatures submitted do not match."}

    test_client.cookies["fastapi-csrf-token"] = "invalid cookie"
    response = test_client.post(
        "/protected",
        data={"csrf-token": csrf_token},
    )
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json() == {"detail": "The CSRF token is invalid."}
