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

"""Tests for MySQL restore backup-source Choice options mapping and route."""

from datetime import datetime, UTC
from unittest.mock import AsyncMock

import pytest
from fastapi import status
from httpx import Response
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import (
    HTTPNotFoundException,
    HTTPServiceUnavailableException,
)
from app.core.pagination import (
    DEFAULT_PAGINATION_LIMIT,
    PaginatedResponse,
    Pagination,
)
from app.extensions.apps.framework.schema import Choice
from app.extensions.apps.mysql_backups.backup_source_choices import (
    _MAX_CHOICE_SCAN_PAGES,
    backup_run_to_choice,
    backup_source_label,
    choices_for_service,
)
from app.extensions.apps.mysql_backups.crud import MysqlBackupRunManager
from app.extensions.apps.mysql_backups.models import (
    BackupType,
    CatalogServiceKey,
    MysqlBackupRun,
    preferred_backup_source,
    restore_valid_backup_source,
    UNKNOWN_SERVICE_SENTINEL,
)
from tests.app.extensions.apps.mysql_backups.conftest import (
    authenticated_get,
    inventory_mock,
    service_payload,
)

_URL = "/api/apps/mysql_backups/backup-sources/choices"


def _catalog_run(
    task_history_id: int,
    location: str | None,
    *,
    finished_at: datetime | None = None,
    upload_destination: str | None = None,
    size_bytes: int | None = None,
    backup_type: str = "M",
) -> MysqlBackupRun:
    """Build an unsaved catalog row for service ``svc-a``.

    :param task_history_id: The task-history id recorded on the row.
    :param location: The recorded location, or ``None`` for an unusable row.
    :param finished_at: When the run finished, or ``None`` if never reported.
    :param upload_destination: The uploaded copy's destination, if any.
    :param size_bytes: The recorded dump size, if any.
    :param backup_type: The catalogued backup type code.
    :return: An unsaved catalog row.
    """
    return MysqlBackupRun(
        task_history_id=task_history_id,
        service_name="svc-a",
        backup_type=backup_type,
        location=location,
        finished_at=finished_at,
        upload_destination=upload_destination,
        size_bytes=size_bytes,
    )


class TestBackupSourceMapper:
    """Map catalog rows onto restore-valid ``Choice`` options."""

    def test_choice_skipped_when_no_usable_value(self) -> None:
        """Skip rows that cannot produce a non-empty Choice value."""
        run = MysqlBackupRun(
            task_history_id=1,
            service_name="svc",
            backup_type="M",
        )
        assert backup_run_to_choice(run) is None

    def test_choice_skipped_when_shell_unsafe(self) -> None:
        """Skip locations the restore shell-safety validator would reject."""
        run = MysqlBackupRun(
            task_history_id=1,
            service_name="svc",
            backup_type="M",
            location="$(id)/evil",
        )
        assert backup_run_to_choice(run) is None

    def test_choice_skipped_when_preferred_candidate_is_unsafe(self) -> None:
        """Skip a row whose upload destination is unsafe, without using its location.

        Falling back would offer the local copy under a row whose authoritative
        source is the upload destination, seeding a restore from a different
        artifact than the one the caller picked.
        """
        run = MysqlBackupRun(
            task_history_id=1,
            service_name="svc",
            backup_type="M",
            location="/backups/mydumper/safe",
            upload_destination="s3://bucket/`whoami`",
        )
        assert backup_run_to_choice(run) is None

    def test_choice_maps_value_and_label(self) -> None:
        """Emit a Choice whose value is restore-valid and label is human-readable."""
        finished = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
        run = MysqlBackupRun(
            task_history_id=1,
            service_name="svc",
            backup_type="M",
            location="/backups/mydumper/20240101",
            size_bytes=1_073_741_824,
            finished_at=finished,
        )
        choice = backup_run_to_choice(run)
        assert choice is not None
        assert choice.value == "/backups/mydumper/20240101"
        assert "Mydumper" in choice.label
        assert "2026-07-29" in choice.label
        assert "1.0 GiB" in choice.label
        assert "/backups/mydumper/20240101" in choice.label

    @pytest.mark.parametrize(
        ("backup_type", "expected"),
        [(BackupType.MYDUMPER, "Mydumper"), (BackupType.XTRABACKUP, "XtraBackup")],
    )
    def test_choice_labels_a_catalogued_backup_type(
        self, backup_type: BackupType, expected: str
    ) -> None:
        """Render a catalogued run's label from the enum's single label source.

        Only mydumper and xtrabackup runs are ever catalogued, so those are the
        values this selector can be asked to label.
        """
        run = MysqlBackupRun(
            task_history_id=1,
            service_name="svc",
            backup_type=backup_type,
            location=f"/backups/{backup_type.value}",
        )

        choice = backup_run_to_choice(run)

        assert choice is not None
        assert expected in choice.label

    def test_choice_falls_back_to_the_raw_value_when_unlabelled(self) -> None:
        """Render a stored code the enum no longer declares as the code itself."""
        run = MysqlBackupRun.model_construct(
            task_history_id=1,
            service_name="svc",
            backup_type="Z",
            location="/backups/legacy",
            finished_at=None,
            size_bytes=None,
        )

        choice = backup_run_to_choice(run)

        assert choice is not None
        assert choice.label.startswith("Z ")


class TestBackupSourceResolvers:
    """Resolve a run's raw source fields to a restore-form-valid value."""

    def test_prefers_upload_destination(self) -> None:
        """Prefer the upload destination when one was configured."""
        assert (
            preferred_backup_source("s3://bucket/base", "/backups/x/base")
            == "s3://bucket/base"
        )

    def test_falls_back_to_location(self) -> None:
        """Fall back to the on-disk location when the upload destination is blank."""
        assert preferred_backup_source("   ", "/backups/x/base") == "/backups/x/base"

    def test_strips_the_chosen_candidate(self) -> None:
        """Return the candidate with surrounding whitespace removed."""
        assert (
            preferred_backup_source("  s3://bucket/base  ", None) == "s3://bucket/base"
        )

    def test_none_when_both_blank(self) -> None:
        """Return ``None`` when neither field holds a non-blank value."""
        assert preferred_backup_source(None, "   ") is None

    def test_restore_valid_returns_an_accepted_candidate(self) -> None:
        """Return the preferred candidate when the restore form would accept it."""
        assert (
            restore_valid_backup_source(None, "/backups/mydumper/20240101")
            == "/backups/mydumper/20240101"
        )

    def test_restore_valid_rejects_without_falling_back(self) -> None:
        """Return ``None`` for a rejected candidate rather than using the other field.

        Judging each field independently would return the location for a run whose
        upload destination is the source it actually wrote to.
        """
        assert (
            restore_valid_backup_source("s3://bucket/`whoami`", "/backups/safe") is None
        )

    def test_restore_valid_none_when_nothing_to_resolve(self) -> None:
        """Return ``None`` when the run recorded no source at all."""
        assert restore_valid_backup_source(None, None) is None


class TestBackupSourceChoicesRoute:
    """Serve Choice options for the restore backup-source selector."""

    async def _get(
        self,
        session: AsyncSession,
        service_id: int | str | None,
        inventory: AsyncMock,
        regular_user: object,
    ) -> Response:
        """Drive the route with the given session + inventory mock, authenticated."""
        params = None if service_id is None else {"service_id": service_id}
        return await authenticated_get(
            _URL,
            session=session,
            inventory=inventory,
            user=regular_user,
            params=params,
        )

    @staticmethod
    async def _newest_run(session: AsyncSession) -> MysqlBackupRun:
        """Return the newest catalogued run as the selector's own query reads it.

        Reading the row back keeps the expected label free of assumptions about
        how the session backend renders a stored timestamp.

        :param session: The database session the catalog is queried on.
        :return: The first row of the service's newest-first catalog page.
        """
        page = await MysqlBackupRunManager.list_for_service(
            session,
            CatalogServiceKey(service_name="svc-a", service_id=1),
            pagination=Pagination(offset=0, limit=1),
        )
        return page.items[0]

    @pytest.mark.asyncio
    async def test_returns_choices_newest_first(self, session, regular_user) -> None:
        """Return Choice options for a service, newest finished run first."""
        older = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
        newer = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(
                task_history_id=1,
                service_name="svc-a",
                backup_type="M",
                location="/data/mydumper/old",
                finished_at=older,
            ),
        )
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(
                task_history_id=2,
                service_name="svc-a",
                backup_type="X",
                location="/data/xtrabackup/base",
                upload_destination="s3://bucket/base",
                finished_at=newer,
                size_bytes=100,
            ),
        )
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(
                task_history_id=3,
                service_name="svc-a",
                backup_type="M",
            ),
        )

        response = await self._get(
            session, 1, inventory_mock(service_payload("svc-a")), regular_user
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert [item["value"] for item in body] == [
            "s3://bucket/base",
            "/data/mydumper/old",
        ]
        assert "XtraBackup" in body[0]["label"]
        assert "s3://bucket/base" in body[0]["label"]

    @pytest.mark.asyncio
    async def test_excludes_other_services(self, session, regular_user) -> None:
        """Return only the requested service's choices."""
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(
                task_history_id=1,
                service_name="svc-a",
                backup_type="M",
                location="/a",
            ),
        )
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(
                task_history_id=2,
                service_name="svc-b",
                backup_type="M",
                location="/b",
            ),
        )

        response = await self._get(
            session, 1, inventory_mock(service_payload("svc-a")), regular_user
        )

        assert [item["value"] for item in response.json()] == ["/a"]

    @pytest.mark.asyncio
    async def test_empty_catalog_returns_empty_list(
        self, session, regular_user
    ) -> None:
        """Return an empty list for a resolvable service with no recorded runs."""
        response = await self._get(
            session, 1, inventory_mock(service_payload("svc-empty")), regular_user
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_missing_service_id_returns_empty_list(
        self, session, regular_user
    ) -> None:
        """Return ``[]`` when the cascade parent query param is omitted."""
        inventory = inventory_mock()
        response = await self._get(session, None, inventory, regular_user)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []
        inventory.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_unusable_rows_to_fill_choice_cap(
        self, session, regular_user
    ) -> None:
        """Keep scanning past unusable catalog rows to surface older valid backups.

        The only usable row is saved first, so it sorts last and falls beyond the
        first page of unusable rows — a single-page scan would return ``[]``.
        """
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(
                task_history_id=1,
                service_name="svc-a",
                backup_type="M",
                location="/data/mydumper/kept",
            ),
        )
        for task_history_id in range(2, DEFAULT_PAGINATION_LIMIT + 2):
            await MysqlBackupRunManager.save(
                session,
                MysqlBackupRun(
                    task_history_id=task_history_id,
                    service_name="svc-a",
                    backup_type="M",
                ),
            )

        response = await self._get(
            session, 1, inventory_mock(service_payload("svc-a")), regular_user
        )

        assert response.status_code == status.HTTP_200_OK
        assert [item["value"] for item in response.json()] == ["/data/mydumper/kept"]

    @pytest.mark.asyncio
    async def test_unknown_service_returns_empty_list(
        self, session, regular_user
    ) -> None:
        """Return ``[]`` for an unknown inventory id so free-text stays usable."""
        response = await self._get(
            session,
            999,
            inventory_mock(raises=HTTPNotFoundException(detail="nope")),
            regular_user,
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_unavailable_inventory_surfaces_as_503(
        self, session, regular_user
    ) -> None:
        """Return 503 for an unavailable inventory instead of swallowing it to ``[]``.

        Only the unknown-service 404 above is swallowed. A capacity refusal
        reaches this route as ``HTTPServiceUnavailableException`` and must stay
        distinguishable from "this service has no backups", or the selector
        silently renders an empty list during an outage.
        """
        response = await self._get(
            session,
            7,
            inventory_mock(raises=HTTPServiceUnavailableException()),
            regular_user,
        )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "detail" in response.json()

    @pytest.mark.asyncio
    async def test_sentinel_service_returns_empty_list(
        self, session, regular_user
    ) -> None:
        """Return ``[]`` for the unknown-service sentinel without hitting inventory."""
        inventory = inventory_mock()
        response = await self._get(
            session, UNKNOWN_SERVICE_SENTINEL, inventory, regular_user
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []
        inventory.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_custom_service_name_queries_catalog(
        self, session, regular_user
    ) -> None:
        """Query the catalog by name when the cascade parent is a free-typed string."""
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(
                task_history_id=1,
                service_name="custom-svc",
                backup_type="M",
                location="/custom",
            ),
        )
        inventory = inventory_mock()
        response = await self._get(session, "custom-svc", inventory, regular_user)

        assert response.status_code == status.HTTP_200_OK
        assert [item["value"] for item in response.json()] == ["/custom"]
        inventory.get.assert_not_called()

    def test_requires_authentication(self, unauthenticated_client) -> None:
        """Reject an unauthenticated caller."""
        response = unauthenticated_client.get(_URL, params={"service_id": 1})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_renamed_service_keeps_its_backups_selectable(
        self, session, regular_user
    ) -> None:
        """Keep earlier backups in the selector after the service was renamed.

        The user-visible half of the defect: a rename — in PMM Extensions or propagated from
        PMM by inventory sync — silently emptied the restore form's existing-backup
        list, so every earlier backup vanished from the picker.
        """
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(
                task_history_id=1,
                service_name="old-name",
                service_id=1,
                backup_type="M",
                location="/data/mydumper/old-name",
            ),
        )

        response = await self._get(
            session, 1, inventory_mock(service_payload("new-name")), regular_user
        )

        assert response.status_code == status.HTTP_200_OK
        assert [item["value"] for item in response.json()] == [
            "/data/mydumper/old-name"
        ]

    @pytest.mark.asyncio
    async def test_custom_service_name_lists_rows_recorded_with_an_id(
        self, session, regular_user
    ) -> None:
        """List id-carrying rows for a free-typed parent matching their name.

        A free-typed destination resolves to no inventory row, so the name is the
        only key available and every row recorded under it is a candidate — with an
        id or without. Still no Inventory call and no type check on this branch.
        """
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(
                task_history_id=1,
                service_name="custom-svc",
                service_id=1,
                backup_type="M",
                location="/custom-with-id",
            ),
        )
        inventory = inventory_mock()

        response = await self._get(session, "custom-svc", inventory, regular_user)

        assert [item["value"] for item in response.json()] == ["/custom-with-id"]
        inventory.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_unicode_digit_parent_returns_empty_list_not_an_error(
        self, session, regular_user
    ) -> None:
        """Answer ``[]`` for an ``int``-unparsable unicode digit, never a 500.

        A superscript digit passes ``str.isdigit`` but not ``int``, so a numeric
        gate on the former raises out of the dependency and breaks the very options
        fetch the free-text escape hatch is meant to keep harmless.
        """
        response = await self._get(
            session, "\N{SUPERSCRIPT TWO}", inventory_mock(), regular_user
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_runs_sharing_a_location_are_offered_once(
        self, session, regular_user
    ) -> None:
        """Offer a reused location once, labelled with its newest finished run.

        A same-day rerun republishes the dump into the day directory it already
        owns, so the earlier run's row resolves to a location that now holds the
        later run's dump. Offering both would restore data the label does not name.
        """
        shared = "/backups/mydumper/172.28.9.40/20260921"
        await MysqlBackupRunManager.save(
            session,
            _catalog_run(
                1,
                shared,
                finished_at=datetime(2026, 9, 21, 17, 44, tzinfo=UTC),
                size_bytes=100,
            ),
        )
        await MysqlBackupRunManager.save(
            session,
            _catalog_run(
                2,
                shared,
                finished_at=datetime(2026, 9, 21, 17, 46, tzinfo=UTC),
                size_bytes=200,
            ),
        )

        response = await self._get(
            session, 1, inventory_mock(service_payload("svc-a")), regular_user
        )

        body = response.json()
        assert [item["value"] for item in body] == [shared]
        newest = await self._newest_run(session)
        assert body[0]["label"] == backup_source_label(newest, value=shared)
        assert "200 B" in body[0]["label"]

    @pytest.mark.asyncio
    async def test_collapses_on_the_resolved_value_not_the_raw_column(
        self, session, regular_user
    ) -> None:
        """Collapse rows whose different columns resolve to one restore value.

        An uploaded run carries its destination and a local path; a later row may
        record the same destination as its only source. Both submit the same
        ``backup_source``, so the selector must treat them as one.
        """
        await MysqlBackupRunManager.save(
            session,
            _catalog_run(
                1,
                "s3://bucket/base",
                finished_at=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
                backup_type="X",
            ),
        )
        await MysqlBackupRunManager.save(
            session,
            _catalog_run(
                2,
                "/data/xtrabackup/base",
                finished_at=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
                upload_destination="s3://bucket/base",
                backup_type="X",
            ),
        )

        response = await self._get(
            session, 1, inventory_mock(service_payload("svc-a")), regular_user
        )

        body = response.json()
        assert [item["value"] for item in body] == ["s3://bucket/base"]
        assert "2026-07-29" in body[0]["label"]

    @pytest.mark.asyncio
    async def test_finished_duplicate_outranks_one_with_no_finish_time(
        self, session, regular_user
    ) -> None:
        """Keep the finished run's label when a duplicate reports no finish time.

        A row with no ``finished_at`` sorts last, so it never supplies the label
        for a value a finished run also resolves to.
        """
        shared = "/backups/mydumper/20260921"
        await MysqlBackupRunManager.save(
            session,
            _catalog_run(
                1, shared, finished_at=datetime(2026, 9, 21, 17, 46, tzinfo=UTC)
            ),
        )
        await MysqlBackupRunManager.save(session, _catalog_run(2, shared))

        response = await self._get(
            session, 1, inventory_mock(service_payload("svc-a")), regular_user
        )

        body = response.json()
        assert [item["value"] for item in body] == [shared]
        assert "unknown time" not in body[0]["label"]

    @pytest.mark.asyncio
    async def test_duplicates_finishing_together_resolve_deterministically(
        self, session, regular_user
    ) -> None:
        """Break a duplicate tie on the catalog's own ordering, not on chance.

        Two runs can report the same finish time; the newest-first ordering falls
        through to ``created_at`` and ``id``, so the last row recorded wins.
        """
        shared = "/backups/mydumper/20260921"
        finished = datetime(2026, 9, 21, 17, 46, tzinfo=UTC)
        for task_history_id, size_bytes in ((1, 100), (2, 200)):
            await MysqlBackupRunManager.save(
                session,
                _catalog_run(
                    task_history_id,
                    shared,
                    finished_at=finished,
                    size_bytes=size_bytes,
                ),
            )

        response = await self._get(
            session, 1, inventory_mock(service_payload("svc-a")), regular_user
        )

        body = response.json()
        assert [item["value"] for item in body] == [shared]
        assert "200 B" in body[0]["label"]

    @pytest.mark.asyncio
    async def test_late_catalogued_duplicate_does_not_supply_the_label(
        self, session, regular_user
    ) -> None:
        """Label a reused location by finish time, not by when it was recorded.

        A run catalogued after an already-recorded later run carries the higher
        ``id``, so collapsing on insertion order would hand the label to the run
        whose dump the rerun replaced.
        """
        shared = "/backups/mydumper/20260921"
        await MysqlBackupRunManager.save(
            session,
            _catalog_run(
                1,
                shared,
                finished_at=datetime(2026, 9, 21, 17, 46, tzinfo=UTC),
                size_bytes=200,
            ),
        )
        await MysqlBackupRunManager.save(
            session,
            _catalog_run(
                2,
                shared,
                finished_at=datetime(2026, 9, 21, 17, 44, tzinfo=UTC),
                size_bytes=100,
            ),
        )

        response = await self._get(
            session, 1, inventory_mock(service_payload("svc-a")), regular_user
        )

        body = response.json()
        assert [item["value"] for item in body] == [shared]
        # Size, not the rendered time, tells the two runs apart without
        # assuming how the session backend stores a timestamp's offset.
        assert "200 B" in body[0]["label"]

    @pytest.mark.asyncio
    async def test_distinct_locations_keep_their_order_around_a_collapse(
        self, session, regular_user
    ) -> None:
        """Keep distinct locations newest-first when a collapse falls between them.

        The duplicate is older than one distinct location and newer than another,
        so dropping it must not reorder the values it sits between or relabel them.
        """
        reused = "/backups/mydumper/20260921"
        middle = "/backups/mydumper/20260920"
        oldest = "/backups/mydumper/20260919"
        rows = (
            (1, reused, datetime(2026, 9, 21, 17, 46, tzinfo=UTC), 300),
            (2, middle, datetime(2026, 9, 20, 17, 0, tzinfo=UTC), 200),
            (3, reused, datetime(2026, 9, 20, 9, 0, tzinfo=UTC), 150),
            (4, oldest, datetime(2026, 9, 19, 17, 0, tzinfo=UTC), 100),
        )
        for task_history_id, location, finished_at, size_bytes in rows:
            await MysqlBackupRunManager.save(
                session,
                _catalog_run(
                    task_history_id,
                    location,
                    finished_at=finished_at,
                    size_bytes=size_bytes,
                ),
            )

        response = await self._get(
            session, 1, inventory_mock(service_payload("svc-a")), regular_user
        )

        body = response.json()
        assert [item["value"] for item in body] == [reused, middle, oldest]
        assert "300 B" in body[0]["label"]
        assert "200 B" in body[1]["label"]
        assert "100 B" in body[2]["label"]


class TestBackupSourceChoicesScan:
    """Page the catalog for distinct restore values within the scan bound.

    The catalog is stubbed rather than seeded here: it gives these cases direct
    control over the page arithmetic and over the ordering they turn on, which
    is the route tests' own subject. The scan-bound case additionally needs more
    rows than a DB-backed test would pay for one insert at a time.
    """

    @staticmethod
    def _pager(runs: list[MysqlBackupRun]) -> AsyncMock:
        """Return a ``list_for_service`` stub paging ``runs`` in catalog order.

        :param runs: The rows the catalog holds, newest first.
        :return: An ``AsyncMock`` serving offset/limit windows over ``runs``.
        """

        async def _list_for_service(
            session: AsyncSession, key: CatalogServiceKey, *, pagination: Pagination
        ) -> PaginatedResponse[MysqlBackupRun]:
            window = runs[pagination.offset : pagination.offset + pagination.limit]
            return PaginatedResponse.from_pagination(window, len(runs), pagination)

        return AsyncMock(side_effect=_list_for_service)

    async def _choices(
        self, monkeypatch: pytest.MonkeyPatch, runs: list[MysqlBackupRun]
    ) -> tuple[list[Choice], AsyncMock]:
        """Collect choices over a stubbed catalog and return them with the stub.

        :param monkeypatch: The fixture patching the catalog manager.
        :param runs: The rows the stubbed catalog holds, newest first.
        :return: The collected choices and the stub that served the pages.
        """
        pager = self._pager(runs)
        monkeypatch.setattr(MysqlBackupRunManager, "list_for_service", pager)
        choices = await choices_for_service(
            AsyncMock(spec=AsyncSession),
            CatalogServiceKey(service_name="svc-a", service_id=1),
        )
        return choices, pager

    @pytest.mark.asyncio
    async def test_duplicates_spanning_a_page_do_not_consume_the_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Collapse a value whose rows fall on both sides of a page boundary.

        Counting collapsed rows against the cap, or tracking offered values per
        page instead of per scan, would hide older backups behind the location a
        rerun reused.
        """
        reused = "/backups/mydumper/20260921"
        runs = [
            _catalog_run(
                index,
                reused,
                finished_at=datetime(2026, 9, 21, 12, 59 - index, tzinfo=UTC),
            )
            for index in range(DEFAULT_PAGINATION_LIMIT - 1)
        ]
        runs.append(_catalog_run(90, "/backups/mydumper/20260920"))
        runs.append(_catalog_run(91, reused))
        runs.append(_catalog_run(92, "/backups/mydumper/20260919"))

        choices, _ = await self._choices(monkeypatch, runs)

        # The third value is reachable only on page 2, so its presence is what
        # proves the scan carried the offered values across the page fetch.
        assert [choice.value for choice in choices] == [
            reused,
            "/backups/mydumper/20260920",
            "/backups/mydumper/20260919",
        ]
        assert "12:59" in choices[0].label

    @pytest.mark.asyncio
    async def test_cap_counts_distinct_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stop at the cap once that many distinct values are collected."""
        runs = [
            _catalog_run(index, f"/backups/mydumper/{index}")
            for index in range(DEFAULT_PAGINATION_LIMIT + 10)
        ]

        choices, pager = await self._choices(monkeypatch, runs)

        assert len(choices) == DEFAULT_PAGINATION_LIMIT
        assert len({choice.value for choice in choices}) == DEFAULT_PAGINATION_LIMIT
        assert pager.await_count == 1

    @pytest.mark.asyncio
    async def test_scan_bound_still_caps_database_work(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Give up after the scan bound rather than paging on for distinct values."""
        runs = [
            _catalog_run(index, "/backups/mydumper/20260921")
            for index in range(DEFAULT_PAGINATION_LIMIT * (_MAX_CHOICE_SCAN_PAGES + 2))
        ]

        choices, pager = await self._choices(monkeypatch, runs)

        assert [choice.value for choice in choices] == ["/backups/mydumper/20260921"]
        assert pager.await_count == _MAX_CHOICE_SCAN_PAGES

    @pytest.mark.asyncio
    async def test_duplicate_and_unusable_rows_are_both_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reach an older distinct value past a page of duplicates and unusable rows."""
        runs = [
            _catalog_run(index, "/backups/mydumper/20260921" if index % 2 else None)
            for index in range(DEFAULT_PAGINATION_LIMIT)
        ]
        runs.append(_catalog_run(99, "/backups/mydumper/20260920"))

        choices, _ = await self._choices(monkeypatch, runs)

        assert [choice.value for choice in choices] == [
            "/backups/mydumper/20260921",
            "/backups/mydumper/20260920",
        ]
