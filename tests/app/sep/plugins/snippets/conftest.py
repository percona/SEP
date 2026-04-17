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

"""Define shared fixtures for the snippets plugin tests."""

from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils import json_serializer
from app.models import CasdoorUser
from app.sep.deps import get_current_user, get_session, validate_csrf
from app.sep.main import sep_app
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models import Snippet


@pytest_asyncio.fixture(name="session")
async def session_fixture() -> AsyncSession:
    """Create an async database session backed by in-memory SQLite."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session_maker = get_async_session_maker_from_engine(engine)
    async with async_session_maker() as session:
        yield session


@pytest.fixture
def snippets_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect :attr:`Snippet.BASE_DIR` to a temporary directory for the test."""
    monkeypatch.setattr(Snippet, "BASE_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def admin_client(admin_user: CasdoorUser, session: AsyncSession) -> TestClient:
    """Return a TestClient authenticated as an admin with the real session."""
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[get_current_user] = lambda: admin_user
    sep_app.dependency_overrides[get_session] = lambda: session
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.fixture
def non_admin_client(regular_user: CasdoorUser, session: AsyncSession) -> TestClient:
    """Return a TestClient authenticated as a non-admin user."""
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user
    sep_app.dependency_overrides[get_session] = lambda: session
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.fixture
def create_snippet(
    session: AsyncSession, snippets_dir: Path
) -> Callable[..., Awaitable[Snippet]]:
    """Return an async callable that seeds a Snippet row + its file on disk.

    The callable accepts ``filename`` plus keyword arguments ``approved`` and
    ``create_file`` (both default-friendly) and returns the persisted instance.

    :param session: The in-memory test session.
    :type session: AsyncSession
    :param snippets_dir: The tmp directory aliased as ``Snippet.BASE_DIR``.
    :type snippets_dir: Path
    :return: An async factory function.
    :rtype: Callable[..., Awaitable[Snippet]]
    """

    async def _factory(
        filename: str, *, approved: bool = False, create_file: bool = True
    ) -> Snippet:
        if create_file:
            (snippets_dir / filename).write_text("#!/bin/sh\necho hi\n")
        snippet = Snippet(filename=filename, size=20, md5_digest="a" * 32)
        if approved:
            snippet.approve("Seeded as approved", "seed-user")
        return await SnippetManager.create(session, snippet)

    return _factory
