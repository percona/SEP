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

"""SEP-side proxy coverage for HOT overrides at the production call sites.

Each case inserts an override row, runs ``refresh_all`` (the same call path
the SEP lifespan refresher uses), and then asserts the override is visible
at the consumer's call shape -- which varies by consumer:

* ``test_snippets_refresh_route_observes_enable_manual_sync_override`` issues
  a real ``TestClient`` request and spies on the sync helper.
* ``test_sep_proxy_visible_after_refresh`` reads the proxy attribute
  directly -- the exact shape ``app/sep/deps.py`` uses per request.

One representative consumer per SEP-side wrapped settings class is
exercised. The Tasks-side equivalent lives next to the Tasks app at
``tests/app/tasks/test_settings_override_integration.py``.
"""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.pool import StaticPool

from app.api.deps import require_minimum_role_for_unsafe_methods
from app.core.auth.providers.casdoor.models import CasdoorUser
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.settings_override.lifecycle import ProxyEntry, refresh_all
from app.core.settings_override.manager import SettingsOverrideManager
from app.core.settings_override.models import (
    setting_class_token,
    SettingClassEnum,
    SettingOverride,
)
from app.core.utils import json_serializer
from app.sep.config import sep_settings, SEPSettings
from app.sep.deps import (
    get_current_user,
    get_session,
)
from app.sep.main import sep_app
from app.sep.snippets.config import snippets_settings, SnippetsSettings
from tests.app.db_schema import apply_schema


@pytest_asyncio.fixture
async def override_session_maker() -> async_sessionmaker:
    """Provide an in-memory SQLite session maker for the override store."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await apply_schema(conn, SQLModel.metadata)
    try:
        yield get_async_session_maker_from_engine(engine)
    finally:
        await engine.dispose()


def _sep_proxies() -> dict:
    """Return the SEP-side proxy registry mirroring the SEP lifespan wiring."""
    return {
        SettingClassEnum.SEP_SETTINGS: ProxyEntry(sep_settings, SEPSettings),
        SettingClassEnum.SNIPPETS_SETTINGS: ProxyEntry(
            snippets_settings, SnippetsSettings
        ),
    }


async def _insert_override(
    session_maker: async_sessionmaker,
    setting_class: str,
    key: str,
    value: object,
) -> None:
    """Insert one active override row into the override store."""
    async with session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(setting_class=setting_class, key=key, value=value),
        )


@pytest.mark.asyncio
async def test_snippets_refresh_route_observes_enable_manual_sync_override(
    override_session_maker: async_sessionmaker,
    admin_user: CasdoorUser,
    mocker: MockerFixture,
) -> None:
    """``POST /api/apps/snippets/refresh`` reads ``ENABLE_MANUAL_SYNC`` via the proxy.

    The repository's ``settings.yaml`` sets ``ENABLE_MANUAL_SYNC: true``, so
    the baseline request invokes the actual sync. Inserting an override row
    that flips the flag to ``false`` and running ``refresh_all`` must cause
    the route's ``IsManualSyncEnabled`` guard to reject the request before the
    sync helper runs, leaving the spy's await count unchanged.
    """
    update_snippets_spy = mocker.patch(
        "app.sep.apps.snippets.extra_routes.update_snippets",
        new=AsyncMock(return_value=None),
    )

    async def _guard_session() -> AsyncIterator[AsyncSession]:
        # The ``require_app_enabled("snippets")`` route guard reads ``appstate``
        # via ``get_session``; point it at the in-memory store (all tables, no
        # rows -> snippets enabled) so the gate is deterministic and never
        # blocks on a shared, order-dependent DB.
        async with override_session_maker() as guard_session:
            yield guard_session

    sep_app.dependency_overrides[require_minimum_role_for_unsafe_methods] = lambda: None
    sep_app.dependency_overrides[get_current_user] = lambda: admin_user
    sep_app.dependency_overrides[get_session] = _guard_session
    try:
        # Per tests/CLAUDE.md: never wrap TestClient(sep_app) in `with` --
        # that triggers ``sep_lifespan`` and queries the celery beat
        # ``schedule.db`` which is absent in fresh CI. Instantiate
        # directly; the snapshot is wired manually via ``refresh_all``
        # below, so the route observes the override without needing the
        # lifespan to start the refresher.
        client = TestClient(sep_app, raise_server_exceptions=False)
        client.post("/api/apps/snippets/refresh", headers={"Authorization": "Bearer t"})
        assert update_snippets_spy.await_count == 1

        await _insert_override(
            override_session_maker,
            setting_class_token(SnippetsSettings),
            "ENABLE_MANUAL_SYNC",
            value=False,
        )
        await refresh_all(lambda: override_session_maker, _sep_proxies())

        client.post("/api/apps/snippets/refresh", headers={"Authorization": "Bearer t"})
        # The HOT override must short-circuit the route before update_snippets.
        assert update_snippets_spy.await_count == 1
    finally:
        sep_app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_sep_proxy_visible_after_refresh(
    override_session_maker: async_sessionmaker,
) -> None:
    """``sep_settings.CONNECTIVITY_CHECK_DEFAULT`` swaps after refresh.

    Asserting via the proxy (rather than a full route round-trip) is
    sufficient end-to-end coverage because the consumer ``app/sep/deps.py``
    reads the field per-request via attribute access -- exactly the call
    shape the proxy intercepts. The proxy contract itself is tested in
    ``test_proxy.py``; this test fills the SEP-side proxy registry coverage
    gap by exercising the full ``refresh_all`` path against the production
    ``sep_settings`` proxy instance.
    """
    yaml_default = sep_settings.CONNECTIVITY_CHECK_DEFAULT
    override_value = not yaml_default
    await _insert_override(
        override_session_maker,
        setting_class_token(SEPSettings),
        "CONNECTIVITY_CHECK_DEFAULT",
        value=override_value,
    )
    await refresh_all(lambda: override_session_maker, _sep_proxies())
    assert sep_settings.CONNECTIVITY_CHECK_DEFAULT is override_value
