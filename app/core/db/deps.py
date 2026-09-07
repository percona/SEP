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

from app.core.db.list_query import make_query_param_dep

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.core.db.in_memory_list_query import (
        InMemoryListQuery,
        InMemoryListQueryApplier,
    )
    from app.core.db.list_query import ListQuerySpec

__all__ = ["make_in_memory_list_query_dep"]


def make_in_memory_list_query_dep(
    applier: InMemoryListQueryApplier,
) -> Callable[..., InMemoryListQuery]:
    """Create a FastAPI dependency yielding a validated ``InMemoryListQuery``.

    The request boundary is Core's, through
    :func:`~app.core.db.list_query.make_query_param_dep`, so this path and the SQL one
    expose the same parameters, publish the same allowlist ``enum`` and descriptions,
    and reject an out-of-allowlist sort key with the same HTTP 422. Only the resolved
    value object differs.

    Takes an applier rather than a spec because the caller already holds one: the
    misdeclaration check and the attribute resolution both happened when it was built,
    so neither is repeated here. Call this at wiring time and hand the result to
    ``Depends``; a fresh dependency is built per call rather than cached, because
    FastAPI binds each reflected parameter's ``Query`` declaration to the route it was
    found on.

    :param applier: The spec-bound applier whose allowlist bounds the request.
    :return: A dependency callable resolving the request into an ``InMemoryListQuery``.
    """

    # Core re-passes the spec it was given; the applier already binds it.
    def resolve(
        _spec: ListQuerySpec, sort: str, search: str | None
    ) -> InMemoryListQuery:
        return applier.resolve_query(sort, search)

    return make_query_param_dep(applier.spec, resolve)
