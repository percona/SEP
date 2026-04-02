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

"""Define the LogContextMiddleware for per-request log context enrichment."""

import re
from uuid import uuid4

from starlette.background import BackgroundTask
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.log import clear_log_context, set_log_context

CORRELATION_ID_HEADER = "X-Correlation-ID"
_VALID_CORRELATION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class LogContextMiddleware(BaseHTTPMiddleware):
    """Set per-request context variables for log enrichment.

    Generate a unique `request_id` for each request, read or generate a
    `correlation_id` from the incoming `X-Correlation-ID` header, and set
    the `endpoint` path. All context is cleared after the response is sent.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Handle the request lifecycle with log context management.

        :param request: The incoming HTTP request.
        :type request: Request
        :param call_next: The next middleware or route handler.
        :type call_next: RequestResponseEndpoint
        :return: The HTTP response with correlation ID header.
        :rtype: Response
        """
        request_id = uuid4().hex
        raw_correlation_id = request.headers.get(CORRELATION_ID_HEADER)
        if raw_correlation_id and _VALID_CORRELATION_ID.match(raw_correlation_id):
            correlation_id = raw_correlation_id
        else:
            correlation_id = uuid4().hex
        endpoint = request.scope.get("path", "-")

        set_log_context(
            request_id=request_id,
            correlation_id=correlation_id,
            endpoint=endpoint,
        )

        try:
            response = await call_next(request)
        except Exception:
            clear_log_context()
            raise
        else:
            response.headers[CORRELATION_ID_HEADER] = correlation_id
            response.background = BackgroundTask(clear_log_context)
            return response
