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

"""Define the snippets list-query filter selections.

Sort and search are declared once, entity-level, by
:attr:`~app.sep.snippets.crud.SnippetManager.list_query_spec` and resolved by the Core
request-boundary dependency. What lives here is the per-resource *filter* surface the
snippets list adds on top: approval status and service type. Those are base
restrictions, so they stay separate predicates composed into the applier's whereclause
rather than members of the spec.

The shared offset/limit :class:`~app.core.pagination.Pagination` model is left
untouched — it is serialized whole to upstream query params at many proxy sites, so
per-resource query capabilities never become fields on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from app.core.utils.fields import EnumFieldMixin

if TYPE_CHECKING:
    from app.core.db.list_query import ListQuery


class SnippetApprovalFilter(EnumFieldMixin, StrEnum):
    """Enumerate the approval-status filter selections.

    :cvar ALL: Do not filter on approval status.
    :cvar APPROVED: Keep only approved snippets (``approved_at IS NOT NULL``).
    :cvar NOT_APPROVED: Keep only unapproved snippets (``approved_at IS NULL``).
    """

    ALL = "all"
    APPROVED = "approved"
    NOT_APPROVED = "not_approved"


@dataclass(frozen=True, slots=True, kw_only=True)
class SnippetListQuery:
    """Carry the immutable snippets list-query selections.

    Composes the Core-resolved sort/search with the snippets filters, so the list
    route exposes one value object while the sort allowlist stays Core's single
    authority.

    :param core: The Core-resolved sort/search, carrying already-vetted SQL
        expressions.
    :param approval: The approval-status filter.
    :param service_type: The service-type equality filter: a free-form value matched
        (trimmed) against ``meta.service_type``, or ``None`` for no equality filter.
    :param uncategorized: When ``True``, keep only snippets whose ``meta.service_type``
        is absent or blank. A structurally separate flag (rather than a reserved
        ``service_type`` value) so a real free-form service type can never be
        misread as "no service type". Takes precedence over ``service_type``.
    """

    core: ListQuery
    approval: SnippetApprovalFilter = SnippetApprovalFilter.ALL
    service_type: str | None = None
    uncategorized: bool = False
