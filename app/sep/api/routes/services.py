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

"""Define the ``/api/sep/services/`` JSON endpoint exposing inventory services.

Proxy the Inventory ``/services/`` listing so the React frontend can populate
schema-driven service selectors without bypassing the SEP layer (see the
non-bypass rule in ``app/sep/api/router.py``).
"""

from fastapi import APIRouter

from app.core.pagination import PaginatedResponse
from app.core.pagination.deps import PaginationDep
from app.inventory.models import ServiceResponse, ServiceTypeEnum
from app.sep.api.models import InventorySelectorOption, proxy_inventory_selector
from app.sep.deps import InventoryAPI

router = APIRouter()


@router.get("/")
async def list_services(
    inventory_api: InventoryAPI,
    pagination: PaginationDep,
    service_type: ServiceTypeEnum | None = None,
) -> PaginatedResponse[ServiceResponse]:
    """Return a paginated list of inventory services via the SEP gateway.

    :param inventory_api: The Inventory API client used to proxy the request.
    :type inventory_api: InventoryAPI
    :param service_type: Optional service type filter forwarded to inventory.
    :type service_type: ServiceTypeEnum | None
    :param pagination: Validated pagination window for this request.
    :type pagination: Pagination
    :return: Paginated services payload.
    :rtype: PaginatedResponse[ServiceResponse]
    """
    params: dict[str, int | str] = pagination.model_dump()
    if service_type is not None:
        params["service_type"] = service_type.value
    response = await inventory_api.get("/services/", params=params)
    return PaginatedResponse[ServiceResponse].model_validate(response)


@router.get("/{service_id}/schemas")
async def list_service_schemas(
    service_id: int,
    inventory_api: InventoryAPI,
    search: str | None = None,
) -> list[InventorySelectorOption]:
    """Return schemas for a service via the SEP gateway.

    Proxies Inventory ``GET /services/{service_id}/schemas/`` for React
    ``SchemaSelector`` components. Returns an empty list only when Inventory
    responds with 404 (missing service); other HTTP errors propagate to the
    global handler (matches legacy AJAX empty-selector UX for not-found only).

    :param service_id: The inventory service ID whose schemas are listed.
    :type service_id: int
    :param inventory_api: The Inventory API client used to proxy the request.
    :type inventory_api: InventoryAPI
    :param search: Optional substring filter forwarded to inventory.
    :type search: str | None
    :return: Minimal id/name options for each schema on the service.
    :rtype: list[InventorySelectorOption]
    """
    return await proxy_inventory_selector(
        inventory_api,
        f"/services/{service_id}/schemas/",
        search,
    )
