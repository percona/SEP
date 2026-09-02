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

"""Test ``POST /hosts/{node_id}/bootstrap`` -- the PMM-15347 PoC route.

Mocks the Tasks API rather than dispatching a real Nomad job: what this route owns
is building the config and returning the right response/errors, not whether Nomad
itself accepts a dispatch (that is ``payload/bootstrap.py``'s job, exercised by
running it, not by a unit test -- see its module docstring).
"""

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import status
from httpx import ASGITransport, AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import require_minimum_role_for_unsafe_methods
from app.core.auth.providers.casdoor.models import CasdoorUser
from app.sep.apps.om_inventory.crud import upsert_host
from app.sep.deps import (
    get_current_user,
    get_session,
    require_bearer_for_unsafe_methods,
)
from app.sep.main import sep_app

BASE = "/api/apps/om_inventory"
NODE_USABLE = "id-app-prod-01"
NODE_UNUSABLE = "id-app-prod-02"
FAKE_TASK_HISTORY_ID = 4242

BOOTSTRAP_BODY = {
    "replica_set_name": "rs-orders-prod",
    "mongodb_version": "7.0.8",
}


@pytest_asyncio.fixture
async def api(regular_user: CasdoorUser, session: AsyncSession) -> AsyncClient:
    """Yield an authenticated client sharing the test session.

    Same shape as ``test_estate_api.py``'s ``api`` fixture: the role gate is
    disabled here too, because that gate is exercised by a central test of every
    route's registered minimum rank, not per app.

    :param regular_user: The authenticated user.
    :param session: The database session the routes should use.
    :return: The client.
    """
    sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
    sep_app.dependency_overrides[require_minimum_role_for_unsafe_methods] = lambda: None
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user
    sep_app.dependency_overrides[get_session] = lambda: session
    client = AsyncClient(
        transport=ASGITransport(app=sep_app),
        base_url="http://test",
        headers={"Authorization": "Bearer test"},
    )
    try:
        yield client
    finally:
        await client.aclose()
        sep_app.dependency_overrides = {}


@pytest_asyncio.fixture
async def estate(session: AsyncSession) -> AsyncSession:
    """Populate one host with a usable executor and one without.

    :param session: The database session.
    :return: The same session, with rows.
    """
    await upsert_host(
        session,
        node_id=NODE_USABLE,
        name="app-prod-01",
        address="10.0.0.11",
        executor_host="app-prod-01",
        observed={"executor": {"registered": True, "reachable": True, "driver_healthy": True}},
    )
    await upsert_host(
        session,
        node_id=NODE_UNUSABLE,
        name="app-prod-02",
        address="10.0.0.12",
        executor_host="app-prod-02",
        observed={"executor": {"registered": True, "reachable": False, "driver_healthy": False}},
    )
    await session.commit()
    return session


class FakeTasksApi:
    """Stand in for the Tasks API client: one dispatch call, one canned reply."""

    def __init__(self, *, task_history_id: int = FAKE_TASK_HISTORY_ID) -> None:
        self.task_history_id = task_history_id
        self.calls: list[dict] = []

    async def post(self, path: str, *, json: dict) -> dict:
        """Record the dispatch call and answer with the canned task history id."""
        self.calls.append({"path": path, "json": json})
        return {"id": self.task_history_id}


class TestBootstrapHost:
    """Assert ``POST /hosts/{node_id}/bootstrap``."""

    @pytest.mark.asyncio
    async def test_dispatches_to_a_usable_host_and_returns_credentials(
        self, api: AsyncClient, estate: AsyncSession
    ) -> None:
        """The happy path: a usable host gets a dispatched run and fresh credentials.

        :param api: The authenticated client.
        :param estate: The seeded hosts.
        """
        fake = FakeTasksApi()
        with patch(
            "app.core.config.Settings.get_remote_api",
            new=AsyncMock(return_value=fake),
        ):
            response = await api.post(f"{BASE}/hosts/{NODE_USABLE}/bootstrap", json=BOOTSTRAP_BODY)

        assert response.status_code == status.HTTP_202_ACCEPTED
        body = response.json()
        assert body["node_id"] == NODE_USABLE
        assert body["task_history_id"] == FAKE_TASK_HISTORY_ID
        assert body["admin_username"] == "admin"
        assert body["admin_password"]  # generated, non-empty

        assert len(fake.calls) == 1
        call = fake.calls[0]
        assert call["path"] == "/execute/run-python"
        assert call["json"]["meta"]["target"] == "app-prod-01"
        assert call["json"]["payload"].endswith("payload/bootstrap.py")

    @pytest.mark.asyncio
    async def test_unknown_host_is_404(self, api: AsyncClient, estate: AsyncSession) -> None:
        """A node id OM holds no row for is answered by name, not a Nomad dispatch.

        :param api: The authenticated client.
        :param estate: The seeded hosts.
        """
        response = await api.post(f"{BASE}/hosts/does-not-exist/bootstrap", json=BOOTSTRAP_BODY)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_a_host_with_no_usable_executor_is_rejected(
        self, api: AsyncClient, estate: AsyncSession
    ) -> None:
        """A host that fails the same check ``?executor=true`` filters on is refused.

        :param api: The authenticated client.
        :param estate: The seeded hosts.
        """
        fake = FakeTasksApi()
        with patch(
            "app.core.config.Settings.get_remote_api",
            new=AsyncMock(return_value=fake),
        ):
            response = await api.post(
                f"{BASE}/hosts/{NODE_UNUSABLE}/bootstrap", json=BOOTSTRAP_BODY
            )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert not fake.calls  # never dispatched

    @pytest.mark.asyncio
    async def test_missing_replica_set_name_is_rejected(
        self, api: AsyncClient, estate: AsyncSession
    ) -> None:
        """Pydantic validation, not the handler, rejects an incomplete request.

        :param api: The authenticated client.
        :param estate: The seeded hosts.
        """
        response = await api.post(
            f"{BASE}/hosts/{NODE_USABLE}/bootstrap", json={"mongodb_version": "7.0.8"}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
