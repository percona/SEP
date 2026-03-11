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

"""Define tests for the app.sep.main module."""

from unittest.mock import Mock

import pytest
from fastapi import HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from app.core.auth.exceptions import BaseAuthProviderException
from app.sep.config import sep_settings
from app.sep.deps import get_access_token_from_cookie
from app.sep.main import get_tasks_index_context, sep_app, templates
from tests.app.factories import OAuthTokenFactory


@pytest.fixture
def test_client_with_session_cookie(test_client: TestClient) -> TestClient:
    """Create an authenticated test client for the app with the session cookie set."""
    test_client.cookies[sep_settings.SESSION.COOKIE_NAME] = "existing_session"
    return test_client


@pytest.fixture
def logger_mock(mocker) -> Mock:
    """Mock the logger for the app.sep.main module."""
    return mocker.patch("app.sep.main.logger")


@pytest.fixture
def dummy_context() -> dict[str, str]:
    """Override get_tasks_index_context and return dummy dict context."""
    ctx = {"message": "Welcome Home"}
    sep_app.dependency_overrides[get_tasks_index_context] = lambda: ctx
    yield ctx
    sep_app.dependency_overrides = {}


@pytest.fixture
def dummy_access_token() -> str:
    """Override get_access_token_from_cookie and return dummy access token."""
    fake_access_token = "access-token"
    sep_app.dependency_overrides[get_access_token_from_cookie] = (
        lambda: fake_access_token
    )
    yield fake_access_token
    sep_app.dependency_overrides = {}


class TestLogin:
    """Define test suite for GET and POST login routes."""

    def test_login_form_renders_template(self, mocker, test_client):
        """Test the GET /login route.

        When an unauthenticated user GETs /login (no session cookie),
        the login form route should call TemplateResponse with the correct
        template name and context.
        """
        dummy_html = "<html>Login Form</html>"
        dummy_response = HTMLResponse(content=dummy_html)
        template_patch = mocker.patch(
            "app.sep.main.templates.TemplateResponse", return_value=dummy_response
        )

        response = test_client.get("/login")

        assert response.status_code == status.HTTP_200_OK
        template_patch.assert_called_once()
        _, kwargs = template_patch.call_args
        assert kwargs.get("name") == "login.html.j2"
        context = kwargs.get("context", {})
        assert "csrf_token" in context

    def test_get_login_redirects_if_authenticated(
        self, test_client_with_session_cookie
    ):
        """Test the GET /login route for an already authenticated user.

        If a user is already authenticated (i.e. has the session cookie)
        then GET /login should raise a redirect.
        """
        response = test_client_with_session_cookie.get("/login", follow_redirects=False)

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/"

    @pytest.mark.parametrize(
        ("next_path", "expected_location"),
        [
            (None, "/"),
            ("", "/"),
            ("/", "/"),
            ("/fake-page", "/fake-page"),
            ("http://127.0.0.1/fake-page", "/"),
        ],
    )
    def test_post_login_success(
        self, mocker, test_client, next_path, expected_location
    ):
        """Test the POST /login route.

        A successful POST /login should (a) call the User.get_oauth_token
        to verify credentials, (b) serialize the access token, (c) set a cookie,
        and (d) return a redirect response.
        """
        username = "testuser"
        fake_access_token = "fake_access_token"
        get_oauth_token_patch = mocker.patch(
            "app.sep.main.User.get_oauth_token",
            new_callable=mocker.AsyncMock,
            return_value=OAuthTokenFactory.build(access_token=fake_access_token),
        )
        invalidate_tokens_for_user_patch = mocker.patch(
            "app.sep.main.User.invalidate_tokens_for_user",
            new_callable=mocker.AsyncMock,
        )
        dumps_patch = mocker.patch(
            "app.sep.main.crypto_timestamp_serializer.dumps",
            return_value="serialized_fake_token",
        )
        form_data = {"username": username, "password": "secret"}

        login_route = "/login"
        if next_path is not None:
            login_route += f"?next={next_path}"
        response = test_client.post(login_route, data=form_data, follow_redirects=False)

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == expected_location
        cookie_header = response.headers.get("set-cookie", "")
        assert sep_settings.SESSION.COOKIE_NAME in cookie_header
        assert "serialized_fake_token" in cookie_header
        get_oauth_token_patch.assert_awaited_once_with(
            username=username, password="secret"
        )
        invalidate_tokens_for_user_patch.assert_awaited_once_with(
            username, exclude_tokens=[fake_access_token]
        )
        dumps_patch.assert_called_once_with(fake_access_token)

    def test_post_login_redirects_if_authenticated(
        self, test_client_with_session_cookie
    ):
        """Test the POST /login route for an already authenticated user.

        If the client sends a session cookie, the POST /login route
        should not try to reauthenticate but instead immediately redirect.
        """
        form_data = {"username": "testuser", "password": "secret"}

        response = test_client_with_session_cookie.post(
            "/login", data=form_data, follow_redirects=False
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/"


class TestLogout:
    """Define test suite for logout route."""

    def test_logout_success(
        self, mocker, dummy_access_token, test_client_with_session_cookie
    ):
        """Test a successful logout request.

        A successful POST /logout should delete the session cookie,
        attempt to invalidate the OAuth token and return a redirect.
        """
        invalidate_patch = mocker.patch(
            "app.sep.main.User.invalidate_oauth_token",
            new_callable=mocker.AsyncMock,
        )

        response = test_client_with_session_cookie.post(
            "/logout", follow_redirects=False
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/"
        cookie_header = response.headers.get("set-cookie", "")
        assert sep_settings.SESSION.COOKIE_NAME in cookie_header
        invalidate_patch.assert_awaited_once_with(dummy_access_token)

    def test_logout_handles_invalidation_error(
        self, mocker, dummy_access_token, test_client_with_session_cookie
    ):
        """Test that logout route always redirects.

        Even if User.invalidate_oauth_token raises an error (e.g. KeyError)
        the logout route should still return a redirect response.
        """
        mocker.patch(
            "app.sep.main.User.invalidate_oauth_token",
            new_callable=mocker.AsyncMock,
            side_effect=KeyError("invalid token"),
        )

        response = test_client_with_session_cookie.post(
            "/logout",
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/"
        cookie_header = response.headers.get("set-cookie", "")
        assert sep_settings.SESSION.COOKIE_NAME in cookie_header


def test_read_root_renders_homepage(mocker, dummy_context, test_client):
    """Test that the index page properly renders the homepage template.

    GET / (the homepage) should render the homepage template with the context
    provided by get_tasks_index_context.
    """
    dummy_html = "<html>Homepage</html>"
    template_patch = mocker.patch(
        "app.sep.main.templates.TemplateResponse",
        return_value=HTMLResponse(content=dummy_html),
    )

    response = test_client.get("/")

    assert response.status_code == status.HTTP_200_OK
    template_patch.assert_called_once()
    _, kwargs = template_patch.call_args
    assert kwargs.get("name") == "homepage.html.j2"
    assert kwargs.get("context") == dummy_context


class TestExceptionHandlers:
    """Define test suite for exception handlers."""

    def test_default_error_handler(self, mocker, dummy_context, test_client):
        """Test that HTTPExceptions are caught and properly handled."""
        error_detail = "Internal Server Error"
        fake_referer = "/fake-page"
        mocker.patch(
            "app.sep.main.templates.TemplateResponse",
            side_effect=HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error_detail
            ),
        )
        messages_error_mock = mocker.patch("app.sep.main.messages.error")

        response = test_client.get(
            "/", headers={"Referer": fake_referer}, follow_redirects=False
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == fake_referer
        messages_error_mock.assert_called_once_with(mocker.ANY, error_detail)

    def test_auth_provider_exception_handler(
        self, mocker, dummy_access_token, dummy_context, test_client_with_session_cookie
    ):
        """Test that BaseAuthProviderException are caught and properly handled."""
        error_detail = "Error getting response from auth provider."
        mocker.patch(
            "app.sep.main.templates.TemplateResponse",
            side_effect=BaseAuthProviderException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=error_detail
            ),
        )
        messages_error_mock = mocker.patch("app.sep.main.messages.error")

        response = test_client_with_session_cookie.get(
            "/",
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/login?next=/"
        cookie_header = response.headers.get("set-cookie", "")
        assert sep_settings.SESSION.COOKIE_NAME in cookie_header
        messages_error_mock.assert_called_once_with(
            mocker.ANY, error_detail, sticky=True
        )

    def test_internal_error_handler(
        self,
        mocker,
        dummy_context,
        dummy_access_token,
        regular_user,
        logger_mock,
        test_client,
    ):
        """Test that unexpected 500 errors are caught and properly handled."""
        error_msg = "Unexpected error"
        unexpected_exc = ValueError(error_msg)
        base_uri = "http://127.0.0.1"
        formatted_exception = f"Line 1\nLine 2\n{error_msg}"
        get_base_url_patch = mocker.patch(
            "app.sep.main.get_base_url", return_value=base_uri
        )
        get_current_user_patch = mocker.patch(
            "app.sep.main.get_current_user", return_value=regular_user
        )
        get_default_context_patch = mocker.patch(
            "app.sep.main.get_default_context", return_value=dummy_context
        )
        template_patch = mocker.patch(
            "app.sep.main.templates.TemplateResponse",
            side_effect=[unexpected_exc, HTMLResponse(content="<html>Error</html>")],
        )
        messages_error_mock = mocker.patch("app.sep.main.messages.error")
        format_exception_patch = mocker.patch(
            "app.sep.main.format_exception",
            return_value=formatted_exception.splitlines(keepends=True),
        )

        test_client.get("/")

        get_base_url_patch.assert_called_once()
        logger_mock.exception.assert_called_once_with(
            "Unhandled exception:", exc_info=unexpected_exc
        )
        get_current_user_patch.assert_called_once()
        messages_error_mock.assert_called_once_with(
            mocker.ANY,
            "Internal Server Error. Please contact the administrators for help.",
            sticky=True,
        )
        format_exception_patch.assert_called_once_with(
            unexpected_exc, limit=-1, chain=False
        )
        get_default_context_patch.assert_called_once_with(
            mocker.ANY, regular_user, base_uri
        )
        template_patch.assert_called_with(
            request=mocker.ANY,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            name="error.html.j2",
            context={"exception": formatted_exception, **dummy_context},
        )

    @pytest.mark.usefixtures("mock_get_username_mapping")
    def test_404_error(self, mocker, regular_user, test_client):
        """Test 404 errors renders the 404 template for authenticated users."""
        mocker.patch("app.sep.main.get_current_user", return_value=regular_user)
        template_spy = mocker.spy(templates, "TemplateResponse")

        response = test_client.get("/non-existent-page")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        template_spy.assert_called_once()
        _, kwargs = template_spy.call_args
        assert kwargs.get("name") == "404.html.j2"

        sep_app.dependency_overrides = {}

    def test_404_error_unauthenticated(self, regular_user, test_client):
        """Test 404 errors redirects to the login page for unauthenticated users."""
        non_existent_path = "/non-existent-page"
        response = test_client.get(non_existent_path, follow_redirects=False)
        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == f"/login?next={non_existent_path}"
