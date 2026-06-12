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

"""Define FastAPI dependencies for offset/limit pagination."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, TypeAlias

from fastapi import Depends, Query

from app.core.pagination.models import (
    DEFAULT_PAGINATION_LIMIT,
    DEFAULT_PAGINATION_OFFSET,
    MAX_PAGINATION_LIMIT,
    Pagination,
)


def pagination_dep(
    offset: int = Query(default=DEFAULT_PAGINATION_OFFSET, ge=0),
    limit: int = Query(
        default=DEFAULT_PAGINATION_LIMIT,
        ge=1,
        le=MAX_PAGINATION_LIMIT,
    ),
) -> Pagination:
    """Parse and validate offset/limit query parameters for list endpoints.

    :param offset: The zero-based starting offset for the query results.
    :param limit: The maximum number of records to return.
    :return: A validated pagination window.
    """
    return Pagination(offset=offset, limit=limit)


PaginationDep = Annotated[Pagination, Depends(pagination_dep)]

PaginationDependency: TypeAlias = Callable[..., Pagination]


def make_pagination_dep(
    max_limit: int = MAX_PAGINATION_LIMIT,
) -> PaginationDependency:
    """Create a pagination dependency callable with a custom ``limit`` upper bound.

    Returns the bare dependency callable rather than a wrapped
    ``Annotated[Pagination, Depends(...)]`` alias: only the callable is actually
    parametrized by ``max_limit``, and a callable carries an honest static type,
    whereas a call-produced ``Annotated`` value can only be typed ``Any``. Callers
    form the route dependency by wrapping the result in a module-scope
    ``Annotated[Pagination, Depends(...)]`` alias.

    :param max_limit: Maximum allowed value for the ``limit`` query parameter.
    :return: A dependency callable yielding a validated pagination window.
    :raises ValueError: If ``max_limit`` exceeds ``MAX_PAGINATION_LIMIT``.
    """
    if max_limit > MAX_PAGINATION_LIMIT:
        msg = f"max_limit must not exceed MAX_PAGINATION_LIMIT ({MAX_PAGINATION_LIMIT})"
        raise ValueError(msg)

    default_limit = min(DEFAULT_PAGINATION_LIMIT, max_limit)

    def _pagination_dep(
        offset: int = Query(default=DEFAULT_PAGINATION_OFFSET, ge=0),
        limit: int = Query(default=default_limit, ge=1, le=max_limit),
    ) -> Pagination:
        return Pagination(offset=offset, limit=limit)

    return _pagination_dep
