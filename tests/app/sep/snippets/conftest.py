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

"""Define shared fixtures for the ``tests/app/sep/snippets`` subtree."""

from collections.abc import Awaitable, Callable

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models import Snippet
from app.sep.snippets.models.meta import (
    META_KEY_DESCRIPTION,
    META_KEY_SERVICE_TYPE,
    META_KEY_TITLE,
)

SeedSnippet = Callable[..., Awaitable[Snippet]]


@pytest.fixture(autouse=True)
def _bind_request_less_session(request_less_session: AsyncSession) -> None:
    """Apply the request-less session binding to every test in this subtree.

    Autouse so the ``script_source`` tests see the seeded data; a no-op for tests
    that never open a request-less session.
    """


@pytest.fixture
def seed_snippet() -> SeedSnippet:
    """Return an async factory persisting a Snippet with given meta and approval.

    Promoted here so the SQLite and PostgreSQL list-query tests share one seeding
    definition instead of re-declaring the row shape per module.

    :return: An awaitable ``(session, filename, *, title, description,
        service_type, approved)`` factory returning the persisted snippet.
    """

    async def _seed(
        session: AsyncSession,
        filename: str,
        *,
        title: str | None = None,
        description: str | None = None,
        service_type: str | None = None,
        approved: bool = False,
    ) -> Snippet:
        meta: dict[str, str] = {}
        if title is not None:
            meta[META_KEY_TITLE] = title
        if description is not None:
            meta[META_KEY_DESCRIPTION] = description
        if service_type is not None:
            meta[META_KEY_SERVICE_TYPE] = service_type
        snippet = Snippet(filename=filename, size=10, md5_digest="a" * 32, meta=meta)
        if approved:
            snippet.approve("Seeded as approved", "seed-user")
        return await SnippetManager.create(session, snippet)

    return _seed
