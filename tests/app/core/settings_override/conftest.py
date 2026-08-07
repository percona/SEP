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

"""Fixtures for ``tests/app/core/settings_override/``."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.pool import StaticPool

from app.core.config import settings
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils import json_serializer

#: Importable path patched when tests replace ``start_refresh_task``.
START_REFRESH_TASK = "app.core.settings_override.worker.start_refresh_task"


class HangingSession:
    """Stand in for an async session whose enter hangs until cancelled."""

    async def __aenter__(self) -> "HangingSession":
        await asyncio.Event().wait()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


def hanging_session_maker_factory() -> type[HangingSession]:
    """Return a session maker whose sessions hang on enter."""
    return HangingSession


def recording_start_refresh_task(
    recorded: dict[str, object],
) -> Callable[..., Awaitable[asyncio.Task]]:
    """Build a stand-in ``start_refresh_task`` that records call kwargs.

    :param recorded: Mutable mapping filled with ``callbacks`` and
        ``seed_timeout`` from each invocation.
    :return: An async callable matching ``start_refresh_task``'s signature.
    """

    async def _fake_start(
        session_maker_factory: object,
        proxies: object,
        interval: object,
        callbacks: object = None,
        *,
        seed_timeout: float | None = None,
    ) -> asyncio.Task:
        recorded["callbacks"] = callbacks
        recorded["seed_timeout"] = seed_timeout
        return asyncio.create_task(asyncio.sleep(3600))

    return _fake_start


@pytest.fixture(autouse=True)
def _propagate_cache_logs() -> None:
    """Allow ``caplog`` to see ``app.core.settings_override.cache`` warnings.

    The application's ``LOGGING_CONFIG`` sets ``propagate=False`` on the
    ``app`` logger, which prevents pytest's ``caplog`` (attached to root) from
    seeing records emitted by ``app.*`` loggers. Temporarily re-enable
    propagation on the ``app`` parent for the duration of the test.
    """
    app_logger = logging.getLogger("app")
    previous = app_logger.propagate
    app_logger.propagate = True
    yield
    app_logger.propagate = previous


@pytest.fixture(name="restrict")
def restrict_fixture(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Return a callable pinning ``SETTINGS_OVERRIDE.ALLOWED_KEYS`` to given entries.

    Pins the value on the already-constructed proxy rather than through the
    environment, which the singleton no longer reads.

    :param monkeypatch: The pytest patcher whose undo restores the real value.
    :return: A callable taking the ``"ClassName.KEY"`` entries to allow.
    """

    def _restrict(*entries: str) -> None:
        monkeypatch.setattr(settings.SETTINGS_OVERRIDE, "ALLOWED_KEYS", set(entries))

    return _restrict


@pytest_asyncio.fixture(name="session")
async def session_fixture() -> AsyncSession:
    """Create an in-memory SQLite async session for override tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
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
