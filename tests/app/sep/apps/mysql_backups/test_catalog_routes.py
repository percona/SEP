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

"""Tests for the per-service backup catalog query route."""

from unittest.mock import AsyncMock

import pytest
from fastapi import status
from httpx import Response
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import HTTPNotFoundException
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.mysql_backups.crud import MysqlBackupRunManager
from app.sep.apps.mysql_backups.models import MysqlBackupRun
from tests.app.sep.apps.mysql_backups.conftest import (
    authenticated_get,
    inventory_mock,
    service_payload,
)

_URL = "/api/apps/mysql_backups/services/{service_id}/backups"


class TestServiceBackupsRoute:
    """GET /api/apps/mysql_backups/services/{service_id}/backups."""

    async def _get(
        self,
        session: AsyncSession,
        service_id: int,
        inventory: AsyncMock,
        regular_user: object,
    ) -> Response:
        """Drive the route with the given session + inventory mock, authenticated."""
        return await authenticated_get(
            _URL.format(service_id=service_id),
            session=session,
            inventory=inventory,
            user=regular_user,
        )

    @pytest.mark.asyncio
    async def test_returns_records_newest_first(self, session, regular_user) -> None:
        """Return a service's records newest first."""
        for i in range(3):
            await MysqlBackupRunManager.save(
                session,
                MysqlBackupRun(
                    task_history_id=i + 1,
                    service_name="svc-a",
                    backup_type="X",
                    location=f"/data/xtrabackup/svc-a/{i}",
                    size_bytes=i,
                ),
            )

        response = await self._get(
            session, 1, inventory_mock(service_payload("svc-a")), regular_user
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == 3  # noqa: PLR2004
        assert [r["location"] for r in body["items"]] == [
            "/data/xtrabackup/svc-a/2",
            "/data/xtrabackup/svc-a/1",
            "/data/xtrabackup/svc-a/0",
        ]
        assert body["items"][0]["backup_type"] == "X"

    @pytest.mark.asyncio
    async def test_excludes_other_services(self, session, regular_user) -> None:
        """Return only the requested service's records."""
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(task_history_id=1, service_name="svc-a", backup_type="M"),
        )
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(task_history_id=2, service_name="svc-b", backup_type="M"),
        )

        response = await self._get(
            session, 1, inventory_mock(service_payload("svc-a")), regular_user
        )

        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["service_name"] == "svc-a"

    @pytest.mark.asyncio
    async def test_existing_service_no_records_returns_empty(
        self, session, regular_user
    ) -> None:
        """Return an empty page for a resolvable service with no recorded runs."""
        response = await self._get(
            session, 1, inventory_mock(service_payload("svc-empty")), regular_user
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == 0
        assert body["items"] == []

    @pytest.mark.asyncio
    async def test_unknown_service_propagates_404(self, session, regular_user) -> None:
        """Surface an unknown service id as ``404`` — a real error, not an empty page.

        Only a *resolvable* service with no recorded runs yields an empty page;
        conflating the two would hide a bad service id from the caller.
        """
        response = await self._get(
            session,
            999,
            inventory_mock(raises=HTTPNotFoundException(detail="nope")),
            regular_user,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_non_mysql_service_returns_404(self, session, regular_user) -> None:
        """Surface a resolvable non-MySQL service as ``404``, not an empty page.

        The catalog query filters on ``service_name`` alone, so serving a
        wrong-type service would let a same-named non-MySQL service leak
        another service's rows.
        """
        response = await self._get(
            session,
            1,
            inventory_mock(
                service_payload("svc-a", service_type=ServiceTypeEnum.POSTGRESQL)
            ),
            regular_user,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_requires_authentication(self, unauthenticated_client) -> None:
        """Reject an unauthenticated caller."""
        response = unauthenticated_client.get(_URL.format(service_id=1))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_renamed_service_still_returns_its_backups(
        self, session, regular_user
    ) -> None:
        """Keep a recorded run reachable after its service was renamed.

        The row was written when the service was called ``old-name``; inventory
        now resolves the same id to ``new-name``. Keying on the name alone lost the
        row and answered with the same empty page a service with no backups gives.
        """
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(
                task_history_id=1,
                service_name="old-name",
                service_id=1,
                backup_type="M",
                location="/data/mydumper/old-name/0",
            ),
        )

        response = await self._get(
            session, 1, inventory_mock(service_payload("new-name")), regular_user
        )

        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["location"] == "/data/mydumper/old-name/0"
        assert body["items"][0]["service_id"] == 1

    @pytest.mark.asyncio
    async def test_row_without_service_id_still_returned_by_name(
        self, session, regular_user
    ) -> None:
        """Serve a row predating the id through the name it was written with."""
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(task_history_id=1, service_name="svc-a", backup_type="M"),
        )

        response = await self._get(
            session, 1, inventory_mock(service_payload("svc-a")), regular_user
        )

        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["service_id"] is None

    @pytest.mark.asyncio
    async def test_same_named_services_do_not_leak_each_others_runs(
        self, session, regular_user
    ) -> None:
        """Isolate two MySQL services that share a name once ids are recorded.

        ``Service.name`` carries no uniqueness constraint, so keying on the name
        returned both services' runs under either id.
        """
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(
                task_history_id=1,
                service_name="shared",
                service_id=1,
                backup_type="M",
            ),
        )
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(
                task_history_id=2,
                service_name="shared",
                service_id=2,
                backup_type="M",
            ),
        )

        response = await self._get(
            session, 1, inventory_mock(service_payload("shared")), regular_user
        )

        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["service_id"] == 1
