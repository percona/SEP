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

"""Shared OpenAPI response declarations for SEP proxy routes."""

from typing import Any

from fastapi import status

UPSTREAM_TASKS_502_RESPONSE: dict[int | str, dict[str, Any]] = {
    status.HTTP_502_BAD_GATEWAY: {
        "description": "Upstream Tasks API failure.",
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {"detail": {"type": "string"}},
                    "required": ["detail"],
                },
            },
        },
    },
}
"""OpenAPI ``responses=`` entry for an SEP proxy route's upstream-Tasks-API ``502``.

SEP proxy routes that forward to the Tasks sub-app re-raise a
``HTTPBadGatewayException`` on upstream Tasks-API failure. The SEP exception
handler renders that as a JSON ``{"detail": ...}`` body; this constant declares
the matching response schema in OpenAPI so the generated typed client sees the
502 branch and consumers can model the error shape.
"""
