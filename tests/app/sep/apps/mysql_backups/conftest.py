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

"""Define test fixtures and shared helpers for mysql_backups plugin tests."""

import ast
import pathlib
from typing import Any, get_args
from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient, Response
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import require_admin_for_unsafe_methods
from app.core.requests import RemoteAPI
from app.inventory.models import ServiceTypeEnum
from app.sep.deps import (
    get_current_user,
    get_inventory_api,
    get_session,
    require_bearer_for_unsafe_methods,
)
from app.sep.main import sep_app
from tests.app.sep.conftest import (  # noqa: F401
    mock_inventory_api_dep,
    mock_task_api_dep,
    unauthenticated_client,
)

XTRABACKUP_PAYLOAD_PATH = (
    pathlib.Path(__file__).parents[5] / "app/sep/apps/mysql_backups/xtrabackup_payload"
)

# Spelled out on purpose: this is the cadence vocabulary the product promises, so a
# test that read it back off a model or the payload would assert a surface against
# itself. ``literal_members`` answers the separate question of whether two surfaces
# agree with each other.
XTRABACKUP_INCREMENTAL_CYCLES = (
    "daily",
    "weekly",
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
)


def xtrabackup_payload_tree() -> ast.Module:
    """Parse and return the xtrabackup payload's AST, fresh on every call.

    Centralizes the payload-path lookup so the per-file AST-extraction helpers
    in this directory's test modules do not each re-derive it independently.
    """
    return ast.parse(XTRABACKUP_PAYLOAD_PATH.read_text())


def service_payload(
    name: str,
    service_id: int = 1,
    service_type: ServiceTypeEnum = ServiceTypeEnum.MYSQL,
) -> dict:
    """Build a minimal inventory service payload a service-resolving route accepts."""
    return {
        "id": service_id,
        "name": name,
        "type": service_type.value,
        "node_id": 1,
    }


def inventory_mock(
    returns: dict | None = None, *, raises: Exception | None = None
) -> AsyncMock:
    """Build a mock InventoryAPI whose ``get`` returns or raises."""
    mock = AsyncMock(spec=RemoteAPI)
    if raises is not None:
        mock.get.side_effect = raises
    else:
        mock.get.return_value = returns
    return mock


async def authenticated_get(
    url: str,
    *,
    session: AsyncSession,
    inventory: AsyncMock,
    user: object,
    params: dict[str, Any] | None = None,
) -> Response:
    """GET ``url`` against the sep app with the given session + inventory mock.

    Installs the authentication overrides an ``/api/apps/*`` route needs, so a
    route test asserts on the route's own behavior rather than on the auth gate,
    and restores any previously installed overrides afterwards.
    """
    previous_overrides = sep_app.dependency_overrides.copy()
    sep_app.dependency_overrides[get_session] = lambda: session
    sep_app.dependency_overrides[get_current_user] = lambda: user
    sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
    sep_app.dependency_overrides[require_admin_for_unsafe_methods] = lambda: None
    sep_app.dependency_overrides[get_inventory_api] = lambda: inventory
    try:
        transport = ASGITransport(app=sep_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(url, params=params)
    finally:
        sep_app.dependency_overrides.clear()
        sep_app.dependency_overrides.update(previous_overrides)


def literal_members(model: type[BaseModel], field: str) -> tuple[str, ...]:
    """Return the string ``Literal`` members a model field accepts.

    Reaches through the optional wrapper (``Literal[...] | EmptyStrToNone``) so a
    test can parametrize over the vocabulary a form declares instead of restating
    it and drifting from the model.

    :param model: The model owning the field.
    :param field: The field name whose annotation carries the ``Literal``.
    :return: The declared members, in declaration order.
    """
    return tuple(
        arg
        for member in get_args(model.model_fields[field].annotation)
        for arg in get_args(member)
        if isinstance(arg, str)
    )
