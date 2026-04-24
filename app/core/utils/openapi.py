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

"""Define OpenAPI helpers for predictable operation IDs."""

from __future__ import annotations

import re
from enum import Enum
from typing import TYPE_CHECKING

from fastapi.utils import generate_unique_id as default_generate_unique_id

if TYPE_CHECKING:
    from fastapi.routing import APIRoute


def generate_tag_prefixed_unique_id(route: APIRoute) -> str:
    """Build a unique OpenAPI operation ID using the first tag plus FastAPI's default.

    Prefix FastAPI's generated ID with a slug from the first ``route.tags`` entry when
    tags exist to avoid collisions between similarly named handlers in different areas
    (for example ``restores_create`` under two plugins). Fall back to the stock
    FastAPI ID when the route has no tags.

    :param route: The FastAPI route being registered.
    :type route: fastapi.routing.APIRoute
    :return: A slug suitable for ``operationId`` in OpenAPI.
    :rtype: str
    """
    base = default_generate_unique_id(route)
    tags = route.tags
    if not tags:
        return base
    first = tags[0]
    label = first.value if isinstance(first, Enum) else str(first)
    prefix = re.sub(r"\W+", "_", label.strip()).strip("_").lower()
    if not prefix:
        return base
    return f"{prefix}_{base}"
