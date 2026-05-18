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

"""End-to-end-ish integration tests for the SEP-side override layer."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.pool import StaticPool

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.settings_override.lifecycle import ProxyEntry, refresh_all
from app.core.settings_override.manager import SettingsOverrideManager
from app.core.settings_override.models import SettingClassEnum, SettingOverride
from app.core.utils import json_serializer
from app.sep.config import sep_settings, SEPSettings
from app.sep.middleware.messages.config import messages_settings, MessagesSettings
from app.sep.middleware.messages.models import MessageLevel
from app.sep.snippets.config import snippets_settings, SnippetsSettings


@pytest_asyncio.fixture(name="override_session_maker")
async def _override_session_maker() -> async_sessionmaker:
    """Provide an in-memory SQLite session maker isolated from the main test DB."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    return get_async_session_maker_from_engine(engine)


def _sep_proxies() -> dict:
    """Return the SEP-side proxy registry mirroring the lifespan wiring."""
    return {
        SettingClassEnum.SEP_SETTINGS: ProxyEntry(sep_settings, SEPSettings),
        SettingClassEnum.SNIPPETS_SETTINGS: ProxyEntry(
            snippets_settings, SnippetsSettings
        ),
        SettingClassEnum.MESSAGES_SETTINGS: ProxyEntry(
            messages_settings, MessagesSettings
        ),
    }


@pytest.mark.asyncio
async def test_active_override_flips_value_after_refresh(
    override_session_maker: async_sessionmaker,
) -> None:
    """An active override row flips the value seen by the SEP proxy after refresh.

    The repository's ``settings.yaml`` ships ``CONNECTIVITY_CHECK_DEFAULT: false``,
    so we override to ``true`` to verify the override is observable irrespective
    of which value the operator defaulted to in YAML.
    """
    yaml_default = sep_settings.CONNECTIVITY_CHECK_DEFAULT
    override_value = not yaml_default
    async with override_session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=SettingClassEnum.SEP_SETTINGS,
                key="CONNECTIVITY_CHECK_DEFAULT",
                value=override_value,
            ),
        )
    await refresh_all(lambda: override_session_maker, _sep_proxies())
    assert sep_settings.CONNECTIVITY_CHECK_DEFAULT is override_value


@pytest.mark.asyncio
async def test_inactive_override_falls_back_to_yaml_default(
    override_session_maker: async_sessionmaker,
) -> None:
    """Deactivating the override row returns the proxy to the YAML default."""
    yaml_default = sep_settings.CONNECTIVITY_CHECK_DEFAULT
    override_value = not yaml_default
    async with override_session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=SettingClassEnum.SEP_SETTINGS,
                key="CONNECTIVITY_CHECK_DEFAULT",
                value=override_value,
            ),
        )
    await refresh_all(lambda: override_session_maker, _sep_proxies())
    assert sep_settings.CONNECTIVITY_CHECK_DEFAULT is override_value

    async with override_session_maker() as session:
        await SettingsOverrideManager.update_where(
            session,
            {"is_active": False},
            setting_class=SettingClassEnum.SEP_SETTINGS,
            key="CONNECTIVITY_CHECK_DEFAULT",
        )
    await refresh_all(lambda: override_session_maker, _sep_proxies())
    assert sep_settings.CONNECTIVITY_CHECK_DEFAULT is yaml_default


@pytest.mark.asyncio
async def test_artifact_download_ttl_override_seen_at_validation_time(
    override_session_maker: async_sessionmaker,
) -> None:
    """The artifact-download TTL override is observable from the proxy.

    ``app/sep/routes/artifacts.py`` reads ``sep_settings.ARTIFACT_DOWNLOAD_TTL``
    at validation time inside the request handler; an override therefore
    affects every download token the next time validation runs.
    """
    override_ttl_seconds = 60
    async with override_session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=SettingClassEnum.SEP_SETTINGS,
                key="ARTIFACT_DOWNLOAD_TTL",
                value=override_ttl_seconds,
            ),
        )
    await refresh_all(lambda: override_session_maker, _sep_proxies())
    assert override_ttl_seconds == sep_settings.ARTIFACT_DOWNLOAD_TTL


@pytest.mark.asyncio
async def test_snippets_enable_manual_sync_override(
    override_session_maker: async_sessionmaker,
) -> None:
    """The snippets ``ENABLE_MANUAL_SYNC`` flag is observable through the proxy."""
    yaml_default = snippets_settings.ENABLE_MANUAL_SYNC
    override_value = not yaml_default
    async with override_session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=SettingClassEnum.SNIPPETS_SETTINGS,
                key="ENABLE_MANUAL_SYNC",
                value=override_value,
            ),
        )
    await refresh_all(lambda: override_session_maker, _sep_proxies())
    assert snippets_settings.ENABLE_MANUAL_SYNC is override_value


@pytest.mark.asyncio
async def test_messages_level_override(
    override_session_maker: async_sessionmaker,
) -> None:
    """The messages middleware ``LEVEL`` field is observable through the proxy."""
    warning_level = MessageLevel.WARNING
    async with override_session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=SettingClassEnum.MESSAGES_SETTINGS,
                key="LEVEL",
                value=warning_level,
            ),
        )
    await refresh_all(lambda: override_session_maker, _sep_proxies())
    assert warning_level == messages_settings.LEVEL


@pytest.mark.asyncio
async def test_per_class_isolation_prevents_key_leak(
    override_session_maker: async_sessionmaker,
) -> None:
    """A row for one class never bleeds into another class's snapshot.

    Insert a ``(SEP_SETTINGS, ENABLE_MANUAL_SYNC)`` row -- the key only exists
    on ``SnippetsSettings``. The cache must drop it as "unknown field" rather
    than apply it to the wrong class.
    """
    yaml_default = snippets_settings.ENABLE_MANUAL_SYNC
    async with override_session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=SettingClassEnum.SEP_SETTINGS,
                key="ENABLE_MANUAL_SYNC",
                value=not yaml_default,
            ),
        )
    await refresh_all(lambda: override_session_maker, _sep_proxies())
    assert snippets_settings.ENABLE_MANUAL_SYNC is yaml_default
