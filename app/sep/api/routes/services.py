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

from fastapi import APIRouter, Query

from app.core.db.crud import DEFAULT_PAGINATION_LIMIT, DEFAULT_PAGINATION_OFFSET
from app.core.models import PaginatedResponse
from app.inventory.models import ServiceResponse, ServiceTypeEnum
from app.sep.deps import InventoryAPI

router = APIRouter()


@router.get("/", response_model=PaginatedResponse[ServiceResponse])
async def list_services(
    inventory_api: InventoryAPI,
    service_type: ServiceTypeEnum | None = None,
    offset: int = Query(default=DEFAULT_PAGINATION_OFFSET, ge=0),
    limit: int = Query(default=DEFAULT_PAGINATION_LIMIT, ge=0),
) -> PaginatedResponse[ServiceResponse]:
    """Return a paginated list of inventory services via the SEP gateway.

    :param inventory_api: The Inventory API client used to proxy the request.
    :type inventory_api: InventoryAPI
    :param service_type: Optional service type filter forwarded to inventory.
    :type service_type: ServiceTypeEnum | None
    :param offset: Pagination offset; must be non-negative.
    :type offset: int
    :param limit: Pagination limit; must be non-negative.
    :type limit: int
    :return: Paginated services payload.
    :rtype: PaginatedResponse[ServiceResponse]
    """
    params: dict[str, int | str] = {"offset": offset, "limit": limit}
    if service_type is not None:
        params["service_type"] = service_type.value
    response = await inventory_api.get("/services/", params=params)
    return PaginatedResponse[ServiceResponse].model_validate(response)
