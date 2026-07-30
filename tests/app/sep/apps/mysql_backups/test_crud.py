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

"""Tests for the MySQL backup catalog manager."""

from datetime import datetime, UTC

import pytest

from app.core.pagination import Pagination
from app.sep.apps.mysql_backups.crud import MysqlBackupRunManager
from app.sep.apps.mysql_backups.models import MysqlBackupRun

_PAGE = Pagination()


class TestMysqlBackupRunManager:
    """Cover create/retrieve, newest-first ordering, and per-service filtering."""

    @pytest.mark.asyncio
    async def test_create_and_retrieve(self, session) -> None:
        """Round-trip a saved record with an assigned primary key."""
        record = MysqlBackupRun(
            task_history_id=1,
            service_name="svc-a",
            hostname="db01",
            backup_type="M",
            location="/data/backups/mydumper/svc-a/20260729",
            upload_destination="s3://bucket/svc-a",
            size_bytes=4096,
        )
        saved = await MysqlBackupRunManager.save(session, record)

        assert saved.id is not None
        fetched = await MysqlBackupRunManager.get_or_404(session, id=saved.id)
        assert fetched.service_name == "svc-a"
        assert fetched.location == "/data/backups/mydumper/svc-a/20260729"
        assert fetched.size_bytes == 4096  # noqa: PLR2004

    @pytest.mark.asyncio
    async def test_list_for_service_newest_first(self, session) -> None:
        """Return a service's records newest first (created_at desc)."""
        for i in range(3):
            await MysqlBackupRunManager.save(
                session,
                MysqlBackupRun(
                    task_history_id=i + 1,
                    service_name="svc-a",
                    backup_type="X",
                    location=f"/data/backups/xtrabackup/svc-a/{i}",
                ),
            )

        page = await MysqlBackupRunManager.list_for_service(
            session, "svc-a", pagination=_PAGE
        )

        assert page.total == 3  # noqa: PLR2004
        assert [r.task_history_id for r in page.items] == [3, 2, 1]

    @pytest.mark.asyncio
    async def test_list_for_service_isolates_other_services(self, session) -> None:
        """Return only that service's records for a per-service query."""
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(task_history_id=1, service_name="svc-a", backup_type="M"),
        )
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(task_history_id=2, service_name="svc-b", backup_type="M"),
        )

        page = await MysqlBackupRunManager.list_for_service(
            session, "svc-a", pagination=_PAGE
        )

        assert page.total == 1
        assert page.items[0].service_name == "svc-a"

    @pytest.mark.asyncio
    async def test_orders_by_finished_at_not_insertion_time(self, session) -> None:
        """Sort a late-catalogued older run below a newer completed one.

        The row inserted second finished *earlier*, so ordering by run
        completion must place the first-inserted (later-finishing) row first —
        insertion order alone would get this backwards.
        """
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(
                task_history_id=1,
                service_name="svc-a",
                backup_type="M",
                finished_at=datetime(2026, 7, 29, 3, 0, tzinfo=UTC),
            ),
        )
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(
                task_history_id=2,
                service_name="svc-a",
                backup_type="M",
                finished_at=datetime(2026, 7, 29, 1, 0, tzinfo=UTC),
            ),
        )

        page = await MysqlBackupRunManager.list_for_service(
            session, "svc-a", pagination=_PAGE
        )

        assert [r.task_history_id for r in page.items] == [1, 2]

    @pytest.mark.asyncio
    async def test_empty_service_returns_empty_list(self, session) -> None:
        """Yield an empty list, not an error, for an unknown service."""
        page = await MysqlBackupRunManager.list_for_service(
            session, "nope", pagination=_PAGE
        )
        assert page.items == []
