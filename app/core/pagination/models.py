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

"""Define shared offset/limit pagination models and fetch helpers."""

from __future__ import annotations

from collections.abc import (  # noqa: TC003 — validate_call resolves these at runtime
    Awaitable,
    Callable,
)
from typing import Any, Generic, NotRequired, TYPE_CHECKING, TypedDict, TypeVar

if TYPE_CHECKING:
    from collections.abc import Sequence

from pydantic import BaseModel, Field, PositiveInt, validate_call

T = TypeVar("T")
U = TypeVar("U")

MAX_PAGINATION_LIMIT = 200
DEFAULT_PAGINATION_OFFSET = 0
DEFAULT_PAGINATION_LIMIT = 50


class PaginatedDictPage(TypedDict):
    """Raw paginated upstream API page before envelope normalization.

    :param items: Rows returned for the current page.
    :type items: list[Any]
    :param total: Total matching rows across all pages (filled in when omitted).
    :type total: int | None
    :param offset: Zero-based offset for this page (filled in when omitted).
    :type offset: int | None
    :param limit: Page size for this request (filled in when omitted).
    :type limit: int | None
    """

    items: list[Any]
    total: NotRequired[int]
    offset: NotRequired[int]
    limit: NotRequired[int]


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

    def map_items(self, func: Callable[[T], U]) -> PaginatedResponse[U]:
        """Transform page items while preserving pagination metadata.

        :param func: Callable applied to each item on the current page.
        :type func: Callable[[T], U]
        :return: A paginated response with transformed items and unchanged metadata.
        :rtype: PaginatedResponse[U]
        """
        return PaginatedResponse(
            items=[func(item) for item in self.items],
            total=self.total,
            offset=self.offset,
            limit=self.limit,
        )


@validate_call
async def fetch_all_items(
    get_page: Callable[[Pagination], Awaitable[PaginatedResponse[T]]],
    *,
    page_size: PositiveInt = MAX_PAGINATION_LIMIT,
) -> list[T]:
    """Fetch every item by walking paginated upstream responses.

    :param get_page: Async callable returning one page for the given window.
    :type get_page: Callable[[Pagination], Awaitable[PaginatedResponse[T]]]
    :param page_size: ``limit`` used for each upstream request.
    :type page_size: PositiveInt
    :return: All items across every page, in upstream order.
    :rtype: list[T]
    """
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


@validate_call
async def fetch_all_dict_items(
    fetch_page: Callable[[Pagination], Awaitable[PaginatedDictPage]],
    *,
    page_size: PositiveInt = MAX_PAGINATION_LIMIT,
) -> list[Any]:
    """Fetch every item from paginated dict responses (e.g. RemoteAPI payloads).

    :param fetch_page: Async callable returning one paginated dict per window.
    :type fetch_page: Callable[[Pagination], Awaitable[PaginatedDictPage]]
    :param page_size: ``limit`` used for each upstream request.
    :type page_size: PositiveInt
    :return: All ``items`` across every page, in upstream order.
    :rtype: list[Any]
    """

    async def get_page(pagination: Pagination) -> PaginatedResponse[Any]:
        raw = await fetch_page(pagination)
        envelope: dict[str, Any] = dict(raw)
        if "total" not in envelope:
            envelope["total"] = len(envelope.get("items", []))
        if "offset" not in envelope:
            envelope["offset"] = pagination.offset
        if "limit" not in envelope:
            envelope["limit"] = pagination.limit
        return PaginatedResponse.model_validate(envelope)

    return await fetch_all_items(get_page, page_size=page_size)
