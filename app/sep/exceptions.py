"""Define reusable exceptions for the SEP app."""

from http.cookies import SimpleCookie

from fastapi import Request, status

from app.core.exceptions import HTTPRedirectException
from app.sep.config import sep_settings


class LoginRedirectException(HTTPRedirectException):
    """Define exception raised for login redirects.

    This exception clears the previous session cookie, if any, and redirects the user to
    the login page.

    :param request: The HTTP request object, used to build the login redirect URL.
    :type request: Request
    """

    def __init__(self, request: Request) -> None:
        super().__init__(
            f"{request.url_for('login').path}?next={request.url.path}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
        cookie = SimpleCookie()
        cookie[sep_settings.SESSION.COOKIE_NAME] = ""
        cookie[sep_settings.SESSION.COOKIE_NAME]["httponly"] = True
        cookie[sep_settings.SESSION.COOKIE_NAME]["secure"] = sep_settings.SESSION.SECURE
        cookie[sep_settings.SESSION.COOKIE_NAME]["samesite"] = (
            sep_settings.SESSION.SAMESITE
        )
        self.headers["set-cookie"] = cookie.output(header="").strip()
