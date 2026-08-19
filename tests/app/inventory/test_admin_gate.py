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

"""Define tests for the unsafe-method admin gate on the Inventory sub-app."""

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pytest_mock import MockerFixture
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.settings_override.models import SettingClassEnum
from app.inventory.deps import get_session
from app.inventory.main import inventory_app
from app.inventory.models import Node, Service

BEARER_HEADERS = {"Authorization": "Bearer valid_token"}
SERVICE_TOKEN = "supersecret"


@pytest.fixture
def bearer_client(session: AsyncSession, casdoor_mock) -> TestClient:
    """Yield an Inventory TestClient that authenticates by Bearer token.

    No authentication dependency is overridden: the gate resolves the user
    imperatively, so an override could not reach it, and leaving the chain real
    is what makes the gate the thing under test.
    """
    inventory_app.dependency_overrides[get_session] = lambda: session
    yield TestClient(inventory_app, raise_server_exceptions=False)
    inventory_app.dependency_overrides = {}


@pytest.fixture
def admin_bearer_client(
    bearer_client: TestClient, casdoor_user_data, mocker: MockerFixture
) -> TestClient:
    """Yield the Bearer client whose credential resolves to an admin."""
    mocker.patch(
        "app.core.auth.providers.casdoor.sdk.CasdoorSDK.get_user",
        new=mocker.AsyncMock(return_value={**casdoor_user_data, "is_admin": True}),
    )
    return bearer_client


MUTATIONS = [
    ("POST", "/nodes/"),
    ("PUT", "/services/1"),
    ("POST", "/schemas/1/tables/"),
    ("DELETE", "/tables/1"),
]
MUTATION_IDS = ["nodes", "services", "schemas", "tables"]


@pytest.mark.parametrize(("method", "path"), MUTATIONS, ids=MUTATION_IDS)
def test_mutations_are_refused_for_a_non_admin(
    bearer_client: TestClient, method: str, path: str
) -> None:
    """Refuse a non-admin's mutation on each of the four route modules.

    The four routers are separate ``APIRouter`` instances that declare nothing
    about the gate — they inherit it through ``create_app``'s include loop, so
    each is covered separately.
    """
    response = bearer_client.request(method, path, json={}, headers=BEARER_HEADERS)

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.parametrize(("method", "path"), MUTATIONS, ids=MUTATION_IDS)
def test_mutations_pass_the_gate_for_an_admin(
    admin_bearer_client: TestClient, method: str, path: str
) -> None:
    """Admit an admin's mutation on each router, leaving the route to answer."""
    response = admin_bearer_client.request(
        method, path, json={}, headers=BEARER_HEADERS
    )

    assert response.status_code != status.HTTP_403_FORBIDDEN


def test_reads_are_unaffected_for_a_non_admin(bearer_client: TestClient) -> None:
    """Serve a non-admin's list request unchanged — the gate is method-scoped."""
    response = bearer_client.get("/nodes/", headers=BEARER_HEADERS)

    assert response.status_code == status.HTTP_200_OK


def test_the_service_principal_is_still_refused_by_a_route_admin_check(
    bearer_client: TestClient, mocker: MockerFixture
) -> None:
    """Refuse the principal on a route carrying its own ``IsAdminDep``."""
    mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", SecretStr(SERVICE_TOKEN))

    response = bearer_client.patch(
        f"/admin/settings/{SettingClassEnum.INVENTORY_SETTINGS.value}",
        json={"overrides": {}},
        headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_the_service_principal_can_still_update_a_node(
    bearer_client: TestClient, node: Node, mocker: MockerFixture
) -> None:
    """Update a node as the principal, which the scheduled sync depends on.

    The concrete 200 and the written field are the assertion — "not 403" would
    also pass on a 401 or a 500, which is exactly the silent breakage this gate
    risks for the scheduled writer.
    """
    mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", SecretStr(SERVICE_TOKEN))

    response = bearer_client.put(
        f"/nodes/{node.id}",
        json={"name": "renamed-by-sync", "address": node.address},
        headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["name"] == "renamed-by-sync"


def test_the_service_principal_can_still_delete_a_service(
    bearer_client: TestClient, service: Service, mocker: MockerFixture
) -> None:
    """Delete a service as the principal, which the scheduled sync depends on."""
    mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", SecretStr(SERVICE_TOKEN))

    response = bearer_client.delete(
        f"/services/{service.id}",
        headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
    )

    assert response.status_code == status.HTTP_204_NO_CONTENT
