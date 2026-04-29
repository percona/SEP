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

Plugins migrating to the JSON API + React UI under the API-First Migration
epic (SEP-948) keep their legacy Jinja2 routes mounted while the React UI
matures. Mark every legacy route on an in-flight plugin with this helper so
clients see the RFC 8594 ``Deprecation`` response header and so each
hit is logged at WARNING.

Apply once at router construction:

.. code-block:: python

    from app.sep.plugins.framework.deprecation import (
        mark_jinja2_route_deprecated,
    )

    router = APIRouter(dependencies=[Depends(mark_jinja2_route_deprecated)])
"""

import logging

from fastapi import Request, Response

__all__ = ["mark_jinja2_route_deprecated"]

logger = logging.getLogger(__name__)


def mark_jinja2_route_deprecated(request: Request, response: Response) -> None:
    """Log a deprecation warning and set the ``Deprecation`` response header.

    :param request: The incoming request, used for the path in the log
        message.
    :type request: Request
    :param response: The outgoing response, mutated in place to add the
        ``Deprecation: true`` header.
    :type response: Response
    """
    logger.warning(
        "Jinja2 plugin route %s is deprecated; use the JSON API equivalent "
        "under /api/plugins/",
        request.url.path,
    )
    response.headers["Deprecation"] = "true"
