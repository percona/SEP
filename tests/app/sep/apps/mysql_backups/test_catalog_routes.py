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
from httpx import ASGITransport, AsyncClient, Response
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import HTTPNotFoundException
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.mysql_backups.catalog_models import MysqlBackupRun
from app.sep.apps.mysql_backups.crud import MysqlBackupRunManager
from app.sep.deps import (
    get_api_authenticated_user,
    get_current_user,
    get_inventory_api,
    get_session,
    require_bearer_for_unsafe_methods,
)
from app.sep.main import sep_app

_URL = "/api/apps/mysql_backups/services/{service_id}/backups"


def _service(name: str, service_id: int = 1) -> dict:
    """Build a minimal inventory service payload the route can resolve."""
    return {
        "id": service_id,
        "name": name,
        "type": ServiceTypeEnum.MYSQL.value,
        "node_id": 1,
    }


def _inventory(
    returns: dict | None = None, *, raises: Exception | None = None
) -> AsyncMock:
    """Build a mock InventoryAPI whose ``get`` returns or raises."""
    mock = AsyncMock()
    if raises is not None:
        mock.get.side_effect = raises
    else:
        mock.get.return_value = returns
    return mock


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
                return await client.get(_URL.format(service_id=service_id))
        finally:
            sep_app.dependency_overrides = {}

    @pytest.mark.asyncio
    async def test_returns_records_newest_first(self, session, regular_user) -> None:
        """The route returns a service's records newest first."""
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
            session, 1, _inventory(_service("svc-a")), regular_user
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert [r["location"] for r in body] == [
            "/data/xtrabackup/svc-a/2",
            "/data/xtrabackup/svc-a/1",
            "/data/xtrabackup/svc-a/0",
        ]
        assert body[0]["backup_type"] == "X"

    @pytest.mark.asyncio
    async def test_excludes_other_services(self, session, regular_user) -> None:
        """The route returns only the requested service's records."""
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(task_history_id=1, service_name="svc-a", backup_type="M"),
        )
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(task_history_id=2, service_name="svc-b", backup_type="M"),
        )

        response = await self._get(
            session, 1, _inventory(_service("svc-a")), regular_user
        )

        body = response.json()
        assert len(body) == 1
        assert body[0]["service_name"] == "svc-a"

    @pytest.mark.asyncio
    async def test_existing_service_no_records_returns_empty(
        self, session, regular_user
    ) -> None:
        """A resolvable service with no recorded runs returns an empty list."""
        response = await self._get(
            session, 1, _inventory(_service("svc-empty")), regular_user
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_unknown_service_propagates_404(self, session, regular_user) -> None:
        """An unknown service id is a real error, surfaced as ``404`` — not ``[]``.

        Only a *resolvable* service with no recorded runs yields an empty list;
        conflating the two would hide a bad service id from the caller.
        """
        response = await self._get(
            session,
            999,
            _inventory(raises=HTTPNotFoundException(detail="nope")),
            regular_user,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_requires_authentication(self, unauthenticated_client) -> None:
        """The route rejects an unauthenticated caller."""
        response = unauthenticated_client.get(_URL.format(service_id=1))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
