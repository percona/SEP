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
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.datastructures import URL

from app.core.auth.providers.casdoor.models import CasdoorUser
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils import json_serializer
from app.sep.deps import (
    get_api_authenticated_user,
    get_current_user,
    get_session,
    require_bearer_for_unsafe_methods,
    validate_csrf,
)
from app.sep.main import sep_app
from app.sep.snippets.config import snippets_settings
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
    try:
        async with async_session_maker() as session:
            yield session
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def request_less_session(session: AsyncSession, mocker: object) -> AsyncSession:
    """Bind the snippets request-less session maker to the test session.

    The derived listing / per-snippet / execute routes open their own
    request-less session via ``get_async_session_maker`` rather than the
    request-scoped ``get_session`` the other fixtures override, so the maker is
    patched to yield the same in-memory ``session`` the rows are seeded through
    (mirroring ``tests/app/sep/apps/snippets/test_celery.py``). Autouse so every derived-route
    test sees the seeded data; a no-op for tests that never hit that path.
    """
    maker = MagicMock()
    maker.return_value.__aenter__ = AsyncMock(return_value=session)
    maker.return_value.__aexit__ = AsyncMock(return_value=False)
    mocker.patch(
        "app.sep.apps.snippets.script_source.get_async_session_maker",
        return_value=maker,
    )
    return session


@pytest.fixture(autouse=True)
def snippets_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure a base URL so the request-less execute path can build artifact URLs.

    The migrated execute hook reads ``SNIPPETS_BASE_URL`` / ``BASE_URL`` instead of
    deriving the artifact URL from the request, so a base URL must be set or
    ``build_snippet_source`` 400s. The value matches the ``TestClient`` host the
    legacy request-derived fallback produced, keeping artifact URLs unchanged.
    """
    monkeypatch.setattr(
        snippets_settings, "SNIPPETS_BASE_URL", URL("http://testserver")
    )


@pytest.fixture
def snippets_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect :attr:`Snippet.BASE_DIR` to a temporary directory for the test."""
    monkeypatch.setattr(Snippet, "BASE_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def admin_client(admin_user: CasdoorUser, session: AsyncSession) -> TestClient:
    """Return a TestClient authenticated as an admin with the real session."""
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
    sep_app.dependency_overrides[get_current_user] = lambda: admin_user
    sep_app.dependency_overrides[get_session] = lambda: session
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.fixture
def non_admin_client(regular_user: CasdoorUser, session: AsyncSession) -> TestClient:
    """Return a TestClient authenticated as a non-admin user."""
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user
    sep_app.dependency_overrides[get_session] = lambda: session
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.fixture
def api_admin_client(admin_user: CasdoorUser, session: AsyncSession) -> TestClient:
    """Return a TestClient authenticated as an admin via the JSON API auth path."""
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
    sep_app.dependency_overrides[get_current_user] = lambda: admin_user
    sep_app.dependency_overrides[get_api_authenticated_user] = lambda: admin_user
    sep_app.dependency_overrides[get_session] = lambda: session
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.fixture
def api_non_admin_client(
    regular_user: CasdoorUser, session: AsyncSession
) -> TestClient:
    """Return a TestClient authenticated as a non-admin via the JSON API auth path."""
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user
    sep_app.dependency_overrides[get_api_authenticated_user] = lambda: regular_user
    sep_app.dependency_overrides[get_session] = lambda: session
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.fixture
def api_admin_client_no_bearer(
    admin_user: CasdoorUser, session: AsyncSession
) -> TestClient:
    """Return a cookie-auth API admin TestClient with the Bearer gate intact.

    Diverges from the central :func:`tests.app.sep.conftest.api_admin_client_no_bearer`
    by additionally pinning ``get_session`` to the in-memory test ``session``:
    the snippets ``Snippet`` table only exists on that session, so the
    central fixture (no session override) would 500 inside the route. Keep
    this local override; do not delete in favour of the central one without
    first solving the snippets table-visibility constraint.
    """
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[get_current_user] = lambda: admin_user
    sep_app.dependency_overrides[get_api_authenticated_user] = lambda: admin_user
    sep_app.dependency_overrides[get_session] = lambda: session
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.fixture
def api_unauthenticated_client(session: AsyncSession) -> TestClient:
    """Return a TestClient with no auth overrides — every JSON call should 401."""
    sep_app.dependency_overrides[get_session] = lambda: session
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.fixture
def admin_client_no_csrf(admin_user: CasdoorUser, session: AsyncSession) -> TestClient:
    """Return a TestClient authenticated as admin but with real CSRF validation.

    Unlike :func:`admin_client`, ``validate_csrf`` is **not** overridden, so
    requests that omit the CSRF token in their form body will receive a 400.
    """
    sep_app.dependency_overrides[get_current_user] = lambda: admin_user
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
            target = snippets_dir / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("#!/bin/sh\necho hi\n")
        snippet = Snippet(filename=filename, size=20, md5_digest="a" * 32)
        if approved:
            snippet.approve("Seeded as approved", "seed-user")
        return await SnippetManager.create(session, snippet)

    return _factory
