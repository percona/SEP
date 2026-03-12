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

"""Define middleware to handle CSRF protection.

Implement the OWASP Signed Double-Submit Cookie pattern using
``itsdangerous.URLSafeSerializer``.  When an ``authToken`` session cookie is
present the CSRF token is HMAC-bound to it (``salt=session_cookie``); otherwise
a plain signed token is used for unauthenticated pages such as the login form.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.security import crypto_serializer

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp

    from app.sep.config import SEPSettings

CSRF_COOKIE_NAME = "_csrf"
CSRF_FORM_FIELD = "csrf-token"

__all__ = ["CSRF_COOKIE_NAME", "CSRF_FORM_FIELD", "CSRFMiddleware"]


def _get_sep_settings() -> SEPSettings:
    """Return the lazily-resolved SEP settings singleton.

    Deferred to break the circular import chain
    ``config → middleware.__init__ → csrf → config``.

    :return: The SEP settings instance.
    :rtype: SEPSettings
    """
    from app.sep.config import sep_settings

    return sep_settings


class CSRFMiddleware(BaseHTTPMiddleware):
    """Manage CSRF protection for HTTP requests and responses.

    On GET requests the middleware generates a signed CSRF token and exposes it
    via ``request.state.csrf_token`` so templates can embed it in forms.  The
    token is also set as a cookie.  Subsequent GETs reuse the existing cookie
    value so multi-tab browsing remains stable.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Generate and attach CSRF tokens on GET requests.

        :param request: The incoming HTTP request.
        :type request: Request
        :param call_next: The next middleware or endpoint in the ASGI application.
        :type call_next: RequestResponseEndpoint
        :return: The HTTP response, potentially with a CSRF cookie set.
        :rtype: Response
        """
        sep_settings = _get_sep_settings()
        method = request.method.upper()
        needs_cookie = False

        if method == "GET":
            session_cookie = request.cookies.get(sep_settings.SESSION.COOKIE_NAME)
            existing_csrf = request.cookies.get(CSRF_COOKIE_NAME)

            if existing_csrf:
                request.state.csrf_token = existing_csrf
            else:
                nonce = secrets.token_hex(32)
                if session_cookie:
                    token = crypto_serializer.dumps(nonce, salt=session_cookie)
                else:
                    token = crypto_serializer.dumps(nonce)
                request.state.csrf_token = token
                needs_cookie = True

        response = await call_next(request)

        endpoint = request.scope.get("endpoint")
        if (
            method == "GET"
            and needs_cookie
            and not isinstance(endpoint, StaticFiles)
            and not getattr(request.state, "is_csrf_exempt", False)
        ):
            response.set_cookie(
                CSRF_COOKIE_NAME,
                request.state.csrf_token,
                httponly=True,
                samesite="lax",
                secure=sep_settings.SESSION.SECURE,
                max_age=int(sep_settings.SESSION.MAX_AGE.total_seconds()),
            )

        return response
