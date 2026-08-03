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
from httpx import ASGITransport, AsyncClient, Response
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import HTTPNotFoundException
from app.core.requests import RemoteAPI
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.mysql_backups.backup_source_choices import (
    backup_run_to_choice,
    backup_source_label,
    backup_source_value,
)
from app.sep.apps.mysql_backups.crud import MysqlBackupRunManager
from app.sep.apps.mysql_backups.models import MysqlBackupRun
from app.sep.deps import (
    get_api_authenticated_user,
    get_current_user,
    get_inventory_api,
    get_session,
    require_bearer_for_unsafe_methods,
)
from app.sep.main import sep_app

_URL = "/api/apps/mysql_backups/backup-sources/choices"


def _service(
    name: str,
    service_id: int = 1,
    service_type: ServiceTypeEnum = ServiceTypeEnum.MYSQL,
) -> dict:
    """Build a minimal inventory service payload the route can resolve."""
    return {
        "id": service_id,
        "name": name,
        "type": service_type.value,
        "node_id": 1,
    }


def _inventory(
    returns: dict | None = None, *, raises: Exception | None = None
) -> AsyncMock:
    """Build a mock InventoryAPI whose ``get`` returns or raises."""
    mock = AsyncMock(spec=RemoteAPI)
    if raises is not None:
        mock.get.side_effect = raises
    else:
        mock.get.return_value = returns
    return mock


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

    def test_value_ignores_blank_upload_destination(self) -> None:
        """Treat a blank upload destination as unset and fall back to location."""
        run = MysqlBackupRun(
            task_history_id=1,
            service_name="svc",
            backup_type="X",
            location="/data/xtrabackup/inc",
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
        assert choice.label == backup_source_label(run)
        assert "Mydumper" in choice.label
        assert "2026-07-29" in choice.label
        assert "1.0 GiB" in choice.label or "1 GiB" in choice.label


class TestBackupSourceChoicesRoute:
    """GET /api/apps/mysql_backups/backup-sources/choices?service_id=..."""

    async def _get(
        self,
        session: AsyncSession,
        service_id: int,
        inventory: AsyncMock,
        regular_user: object,
    ) -> Response:
        """Drive the route with the given session + inventory mock, authenticated."""
        sep_app.dependency_overrides[get_session] = lambda: session
        sep_app.dependency_overrides[get_current_user] = lambda: regular_user
        sep_app.dependency_overrides[get_api_authenticated_user] = lambda: regular_user
        sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
        sep_app.dependency_overrides[get_inventory_api] = lambda: inventory
        try:
            transport = ASGITransport(app=sep_app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                return await client.get(_URL, params={"service_id": service_id})
        finally:
            sep_app.dependency_overrides = {}

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
            session, 1, _inventory(_service("svc-a")), regular_user
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert [item["value"] for item in body] == [
            "s3://bucket/base",
            "/data/mydumper/old",
        ]
        assert body[0]["label"]
        assert "XtraBackup" in body[0]["label"]

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
            session, 1, _inventory(_service("svc-a")), regular_user
        )

        assert [item["value"] for item in response.json()] == ["/a"]

    @pytest.mark.asyncio
    async def test_empty_catalog_returns_empty_list(
        self, session, regular_user
    ) -> None:
        """Return an empty list for a resolvable service with no recorded runs."""
        response = await self._get(
            session, 1, _inventory(_service("svc-empty")), regular_user
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_unknown_service_propagates_404(self, session, regular_user) -> None:
        """Surface an unknown service id as ``404``."""
        response = await self._get(
            session,
            999,
            _inventory(raises=HTTPNotFoundException(detail="nope")),
            regular_user,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_requires_authentication(self, unauthenticated_client) -> None:
        """Reject an unauthenticated caller."""
        response = unauthenticated_client.get(_URL, params={"service_id": 1})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
