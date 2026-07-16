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
"""Define tests for the shared offset/limit pagination models and helpers."""

from app.core.pagination import build_proxied_page, PaginatedResponse, Pagination

UPSTREAM_TOTAL = 57
FILTERED_UPSTREAM_TOTAL = 999
REQUEST_OFFSET = 10
REQUEST_LIMIT = 5


class TestBuildProxiedPage:
    """Cover the proxied-upstream total-correction helper."""

    def test_passes_through_upstream_total_when_not_filtered(self) -> None:
        """Trust the upstream ``total`` when rows were not filtered locally."""
        items = [1, 2]
        upstream = {"items": items, "total": UPSTREAM_TOTAL, "offset": 0, "limit": 50}
        pagination = Pagination(offset=0, limit=50)

        page = build_proxied_page(
            items, upstream, pagination, client_side_filtered=False
        )

        assert isinstance(page, PaginatedResponse)
        assert page.total == UPSTREAM_TOTAL
        assert page.items == items

    def test_substitutes_len_items_when_filtered(self) -> None:
        """Report the filtered-page count when rows were narrowed locally."""
        items = [1, 2]
        upstream = {
            "items": items,
            "total": FILTERED_UPSTREAM_TOTAL,
            "offset": 0,
            "limit": 50,
        }
        pagination = Pagination(offset=0, limit=50)

        page = build_proxied_page(
            items, upstream, pagination, client_side_filtered=True
        )

        assert page.total == len(items)

    def test_falls_back_to_len_items_when_total_missing(self) -> None:
        """Default ``total`` to the page length when upstream omits ``total``."""
        items = [1, 2, 3]
        upstream = {"items": items}
        pagination = Pagination(offset=0, limit=50)

        page = build_proxied_page(
            items, upstream, pagination, client_side_filtered=False
        )

        assert page.total == len(items)

    def test_echoes_request_offset_and_limit(self) -> None:
        """Echo the request pagination window rather than upstream values."""
        upstream = {"items": [], "total": 0, "offset": 99, "limit": 99}
        pagination = Pagination(offset=REQUEST_OFFSET, limit=REQUEST_LIMIT)

        page = build_proxied_page([], upstream, pagination, client_side_filtered=False)

        assert page.offset == REQUEST_OFFSET
        assert page.limit == REQUEST_LIMIT

    def test_empty_page_reports_zero_total(self) -> None:
        """Return a valid envelope with ``total == 0`` for an empty page."""
        pagination = Pagination(offset=0, limit=50)

        page = build_proxied_page(
            [], {"items": []}, pagination, client_side_filtered=True
        )

        assert page.items == []
        assert page.total == 0
