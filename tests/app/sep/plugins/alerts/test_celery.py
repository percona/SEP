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

"""Define tests for the app.sep.celery alert backup task."""

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils import json_serializer
from app.sep.celery import _backup_alert_config
from app.sep.clients.pmm import (
    AlertRule,
    ContactPoint,
    Folder,
    NotificationPolicy,
)
from app.sep.clients.pmm import (
    AlertTemplate as PMMAlertTemplate,
)
from app.sep.plugins.alerts.backup import AlertBackup
from app.sep.plugins.alerts.crud import AlertBackupManager

_MOCK_CONTACT_POINT_COUNT = 2


@pytest_asyncio.fixture
async def session():
    """Create an async db session for testing."""
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


def _mock_pmm_api():
    """Build a mock PMMRemoteAPI with alert methods."""
    api = AsyncMock()
    api.list_templates = AsyncMock(
        return_value=[
            PMMAlertTemplate(name="t1", summary="Template 1", template="yaml1"),
        ]
    )
    api.list_rules = AsyncMock(
        return_value=[
            AlertRule(uid="r1", title="Rule 1"),
        ]
    )
    api.list_contact_points = AsyncMock(
        return_value=[
            ContactPoint(uid="cp1", name="CP 1", type="email"),
            ContactPoint(uid="cp2", name="CP 2", type="slack"),
        ]
    )
    api.get_notification_policy = AsyncMock(
        return_value=NotificationPolicy(
            receiver="default",
        )
    )
    api.list_folders = AsyncMock(
        return_value=[
            Folder(uid="f1", title="Folder 1", id=1),
        ]
    )
    return api


def _patch_pmm_settings(mocker, *, endpoint="https://pmm.example.com", retention=10):
    """Patch sep_settings inside _backup_alert_config."""
    mocker.patch(
        "app.sep.config.sep_settings",
        PMM=MagicMock(
            endpoint=endpoint,
            api_key=MagicMock(get_secret_value=lambda: "key123") if endpoint else None,
            verify_ssl=True,
            backup_interval="every 24 hours",
            backup_retention=retention,
        ),
    )


def _patch_session(mocker, session):
    """Patch get_async_session_maker to return the test session."""
    mock_session_maker = MagicMock()
    mock_session_maker.return_value.__aenter__ = AsyncMock(return_value=session)
    mock_session_maker.return_value.__aexit__ = AsyncMock(return_value=False)
    mocker.patch(
        "app.sep.celery.get_async_session_maker", return_value=mock_session_maker
    )


class TestBackupAlertConfig:
    """Test the _backup_alert_config async function."""

    @pytest.mark.asyncio
    async def test_backup_success(self, session, mocker) -> None:
        """Assert a backup row is created with correct data and metadata."""
        mock_api = _mock_pmm_api()
        _patch_pmm_settings(mocker)
        mocker.patch(
            "app.core.config.settings",
            get_remote_api=AsyncMock(return_value=mock_api),
        )
        _patch_session(mocker, session)

        await _backup_alert_config()

        results = await AlertBackupManager.list(session)
        assert len(results) == 1
        backup = results[0]
        assert backup.metadata_["template_count"] == 1
        assert backup.metadata_["rule_count"] == 1
        assert backup.metadata_["contact_point_count"] == _MOCK_CONTACT_POINT_COUNT
        assert backup.metadata_["folder_count"] == 1
        assert len(backup.data["templates"]) == 1
        assert len(backup.data["rules"]) == 1
        assert len(backup.data["contact_points"]) == _MOCK_CONTACT_POINT_COUNT
        assert len(backup.data["folders"]) == 1

    @pytest.mark.asyncio
    async def test_backup_pmm_not_configured(self, mocker) -> None:
        """Assert no backup is created when PMM is not configured."""
        _patch_pmm_settings(mocker, endpoint=None)
        mock_session_maker = mocker.patch("app.sep.celery.get_async_session_maker")

        await _backup_alert_config()

        mock_session_maker.assert_not_called()

    @pytest.mark.asyncio
    async def test_backup_pmm_api_error(self, mocker) -> None:
        """Assert API errors are logged without crashing the task."""
        _patch_pmm_settings(mocker)
        mock_api = AsyncMock()
        mock_api.list_templates = AsyncMock(
            side_effect=ConnectionError("PMM unreachable")
        )
        mocker.patch(
            "app.core.config.settings",
            get_remote_api=AsyncMock(return_value=mock_api),
        )
        mock_session_maker = mocker.patch("app.sep.celery.get_async_session_maker")

        await _backup_alert_config()

        mock_session_maker.assert_not_called()

    @pytest.mark.asyncio
    async def test_backup_retention_cleanup(self, session, mocker) -> None:
        """Assert oldest backups beyond retention limit are deleted."""
        retention = 3
        for i in range(5):
            backup = AlertBackup(
                data={"index": i},
                metadata_={"count": i},
            )
            await AlertBackupManager.save(session, backup)

        mock_api = _mock_pmm_api()
        _patch_pmm_settings(mocker, retention=retention)
        mocker.patch(
            "app.core.config.settings",
            get_remote_api=AsyncMock(return_value=mock_api),
        )
        _patch_session(mocker, session)

        await _backup_alert_config()

        results = await AlertBackupManager.list(session)
        assert len(results) == retention

    @pytest.mark.asyncio
    async def test_backup_retention_configurable(self, session, mocker) -> None:
        """Assert retention limit is respected with custom value."""
        retention = 2
        for i in range(4):
            backup = AlertBackup(
                data={"index": i},
                metadata_={"count": i},
            )
            await AlertBackupManager.save(session, backup)

        mock_api = _mock_pmm_api()
        _patch_pmm_settings(mocker, retention=retention)
        mocker.patch(
            "app.core.config.settings",
            get_remote_api=AsyncMock(return_value=mock_api),
        )
        _patch_session(mocker, session)

        await _backup_alert_config()

        results = await AlertBackupManager.list(session)
        assert len(results) == retention
