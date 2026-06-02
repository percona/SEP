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

"""Define shared offset/limit pagination models and FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated, Any, Generic, TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

from fastapi import Depends, Query
from pydantic import BaseModel, Field

T = TypeVar("T")
U = TypeVar("U")

MAX_PAGINATION_LIMIT = 200
DEFAULT_PAGINATION_OFFSET = 0
DEFAULT_PAGINATION_LIMIT = 50

__all__ = [
    "DEFAULT_PAGINATION_LIMIT",
    "DEFAULT_PAGINATION_OFFSET",
    "MAX_PAGINATION_LIMIT",
    "PaginatedResponse",
    "Pagination",
    "PaginationDep",
    "fetch_all_dict_items",
    "fetch_all_items",
    "make_pagination_dep",
    "pagination_dep",
]


class Pagination(BaseModel):
    """Validated offset/limit page window for list endpoints and helpers.

    :param offset: Zero-based index of the first item in the page.
    :type offset: int
    :param limit: Maximum number of items in the page.
    :type limit: int
    """

    offset: int = Field(default=DEFAULT_PAGINATION_OFFSET, ge=0)
    limit: int = Field(
        default=DEFAULT_PAGINATION_LIMIT,
        ge=1,
        le=MAX_PAGINATION_LIMIT,
    )

    def as_params(self) -> dict[str, int]:
        """Return query parameters for forwarding pagination to upstream APIs."""
        return {"offset": self.offset, "limit": self.limit}

    def slice(self, seq: Sequence[T]) -> list[T]:
        """Return the page slice of ``seq`` for this offset/limit window.

        :param seq: The sequence to slice.
        :type seq: Sequence[T]
        :return: Items in ``seq`` within this pagination window.
        :rtype: list[T]
        """
        return list(seq[self.offset : self.offset + self.limit])


class PaginatedResponse(BaseModel, Generic[T]):
    """Represent a paginated response envelope.

    :param items: The items returned for the current page.
    :type items: list[T]
    :param total: The total number of matching records across all pages.
    :type total: int
    :param offset: The zero-based starting offset used for this page.
    :type offset: int
    :param limit: The maximum number of items requested for this page.
    :type limit: int
    """

    items: list[T]
    total: int
    offset: int
    limit: int

    @classmethod
    def from_pagination(
        cls,
        items: list[T],
        total: int,
        pagination: Pagination,
    ) -> PaginatedResponse[T]:
        """Build a paginated response echoing the request pagination window.

        :param items: The items returned for the current page.
        :type items: list[T]
        :param total: The total number of matching records across all pages.
        :type total: int
        :param pagination: The pagination window used for this request.
        :type pagination: Pagination
        :return: A paginated response envelope with echoed offset and limit.
        :rtype: PaginatedResponse[T]
        """
        return cls(
            items=items,
            total=total,
            offset=pagination.offset,
            limit=pagination.limit,
        )

    def map_items(self, fn: Callable[[T], U]) -> PaginatedResponse[U]:
        """Transform page items while preserving pagination metadata.

        :param fn: Callable applied to each item on the current page.
        :type fn: Callable[[T], U]
        :return: A paginated response with transformed items and unchanged metadata.
        :rtype: PaginatedResponse[U]
        """
        return PaginatedResponse(
            items=[fn(item) for item in self.items],
            total=self.total,
            offset=self.offset,
            limit=self.limit,
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
    :type offset: int
    :param limit: The maximum number of records to return.
    :type limit: int
    :return: A validated pagination window.
    :rtype: Pagination
    """
    return Pagination(offset=offset, limit=limit)


PaginationDep = Annotated[Pagination, Depends(pagination_dep)]


def make_pagination_dep(
    max_limit: int = MAX_PAGINATION_LIMIT,
) -> Annotated[Pagination, Depends[Any]]:
    """Return a FastAPI dependency type alias with a custom ``limit`` upper bound.

    :param max_limit: Maximum allowed value for the ``limit`` query parameter.
    :type max_limit: int
    :return: An annotated dependency type that parses offset/limit query parameters.
    :rtype: Annotated[Pagination, Depends[Any]]
    """

    def _pagination_dep(
        offset: int = Query(default=DEFAULT_PAGINATION_OFFSET, ge=0),
        limit: int = Query(default=DEFAULT_PAGINATION_LIMIT, ge=1, le=max_limit),
    ) -> Pagination:
        return Pagination(offset=offset, limit=limit)

    return Annotated[Pagination, Depends(_pagination_dep)]


async def fetch_all_items(
    get_page: Callable[[Pagination], Awaitable[PaginatedResponse[T]]],
    *,
    page_size: int = MAX_PAGINATION_LIMIT,
) -> list[T]:
    """Fetch every item by walking paginated upstream responses.

    :param get_page: Async callable returning one page for the given window.
    :type get_page: Callable[[Pagination], Awaitable[PaginatedResponse[T]]]
    :param page_size: ``limit`` used for each upstream request.
    :type page_size: int
    :return: All items across every page, in upstream order.
    :rtype: list[T]
    """
    if page_size < 1:
        msg = "page_size must be at least 1"
        raise ValueError(msg)

    all_items: list[T] = []
    offset = 0
    while True:
        page = await get_page(Pagination(offset=offset, limit=page_size))
        if not page.items:
            break
        all_items.extend(page.items)
        offset += len(page.items)
        if offset >= page.total or len(page.items) < page_size:
            break
    return all_items


async def fetch_all_dict_items(
    fetch_page: Callable[[Pagination], Awaitable[dict[str, Any]]],
    *,
    page_size: int = MAX_PAGINATION_LIMIT,
) -> list[Any]:
    """Fetch every item from paginated dict responses (e.g. RemoteAPI payloads).

    :param fetch_page: Async callable returning one paginated dict per window.
    :type fetch_page: Callable[[Pagination], Awaitable[dict[str, Any]]]
    :param page_size: ``limit`` used for each upstream request.
    :type page_size: int
    :return: All ``items`` across every page, in upstream order.
    :rtype: list[Any]
    """

    async def get_page(pagination: Pagination) -> PaginatedResponse[Any]:
        raw = await fetch_page(pagination)
        if "total" not in raw:
            raw = {**raw, "total": len(raw.get("items", []))}
        if "offset" not in raw:
            raw = {**raw, "offset": pagination.offset}
        if "limit" not in raw:
            raw = {**raw, "limit": pagination.limit}
        return PaginatedResponse.model_validate(raw)

    return await fetch_all_items(get_page, page_size=page_size)
