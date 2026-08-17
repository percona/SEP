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

"""Test the estate the API serves: hosts, their services, and forgetting a row.

Two contracts here are load-bearing and neither is obvious from the handler code.

``GET /hosts?has_service=false`` is the question the host table exists to answer --
which machines carry a PMM client and no database -- so it is asserted rather than
assumed, and asserted as a *filter* on the ordinary list rather than a second
endpoint.

``DELETE`` exists because stale rows are real: restarting a node's pmm-agent runs
``setup --force``, which replaces the node in PMM and mints a new id, so POM gains a
row and keeps the old one. It is emphatically not suppression -- an entity PMM still
knows about returns on the next sweep -- and the tests say so, because a reader who
mistakes it for suppression will use it that way exactly once.
"""

import pytest
import pytest_asyncio
from fastapi import status
from httpx import ASGITransport, AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth.providers.casdoor.models import CasdoorUser
from app.sep.apps.pom_discovery.crud import upsert_host, upsert_service
from app.sep.deps import (
    get_api_authenticated_user,
    get_current_user,
    get_session,
    require_bearer_for_unsafe_methods,
    validate_csrf,
)
from app.sep.main import sep_app

BASE = "/api/apps/pom_discovery"
NODE_WITH_DB = "id-db00"
NODE_EMPTY = "id-pmm-client-node00"
SERVICE_ID = "svc-db00"


@pytest_asyncio.fixture
async def api(regular_user: CasdoorUser, session: AsyncSession) -> AsyncClient:
    """Yield an authenticated client sharing the test session.

    Async rather than a sync ``TestClient`` so a test can await a database read after
    the request -- asserting the cascade on delete needs the request and the check to
    run on one event loop and one session.

    :param regular_user: The authenticated user.
    :param session: The database session the routes should use.
    :return: The client.
    """
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user
    sep_app.dependency_overrides[get_api_authenticated_user] = lambda: regular_user
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
    """Populate the two-host estate every test here reads.

    One host runs a registered database; the other is a PMM client with nothing on it,
    which is the case the whole table exists for.

    :param session: The database session.
    :return: The same session, with rows.
    """
    await upsert_host(
        session,
        node_id=NODE_WITH_DB,
        name="db00",
        address="10.0.0.1",
        executor_host="db00",
        observed={"collected_at": "2026-08-17T09:00:00+00:00", "os": "Ubuntu 24.04"},
    )
    await upsert_host(
        session,
        node_id=NODE_EMPTY,
        name="pmm-client-node00",
        address="10.0.0.2",
        executor_host="pmm-client-node00",
        observed={"collected_at": "2026-08-17T09:00:00+00:00", "os": "Ubuntu 24.04"},
    )
    await session.flush()
    await upsert_service(
        session,
        service_id=SERVICE_ID,
        node_id=NODE_WITH_DB,
        name="db00",
        port=27017,
        role="mongod",
        observed={"installed_version": "7.0.39-21"},
    )
    await session.commit()
    return session


class TestHosts:
    """Assert the host listing and its filters."""

    @pytest.mark.asyncio
    async def test_lists_every_host_with_its_services_nested(
        self, api: AsyncClient, estate: AsyncSession
    ) -> None:
        """A host carries its services, so a consumer needs one request.

        :param api: The authenticated client.
        :param estate: The populated session.
        """
        response = await api.get(f"{BASE}/hosts")

        assert response.status_code == status.HTTP_200_OK
        hosts = {host["node_id"]: host for host in response.json()}
        assert set(hosts) == {NODE_WITH_DB, NODE_EMPTY}
        assert [s["service_id"] for s in hosts[NODE_WITH_DB]["services"]] == [
            SERVICE_ID
        ]
        assert hosts[NODE_EMPTY]["services"] == []

    @pytest.mark.asyncio
    async def test_has_service_false_finds_the_hosts_with_no_database(
        self, api: AsyncClient, estate: AsyncSession
    ) -> None:
        """The question the host table exists to answer.

        :param api: The authenticated client.
        :param estate: The populated session.
        """
        response = await api.get(f"{BASE}/hosts", params={"has_service": "false"})

        assert [host["node_id"] for host in response.json()] == [NODE_EMPTY]

    @pytest.mark.asyncio
    async def test_has_service_true_is_the_ordinary_estate_view(
        self, api: AsyncClient, estate: AsyncSession
    ) -> None:
        """The same list, inverted -- which is why it is a filter, not an endpoint.

        :param api: The authenticated client.
        :param estate: The populated session.
        """
        response = await api.get(f"{BASE}/hosts", params={"has_service": "true"})

        assert [host["node_id"] for host in response.json()] == [NODE_WITH_DB]

    @pytest.mark.asyncio
    async def test_one_host_by_pmms_node_id(
        self, api: AsyncClient, estate: AsyncSession
    ) -> None:
        """The path is the id every consumer already holds.

        :param api: The authenticated client.
        :param estate: The populated session.
        """
        response = await api.get(f"{BASE}/hosts/{NODE_WITH_DB}")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "db00"

    @pytest.mark.asyncio
    async def test_unknown_host_is_404(
        self, api: AsyncClient, estate: AsyncSession
    ) -> None:
        """An id POM does not hold is not an empty host.

        :param api: The authenticated client.
        :param estate: The populated session.
        """
        response = await api.get(f"{BASE}/hosts/nope")

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestServices:
    """Assert the flat service listing."""

    @pytest.mark.asyncio
    async def test_lists_services_without_walking_hosts(
        self, api: AsyncClient, estate: AsyncSession
    ) -> None:
        """For a consumer that works in services rather than hosts.

        :param api: The authenticated client.
        :param estate: The populated session.
        """
        response = await api.get(f"{BASE}/services")

        assert [s["service_id"] for s in response.json()] == [SERVICE_ID]

    @pytest.mark.asyncio
    async def test_filters_by_host(
        self, api: AsyncClient, estate: AsyncSession
    ) -> None:
        """``?node_id=`` is why there is no ``/hosts/{id}/services`` collection.

        :param api: The authenticated client.
        :param estate: The populated session.
        """
        response = await api.get(f"{BASE}/services", params={"node_id": NODE_EMPTY})

        assert response.json() == []

    @pytest.mark.asyncio
    async def test_one_service_by_pmms_service_id(
        self, api: AsyncClient, estate: AsyncSession
    ) -> None:
        """Keying on PMM's id is what keeps the path free of a lookup step.

        :param api: The authenticated client.
        :param estate: The populated session.
        """
        response = await api.get(f"{BASE}/services/{SERVICE_ID}")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["observed"]["installed_version"] == "7.0.39-21"


class TestDelete:
    """Assert forgetting a row, and what forgetting does not mean."""

    @pytest.mark.asyncio
    async def test_deleting_a_host_takes_its_services_with_it(
        self, api: AsyncClient, estate: AsyncSession
    ) -> None:
        """The cascade is the database's, so no service can outlive its host.

        :param api: The authenticated client.
        :param estate: The populated session.
        """
        response = await api.delete(f"{BASE}/hosts/{NODE_WITH_DB}")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        gone = await api.get(f"{BASE}/hosts/{NODE_WITH_DB}")
        assert gone.status_code == status.HTTP_404_NOT_FOUND
        remaining = await api.get(f"{BASE}/services")
        assert remaining.json() == []

    @pytest.mark.asyncio
    async def test_deleting_a_service_leaves_its_host(
        self, api: AsyncClient, estate: AsyncSession
    ) -> None:
        """A stale service is not a reason to forget the machine it ran on.

        :param api: The authenticated client.
        :param estate: The populated session.
        """
        response = await api.delete(f"{BASE}/services/{SERVICE_ID}")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        host = await api.get(f"{BASE}/hosts/{NODE_WITH_DB}")
        assert host.status_code == status.HTTP_200_OK
        assert host.json()["services"] == []

    @pytest.mark.asyncio
    async def test_deleting_something_absent_is_404(
        self, api: AsyncClient, estate: AsyncSession
    ) -> None:
        """Silence would let a typo read as a successful cleanup.

        :param api: The authenticated client.
        :param estate: The populated session.
        """
        host = await api.delete(f"{BASE}/hosts/nope")
        service = await api.delete(f"{BASE}/services/nope")

        assert host.status_code == status.HTTP_404_NOT_FOUND
        assert service.status_code == status.HTTP_404_NOT_FOUND
