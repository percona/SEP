# Copyright (C) 2025 Percona LLC
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
