"""Define tests for the app.sep.main module."""

from fastapi import HTTPException, status
from fastapi.responses import HTMLResponse

from app.sep.config import sep_settings
from app.sep.deps import get_access_token_from_cookie
from app.sep.main import get_tasks_index_context, sep_app, templates
from tests.app.factories import OAuthTokenFactory


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
        assert kwargs.get("name") == "login.html"
        context = kwargs.get("context", {})
        assert "csrf_token" in context

    def test_get_login_redirects_if_authenticated(self, test_client):
        """Test the GET /login route for an already authenticated user.

        If a user is already authenticated (i.e. has the session cookie)
        then GET /login should raise a redirect.
        """
        cookies = {sep_settings.SESSION.COOKIE_NAME: "existing_session"}

        response = test_client.get("/login", cookies=cookies, allow_redirects=False)

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/"

    def test_post_login_success(self, mocker, test_client):
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

        response = test_client.post("/login", data=form_data, allow_redirects=False)

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/"
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

    def test_post_login_redirects_if_authenticated(self, test_client):
        """Test the POST /login route for an already authenticated user.

        If the client sends a session cookie, the POST /login route
        should not try to reauthenticate but instead immediately redirect.
        """
        cookies = {sep_settings.SESSION.COOKIE_NAME: "existing_session"}
        form_data = {"username": "testuser", "password": "secret"}

        response = test_client.post(
            "/login", data=form_data, cookies=cookies, allow_redirects=False
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/"


class TestLogout:
    """Define test suite for logout route."""

    def test_logout_success(self, mocker, test_client):
        """Test a successful logout request.

        A successful POST /logout should delete the session cookie,
        attempt to invalidate the OAuth token and return a redirect.
        """
        invalidate_patch = mocker.patch(
            "app.sep.main.User.invalidate_oauth_token",
            new_callable=mocker.AsyncMock,
        )
        fake_access_token = "access-token"
        sep_app.dependency_overrides[get_access_token_from_cookie] = (
            lambda: fake_access_token
        )

        response = test_client.post(
            "/logout",
            cookies={sep_settings.SESSION.COOKIE_NAME: "fake_cookie_token"},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/"
        cookie_header = response.headers.get("set-cookie", "")
        assert sep_settings.SESSION.COOKIE_NAME in cookie_header
        invalidate_patch.assert_awaited_once_with(fake_access_token)

        sep_app.dependency_overrides = {}

    def test_logout_handles_invalidation_error(self, mocker, test_client):
        """Test that logout route always redirects.

        Even if User.invalidate_oauth_token raises an error (e.g. KeyError)
        the logout route should still return a redirect response.
        """
        mocker.patch(
            "app.sep.main.User.invalidate_oauth_token",
            new_callable=mocker.AsyncMock,
            side_effect=KeyError("invalid token"),
        )
        fake_access_token = "access-token"
        sep_app.dependency_overrides[get_access_token_from_cookie] = (
            lambda: fake_access_token
        )

        response = test_client.post(
            "/logout",
            cookies={sep_settings.SESSION.COOKIE_NAME: "fake_cookie_token"},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/"
        cookie_header = response.headers.get("set-cookie", "")
        assert sep_settings.SESSION.COOKIE_NAME in cookie_header


def test_read_root_renders_homepage(mocker, test_client):
    """Test that the index page properly renders the homepage template.

    GET / (the homepage) should render the homepage template with the context
    provided by get_tasks_index_context.
    """
    dummy_context = {"message": "Welcome Home"}
    sep_app.dependency_overrides[get_tasks_index_context] = lambda: dummy_context
    dummy_html = "<html>Homepage</html>"
    template_patch = mocker.patch(
        "app.sep.main.templates.TemplateResponse",
        return_value=HTMLResponse(content=dummy_html),
    )

    response = test_client.get("/")

    assert response.status_code == status.HTTP_200_OK
    template_patch.assert_called_once()
    _, kwargs = template_patch.call_args
    assert kwargs.get("name") == "homepage.html"
    assert kwargs.get("context") == dummy_context

    sep_app.dependency_overrides = {}


def test_default_error_handler(mocker, test_client):
    """Test that HTTPExceptions are caught and properly handled."""
    error_detail = "Internal Server Error"
    fake_referer = "/fake-page"
    sep_app.dependency_overrides[get_tasks_index_context] = lambda: {"message": "hi"}
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

    sep_app.dependency_overrides = {}


def test_404_error(mocker, regular_user, test_client):
    """Test 404 errors renders the 404 template for authenticated users."""
    mocker.patch("app.sep.main.get_current_user", return_value=regular_user)
    template_spy = mocker.spy(templates, "TemplateResponse")

    response = test_client.get("/non-existent-page")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    template_spy.assert_called_once()
    _, kwargs = template_spy.call_args
    assert kwargs.get("name") == "404.html"

    sep_app.dependency_overrides = {}


def test_404_error_unauthenticated(regular_user, test_client):
    """Test 404 errors redirects to the login page for unauthenticated users."""
    response = test_client.get("/non-existent-page", follow_redirects=False)
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/login"
