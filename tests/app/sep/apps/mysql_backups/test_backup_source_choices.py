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

from app.core.exceptions import HTTPNotFoundException
from app.core.pagination import DEFAULT_PAGINATION_LIMIT
from app.sep.apps.mysql_backups.backup_source_choices import (
    backup_run_to_choice,
    backup_source_value,
)
from app.sep.apps.mysql_backups.crud import MysqlBackupRunManager
from app.sep.apps.mysql_backups.models import MysqlBackupRun, UNKNOWN_SERVICE_SENTINEL
from tests.app.sep.apps.mysql_backups.conftest import (
    authenticated_get,
    inventory_mock,
    service_payload,
)

_URL = "/api/apps/mysql_backups/backup-sources/choices"


class TestBackupSourceMapper:
    """Map catalog rows onto restore-valid ``Choice`` options."""

    def test_value_prefers_upload_destination(self) -> None:
        """Prefer the upload destination when one was configured."""
        run = MysqlBackupRun(
            task_history_id=1,
            service_name="svc",
            backup_type="X",
            location="/backups/x/base",
            upload_destination="s3://bucket/base",
        )
        assert backup_source_value(run) == "s3://bucket/base"

    def test_value_falls_back_to_location(self) -> None:
        """Fall back to the on-disk location when no upload destination exists."""
        run = MysqlBackupRun(
            task_history_id=1,
            service_name="svc",
            backup_type="M",
            location="/backups/mydumper/20240101",
        )
        assert backup_source_value(run) == "/backups/mydumper/20240101"

    def test_value_none_when_both_missing(self) -> None:
        """Return ``None`` when neither location nor upload destination is set."""
        run = MysqlBackupRun(
            task_history_id=1,
            service_name="svc",
            backup_type="M",
        )
        assert backup_source_value(run) is None

    def test_value_strips_and_ignores_blank_upload_destination(self) -> None:
        """Strip whitespace and treat a blank upload destination as unset."""
        run = MysqlBackupRun(
            task_history_id=1,
            service_name="svc",
            backup_type="X",
            location=" /data/xtrabackup/inc ",
            upload_destination="  ",
        )
        assert backup_source_value(run) == "/data/xtrabackup/inc"

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

        The user-visible half of the defect: a rename — in SEP or propagated from
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
