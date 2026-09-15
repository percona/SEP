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

"""Adapt a materialize-everything source to the framework's list-scripts contract.

The replay itself — sort, search, pagination against in-process objects — belongs to
every service, so it lives in :mod:`app.core.db.in_memory_list_query`, on a spec-bound
applier. What stays here is the app-framework-shaped adapter: a callable honouring the
:attr:`~app.sep.apps.framework.script_source.ScriptSource.list_scripts` protocol, which
is framework vocabulary rather than a Core concern.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from app.core.db.in_memory_list_query import (
        InMemoryListQuery,
        InMemoryListQueryApplier,
    )
    from app.core.pagination import Pagination

__all__ = ["in_memory_list_scripts"]

S = TypeVar("S")


def in_memory_list_scripts(
    materialize: Callable[[], Awaitable[Sequence[S]]],
    applier: InMemoryListQueryApplier,
) -> Callable[
    [InMemoryListQuery | None, Pagination | None], Awaitable[tuple[list[S], int]]
]:
    """Adapt a materialize-everything callable into the widened list-scripts contract.

    A source that fetches its whole set has one honest implementation of all four call
    shapes — query or not, paginated or not — so it is written once here rather than as
    a branch cascade per source. A missing query resolves to the spec default, which is
    what removes the need for an unsorted, unfiltered fallback path.

    Nothing here assumes a script type: any homogeneous sequence of rows exposing the
    spec's attributes works, so a hand-written route outside the script seam can use it.

    :param materialize: Fetches the complete set of rows.
    :param applier: The spec-bound applier replaying the sort, search, and default
        ordering.
    :return: A callable honouring the ``ScriptSource.list_scripts`` contract.
    """

    async def list_scripts(
        list_query: InMemoryListQuery | None, pagination: Pagination | None
    ) -> tuple[list[S], int]:
        return applier.apply(
            await materialize(), list_query or applier.default_query(), pagination
        )

    return list_scripts
