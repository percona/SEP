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

"""Define helpers for marking Jinja2 plugin routes as deprecated.

Plugins migrating to the JSON API + React UI keep their legacy Jinja2 routes
mounted while the React UI matures. Mark every legacy route on an in-flight
plugin with this helper so clients see the RFC 8594 ``Deprecation`` response
header and so each hit is logged at WARNING.

Apply once at router construction:

.. code-block:: python

    from app.sep.plugins.framework.deprecation import DeprecatedJinja2Route

    router = APIRouter(route_class=DeprecatedJinja2Route)
"""

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute

__all__ = ["DeprecatedJinja2Route"]

logger = logging.getLogger(__name__)


class DeprecatedJinja2Route(APIRoute):
    """:class:`APIRoute` subclass that marks every response as deprecated.

    Logs a WARNING per request and sets ``Deprecation: true`` on the
    outgoing response, regardless of whether the endpoint returns a plain
    value, a :class:`Response` subclass, or a template response. The
    header mutation happens after the handler runs, so it survives
    FastAPI's short-circuit for endpoints that return a ``Response``
    directly.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        """Wrap the default route handler with deprecation logging and header.

        :return: A coroutine handler that logs a WARNING and stamps the
            ``Deprecation: true`` header on the outgoing response.
        :rtype: Callable[[Request], Coroutine[Any, Any, Response]]
        """
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            logger.warning(
                "Jinja2 plugin route %s is deprecated; use the JSON API "
                "equivalent under /api/plugins/",
                request.url.path,
            )
            response = await original_route_handler(request)
            response.headers["Deprecation"] = "true"
            return response

        return custom_route_handler
