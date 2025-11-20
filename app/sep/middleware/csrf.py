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

"""Define middleware to handle CSRF protection."""

from itsdangerous import BadData, SignatureExpired, URLSafeTimedSerializer

from fastapi.staticfiles import StaticFiles
from fastapi_csrf_protect import CsrfProtect
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

__all__ = ["CSRFMiddleware"]


class CSRFMiddleware(BaseHTTPMiddleware):
    """Manage CSRF protection for HTTP requests and responses."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self.csrf_protect = CsrfProtect()

    def _serializer(self) -> URLSafeTimedSerializer:
        secret_key = self.csrf_protect._secret_key  # noqa: SLF001
        if secret_key is None:  # pragma: no cover - validated during app startup
            msg = "CSRF secret key is not configured. Did you call CsrfProtect.load_config?"
            raise RuntimeError(msg)
        return URLSafeTimedSerializer(secret_key, salt="fastapi-csrf-token")

    def _ensure_csrf_tokens(self, request: Request) -> tuple[str, str]:
        """Reuse an existing CSRF cookie when possible to keep tokens stable."""
        cookie_key = self.csrf_protect._cookie_key  # noqa: SLF001
        signed_token = request.cookies.get(cookie_key)
        serializer = self._serializer()
        if signed_token is not None:
            try:
                csrf_token = serializer.loads(
                    signed_token,
                    max_age=self.csrf_protect._max_age,  # noqa: SLF001
                )
                return csrf_token, signed_token
            except (BadData, SignatureExpired):
                # Invalid or expired cookie, fall through to mint a new token
                ...
        return self.csrf_protect.generate_csrf_tokens()

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Add CSRF tokens to the request state and manage their inclusion in the response.

        :param request: The incoming HTTP request.
        :type request: Request
        :param call_next: The next middleware or endpoint in the ASGI application.
        :type call_next: RequestResponseEndpoint
        :return: The HTTP response with added security headers.
        :rtype: Response
        """
        method = request.method.upper()
        signed_token: str | None = None

        if method == "GET":
            csrf_token, signed_token = self._ensure_csrf_tokens(request)
            request.state.csrf_token = csrf_token

        response = await call_next(request)

        endpoint = request.scope.get("endpoint")
        if (
            method == "GET"
            and signed_token is not None
            and not isinstance(endpoint, StaticFiles)
            and not getattr(request.state, "is_csrf_exempt", False)
        ):
            self.csrf_protect.set_csrf_cookie(signed_token, response)

        return response
