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

"""Define the ``/api/sep/schemas/`` JSON endpoint exposing inventory tables.

Proxy the Inventory ``/schemas/{schema_id}/tables/`` listing so the React
frontend can populate schema-driven table selectors without bypassing the SEP
layer (see the non-bypass rule in ``app/sep/api/router.py``).
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.sep.deps import InventoryAPI

router = APIRouter()


class InventorySelectorOption(BaseModel):
    """Represent a minimal ``{id, name}`` option for inventory autocomplete selectors.

    :param id: The inventory entity ID consumed by form payloads.
    :type id: int
    :param name: The human-readable display label.
    :type name: str
    """

    id: int
    name: str


@router.get("/{schema_id}/tables", response_model=list[InventorySelectorOption])
async def list_schema_tables(
    schema_id: int,
    inventory_api: InventoryAPI,
    search: str | None = None,
) -> list[InventorySelectorOption]:
    """Return tables for a schema via the SEP gateway.

    Proxies Inventory ``GET /schemas/{schema_id}/tables/`` for React
    ``TableSelector`` components. Returns an empty list when the schema is
    missing or inventory raises an HTTP error (matches legacy AJAX behavior).

    :param schema_id: The inventory schema ID whose tables are listed.
    :type schema_id: int
    :param inventory_api: The Inventory API client used to proxy the request.
    :type inventory_api: InventoryAPI
    :param search: Optional substring filter forwarded to inventory.
    :type search: str | None
    :return: Minimal id/name options for each table in the schema.
    :rtype: list[InventorySelectorOption]
    """
    params: dict[str, int | str] = {"limit": 0}
    if search:
        params["search"] = search
    try:
        tables = await inventory_api.get(f"/schemas/{schema_id}/tables/", params=params)
    except HTTPException:
        return []
    return [
        InventorySelectorOption(id=t["id"], name=t["name"]) for t in tables["items"]
    ]
