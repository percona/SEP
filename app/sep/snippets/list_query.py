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

"""Define the opt-in sort/search/filter list-query value object for snippets.

A self-contained, validated value object injected only on the snippets list route.
The shared offset/limit :class:`~app.core.pagination.Pagination` model is left
untouched — sort and search are per-resource capabilities and live here, not on the
uniform pagination transport.

The sort allowlist maps public sort keys to vetted column/JSON expressions; a raw
client-supplied column name is never interpolated into a query, and an out-of-allowlist
key is rejected at the request boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from app.core.utils.fields import EnumFieldMixin
from app.sep.snippets.models.meta import META_KEY_SERVICE_TYPE, META_KEY_TITLE


class SnippetApprovalFilter(EnumFieldMixin, StrEnum):
    """Enumerate the approval-status filter selections.

    :cvar ALL: Do not filter on approval status.
    :cvar APPROVED: Keep only approved snippets (``approved_at IS NOT NULL``).
    :cvar NOT_APPROVED: Keep only unapproved snippets (``approved_at IS NULL``).
    """

    ALL = "all"
    APPROVED = "approved"
    NOT_APPROVED = "not_approved"


class SnippetSortDirection(EnumFieldMixin, StrEnum):
    """Enumerate the sort direction.

    :cvar ASC: Ascending order.
    :cvar DESC: Descending order.
    """

    ASC = "asc"
    DESC = "desc"


class SnippetSortKey(EnumFieldMixin, StrEnum):
    """Enumerate the allowlisted public sort keys.

    Membership is the type: an out-of-allowlist key fails to coerce at the
    request boundary, so no raw client-supplied column name can reach a query.

    :cvar CREATED_AT: Sort by the ``created_at`` column.
    :cvar FILENAME: Sort by the ``filename`` column.
    :cvar APPROVED_AT: Sort by the ``approved_at`` column.
    :cvar TITLE: Sort by the ``meta.title`` JSON value.
    :cvar SERVICE_TYPE: Sort by the ``meta.service_type`` JSON value.
    """

    CREATED_AT = "created_at"
    FILENAME = "filename"
    APPROVED_AT = "approved_at"
    TITLE = "title"
    SERVICE_TYPE = "service_type"


@dataclass(frozen=True, slots=True)
class SnippetSortColumn:
    """Map a public sort key to a vetted backing expression.

    :param source: ``"column"`` for a first-class ``Snippet`` column, or ``"meta"``
        for a key read out of the ``meta`` JSON column via a dialect-aware extract.
    :param name: The column name or the ``meta`` JSON key.
    """

    source: Literal["column", "meta"]
    name: str


SNIPPET_SORT_KEYS: dict[SnippetSortKey, SnippetSortColumn] = {
    SnippetSortKey.CREATED_AT: SnippetSortColumn("column", "created_at"),
    SnippetSortKey.FILENAME: SnippetSortColumn("column", "filename"),
    SnippetSortKey.APPROVED_AT: SnippetSortColumn("column", "approved_at"),
    SnippetSortKey.TITLE: SnippetSortColumn("meta", META_KEY_TITLE),
    SnippetSortKey.SERVICE_TYPE: SnippetSortColumn("meta", META_KEY_SERVICE_TYPE),
}
"""Allowlist of public sort keys mapped to their vetted backing expressions."""

DEFAULT_SNIPPET_SORT_KEY = SnippetSortKey.CREATED_AT

TIE_BREAKER_COLUMN = "filename"
"""Unique column appended to every sort so ordering is deterministic across pages."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SnippetListQuery:
    """Carry the immutable snippets list-query selections.

    :param search: Free-text search term matched case-insensitively against the
        filename, title, and description, or ``None`` for no search.
    :param sort_key: The allowlisted public sort key.
    :param sort_direction: The sort direction.
    :param approval: The approval-status filter.
    :param service_type: The service-type equality filter: a free-form value matched
        (trimmed) against ``meta.service_type``, or ``None`` for no equality filter.
    :param uncategorized: When ``True``, keep only snippets whose ``meta.service_type``
        is absent or blank. A structurally separate flag (rather than a reserved
        ``service_type`` value) so a real free-form service type can never be
        misread as "no service type". Takes precedence over ``service_type``.
    """

    search: str | None = None
    sort_key: SnippetSortKey = DEFAULT_SNIPPET_SORT_KEY
    sort_direction: SnippetSortDirection = SnippetSortDirection.DESC
    approval: SnippetApprovalFilter = SnippetApprovalFilter.ALL
    service_type: str | None = None
    uncategorized: bool = False
