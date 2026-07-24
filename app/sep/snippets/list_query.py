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

This is the first increment of a phased rollout: a self-contained, validated value
object injected only on the snippets list route, deliberately shaped so a future
config-driven framework capability can later produce it in place of the hand-wired
dependency. The shared offset/limit :class:`~app.core.pagination.Pagination` model
is intentionally left untouched — sort and search are per-resource capabilities and
live here, not on the uniform pagination transport.

The sort allowlist maps public sort keys to vetted column/JSON expressions; a raw
client-supplied column name is never interpolated into a query, and an out-of-allowlist
key is rejected at the request boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, field_validator

from app.core.utils.fields import EnumFieldMixin

SERVICE_TYPE_UNCATEGORIZED = "__uncategorized__"
"""Sentinel ``service_type`` value selecting snippets with no service type.

Distinguishes "filter to snippets whose ``meta.service_type`` is absent" (SQL
``IS NULL``) from a real free-form service-type value, which the ``meta.service_type``
frontmatter could never legitimately carry.
"""


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


@dataclass(frozen=True, slots=True)
class SnippetSortColumn:
    """Map a public sort key to a vetted backing expression.

    :param source: ``"column"`` for a first-class ``Snippet`` column, or ``"meta"``
        for a key read out of the ``meta`` JSON column via a dialect-aware extract.
    :param name: The column name or the ``meta`` JSON key.
    """

    source: Literal["column", "meta"]
    name: str


SNIPPET_SORT_KEYS: dict[str, SnippetSortColumn] = {
    "created_at": SnippetSortColumn("column", "created_at"),
    "filename": SnippetSortColumn("column", "filename"),
    "approved_at": SnippetSortColumn("column", "approved_at"),
    "title": SnippetSortColumn("meta", "title"),
    "service_type": SnippetSortColumn("meta", "service_type"),
}
"""Allowlist of public sort keys mapped to their vetted backing expressions."""

DEFAULT_SNIPPET_SORT_KEY = "created_at"

TIE_BREAKER_COLUMN = "filename"
"""Unique column appended to every sort so ordering is deterministic across pages."""


class SnippetListQuery(BaseModel, frozen=True):
    """Carry the validated, immutable snippets list-query selections.

    :param search: Free-text search term matched case-insensitively against the
        filename, title, and description, or ``None`` for no search.
    :param sort_key: The public sort key; must be a member of
        :data:`SNIPPET_SORT_KEYS`.
    :param sort_direction: The sort direction.
    :param approval: The approval-status filter.
    :param service_type: The service-type filter: a free-form value for equality,
        :data:`SERVICE_TYPE_UNCATEGORIZED` for "no service type", or ``None`` for no
        filter.
    """

    search: str | None = None
    sort_key: str = DEFAULT_SNIPPET_SORT_KEY
    sort_direction: SnippetSortDirection = SnippetSortDirection.DESC
    approval: SnippetApprovalFilter = SnippetApprovalFilter.ALL
    service_type: str | None = None

    @field_validator("sort_key")
    @classmethod
    def _validate_sort_key(cls, value: str) -> str:
        """Reject a sort key that is not in the allowlist.

        :param value: The candidate public sort key.
        :return: The validated sort key.
        :raises ValueError: When ``value`` is not a member of :data:`SNIPPET_SORT_KEYS`.
        """
        if value not in SNIPPET_SORT_KEYS:
            allowed = ", ".join(sorted(SNIPPET_SORT_KEYS))
            raise ValueError(f"Invalid sort key {value!r}; allowed: {allowed}.")
        return value
