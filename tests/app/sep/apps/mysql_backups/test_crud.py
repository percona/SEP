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
from typing import Any

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

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
            service_id=7,
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
        assert fetched.service_id == 7  # noqa: PLR2004
        assert fetched.location == "/data/backups/mydumper/svc-a/20260729"
        assert fetched.size_bytes == 4096  # noqa: PLR2004

    @pytest.mark.asyncio
    async def test_service_id_defaults_to_none(self, session) -> None:
        """Leave ``service_id`` empty for a record written without one."""
        saved = await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(task_history_id=1, service_name="svc-a", backup_type="M"),
        )

        fetched = await MysqlBackupRunManager.get_or_404(session, id=saved.id)
        assert fetched.service_id is None

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


async def _save(session: AsyncSession, **fields: Any) -> None:
    """Persist one catalog row, defaulting the fields these tests do not vary.

    :param session: The database session to write on.
    :param fields: The ``MysqlBackupRun`` column values this row varies.
    """
    await MysqlBackupRunManager.save(session, MysqlBackupRun(backup_type="M", **fields))


class TestListForServiceKey:
    """Cover the id-preferred query key and its service-name fallback."""

    @pytest.mark.asyncio
    async def test_id_keyed_query_survives_a_rename(self, session) -> None:
        """Return a row recorded under the service's *old* name.

        The rename this key exists to survive: the row was written when the
        service was called ``old-name``, and the caller now resolves that same
        inventory id to ``new-name``.
        """
        await _save(session, task_history_id=1, service_name="old-name", service_id=7)

        page = await MysqlBackupRunManager.list_for_service(
            session, "new-name", service_id=7, pagination=_PAGE
        )

        assert page.total == 1
        assert page.items[0].task_history_id == 1

    @pytest.mark.asyncio
    async def test_id_less_row_reachable_through_its_recorded_name(
        self, session
    ) -> None:
        """Serve a row carrying no id through the name it was written with."""
        await _save(session, task_history_id=1, service_name="svc-a", service_id=None)

        page = await MysqlBackupRunManager.list_for_service(
            session, "svc-a", service_id=7, pagination=_PAGE
        )

        assert page.total == 1
        assert page.items[0].service_id is None

    @pytest.mark.asyncio
    async def test_id_keyed_query_isolates_same_named_services(self, session) -> None:
        """Return only the queried service's rows when two share a name.

        ``Service.name`` carries no uniqueness constraint, so a name-only key
        merged both services' runs under either id. Each id must now see only its
        own.
        """
        await _save(session, task_history_id=1, service_name="shared", service_id=7)
        await _save(session, task_history_id=2, service_name="shared", service_id=8)

        page = await MysqlBackupRunManager.list_for_service(
            session, "shared", service_id=7, pagination=_PAGE
        )

        assert page.total == 1
        assert page.items[0].task_history_id == 1

    @pytest.mark.asyncio
    async def test_name_only_query_matches_every_row_with_that_name(
        self, session
    ) -> None:
        """Match on the name alone when no id is known.

        The free-typed restore destination: the submitted value has no inventory
        row, so the name is the only key available and every row recorded under it
        is a candidate, id-carrying or not.
        """
        await _save(session, task_history_id=1, service_name="typed", service_id=None)
        await _save(session, task_history_id=2, service_name="typed", service_id=7)

        page = await MysqlBackupRunManager.list_for_service(
            session, "typed", pagination=_PAGE
        )

        assert page.total == 2  # noqa: PLR2004
        assert {r.task_history_id for r in page.items} == {1, 2}

    @pytest.mark.asyncio
    async def test_total_counts_exactly_the_returned_rows(self, session) -> None:
        """Keep the reported total consistent with the widened key.

        The restore selector pages until it fills its option cap and terminates on
        this total, so a count computed from a different predicate than the page
        would truncate the option list.
        """
        await _save(session, task_history_id=1, service_name="shared", service_id=7)
        await _save(session, task_history_id=2, service_name="shared", service_id=None)
        await _save(session, task_history_id=3, service_name="shared", service_id=8)
        await _save(session, task_history_id=4, service_name="other", service_id=None)

        first = await MysqlBackupRunManager.list_for_service(
            session, "shared", service_id=7, pagination=Pagination(offset=0, limit=1)
        )
        second = await MysqlBackupRunManager.list_for_service(
            session, "shared", service_id=7, pagination=Pagination(offset=1, limit=100)
        )

        assert first.total == 2  # noqa: PLR2004
        assert first.total == second.total
        assert len(first.items) + len(second.items) == first.total

    @pytest.mark.asyncio
    async def test_id_less_row_is_lost_once_its_service_is_renamed(
        self, session
    ) -> None:
        """Leave a row unreachable when it predates the id *and* was renamed.

        The accepted limit of having no backfill: the row carries no id to key on
        and no longer matches the service's current name. Pinned so a future change
        cannot widen the key back to an unguarded name match — which would reach
        this row at the cost of merging two same-named services again.
        """
        await _save(session, task_history_id=1, service_name="old-name")

        page = await MysqlBackupRunManager.list_for_service(
            session, "new-name", service_id=7, pagination=_PAGE
        )

        assert page.total == 0
        assert page.items == []
