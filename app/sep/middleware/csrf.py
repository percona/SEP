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

        if method == "GET":
            csrf_token, signed_token = self.csrf_protect.generate_csrf_tokens()
            request.state.csrf_token = csrf_token

        response = await call_next(request)

        endpoint = request.scope.get("endpoint")
        if not isinstance(endpoint, StaticFiles) and not getattr(
            request.state, "is_csrf_exempt", False
        ):
            csrf_cookie_handler = {
                "GET": lambda: self.csrf_protect.set_csrf_cookie(
                    signed_token, response
                ),
                "POST": lambda: None,
            }
            csrf_cookie_handler.get(method, lambda: None)()

        return response
