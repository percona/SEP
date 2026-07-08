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

"""Define tests for the app.sep.apps.alerts.crud module."""

import pytest

from app.core.utils.date_time import utc_now
from app.sep.apps.alerts.crud import AlertBackupManager
from app.sep.apps.alerts.models import AlertBackup

_EXPECTED_BACKUP_COUNT = 2


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

    @pytest.mark.asyncio
    async def test_list_breaks_created_at_ties_by_id_desc(self, session) -> None:
        """Assert ``created_at`` ties fall back to ``id`` descending order."""
        tie = utc_now()
        first = AlertBackup(
            data={"order": "first"}, metadata_={"count": 1}, created_at=tie
        )
        second = AlertBackup(
            data={"order": "second"}, metadata_={"count": 2}, created_at=tie
        )
        await AlertBackupManager.save(session, first)
        await AlertBackupManager.save(session, second)

        results = await AlertBackupManager.list(session)
        assert results[0].created_at == results[1].created_at
        assert [backup.data["order"] for backup in results] == ["second", "first"]
