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

"""Provide the shared in-memory list-query test setup: specs and materialized rows.

The applier's own tests and its dependency factory's tests query the same declared
contract from opposite sides, so the specs and the row type they read attributes off
live here rather than once per test module. Kept as plain module-level values, not
fixtures, because both suites build appliers — and one builds routes — at import time.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import column

from app.core.db.list_query import ListQuerySpec

#: A spec with a multi-key allowlist and two searchable attributes.
SPEC = ListQuerySpec(
    sortable={
        "filename": column("filename"),
        "title": column("title"),
        "created_at": column("created_at"),
    },
    default_sort="-created_at",
    tie_breaker=column("filename"),
    searchable=(column("filename"), column("title")),
)

#: The same shape with search disabled, so ``search`` is never declared.
NO_SEARCH_SPEC = ListQuerySpec(
    sortable={"filename": column("filename")},
    default_sort="filename",
    tie_breaker=column("filename"),
)


@dataclass(frozen=True, slots=True)
class Row:
    """Stand in for a materialized in-memory row the applier queries.

    :param filename: The tie-breaker and a sortable, searchable attribute.
    :param title: A nullable sortable, searchable attribute, exercising NULLS-LAST
        ordering and a missing search value.
    :param created_at: The default sort's attribute.
    """

    filename: str
    title: str | None
    created_at: int


def make_rows(*specs: tuple[str, str | None, int]) -> list[Row]:
    """Build materialized rows from ``(filename, title, created_at)`` triples.

    :param specs: One triple per row, in the order the source materialized them.
    :return: The rows to hand to the applier.
    """
    return [Row(filename=f, title=t, created_at=c) for f, t, c in specs]
