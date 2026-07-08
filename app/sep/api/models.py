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

"""Shared Pydantic models and helpers for SEP JSON API routes."""

from pydantic import BaseModel

from app.core.exceptions import HTTPNotFoundException
from app.core.pagination import fetch_all_dict_items, PaginatedDictPage, Pagination
from app.sep.deps import InventoryAPI


class InventorySelectorOption(BaseModel):
    """Represent a minimal ``{id, name}`` option for inventory autocomplete selectors.

    :param id: The inventory entity ID consumed by form payloads.
    :type id: int
    :param name: The human-readable display label.
    :type name: str
    """

    id: int
    name: str


async def proxy_inventory_selector(
    inventory_api: InventoryAPI,
    url: str,
    search: str | None,
) -> list[InventorySelectorOption]:
    """Proxy a selector endpoint and normalize to ``[{id, name}]`` options.

    :param inventory_api: The Inventory API client used to proxy the request.
    :type inventory_api: InventoryAPI
    :param url: Inventory endpoint URL (for example ``/services/{id}/schemas/``).
    :type url: str
    :param search: Optional substring filter forwarded to inventory.
    :type search: str | None
    :return: Minimal selector options, or an empty list on Inventory 404.
    :rtype: list[InventorySelectorOption]
    """
    try:

        async def fetch_page(pagination: Pagination) -> PaginatedDictPage:
            return await inventory_api.get(
                url,
                params={
                    **pagination.model_dump(),
                    **({"search": search} if search else {}),
                },
            )

        items = await fetch_all_dict_items(fetch_page)
    except HTTPNotFoundException:
        return []
    return [
        InventorySelectorOption(id=item["id"], name=item["name"])
        for item in items
        if isinstance(item, dict)
    ]
