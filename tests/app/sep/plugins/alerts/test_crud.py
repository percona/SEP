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

"""Define tests for the app.sep.plugins.alerts.crud module."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils import json_serializer
from app.sep.plugins.alerts.backup import AlertBackup
from app.sep.plugins.alerts.crud import AlertBackupManager

_EXPECTED_BACKUP_COUNT = 2


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


class TestAlertBackupManager:
    """Test AlertBackupManager CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_and_retrieve(self, session) -> None:
        """Assert an AlertBackup can be created and retrieved."""
        backup = AlertBackup(
            data={"templates": [], "rules": []},
            metadata_={"template_count": 0, "rule_count": 0},
        )
        saved = await AlertBackupManager.save(session, backup)
        assert saved.id is not None
        assert saved.data == {"templates": [], "rules": []}
        assert saved.metadata_ == {"template_count": 0, "rule_count": 0}

    @pytest.mark.asyncio
    async def test_list_ordered_by_created_at_desc(self, session) -> None:
        """Assert backups are listed in descending order by created_at."""
        first = AlertBackup(
            data={"order": "first"},
            metadata_={"count": 1},
        )
        second = AlertBackup(
            data={"order": "second"},
            metadata_={"count": 2},
        )
        await AlertBackupManager.save(session, first)
        await AlertBackupManager.save(session, second)

        results = await AlertBackupManager.list(session)
        assert len(results) == _EXPECTED_BACKUP_COUNT
        assert results[0].data["order"] == "second"
        assert results[1].data["order"] == "first"
