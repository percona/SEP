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

"""Declare the list-query dependencies a route injects at the request boundary.

The factory here wraps :func:`~app.core.db.list_query.make_query_param_dep`, which owns
the parameters, the published allowlist ``enum`` and the HTTP 422 for an
out-of-allowlist sort key. What it adds is the resolved value object: row attributes,
for a source that materializes its whole set rather than pushing the query down to a
table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.db.in_memory_list_query import (
    resolve_in_memory_list_query,
    validate_in_memory_spec,
)
from app.core.db.list_query import make_query_param_dep

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.core.db.in_memory_list_query import InMemoryListQuery
    from app.core.db.list_query import ListQuerySpec

__all__ = ["make_in_memory_list_query_dep"]


def make_in_memory_list_query_dep(
    spec: ListQuerySpec,
) -> Callable[..., InMemoryListQuery]:
    """Create a FastAPI dependency yielding a validated ``InMemoryListQuery``.

    The request boundary is Core's, through
    :func:`~app.core.db.list_query.make_query_param_dep`, so this path and the SQL one
    expose the same parameters, publish the same allowlist ``enum`` and descriptions,
    and reject an out-of-allowlist sort key with the same HTTP 422. Only the resolved
    value object differs.

    :param spec: The spec whose allowlist and searchable set bound the request.
    :return: A dependency callable resolving the request into an ``InMemoryListQuery``.
    :raises ValueError: When a spec column expression exposes no name to read off a
        row, so a misdeclared spec fails at wiring time rather than per request.
    """
    validate_in_memory_spec(spec)
    return make_query_param_dep(spec, resolve_in_memory_list_query)
