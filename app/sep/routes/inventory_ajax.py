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

"""Define legacy AJAX proxy routes for inventory API schema/table data.

Serve dynamic dropdown data to Jinja2 forms that predate the shared
``/api/apps/*`` surface. New plugin API endpoints should register under
``app/sep/api/router.py`` instead of being added here.
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.pagination import fetch_all_dict_items
from app.sep.apps.framework.deprecation import DeprecatedJinja2Route
from app.sep.deps import InventoryAPI, IsAuthenticated
from app.sep.utils.decorators import csrf_exempt

logger = logging.getLogger(__name__)

router = APIRouter(route_class=DeprecatedJinja2Route)


@router.get("/services/{service_id}/schemas", dependencies=[IsAuthenticated])
@csrf_exempt
async def list_schemas(
    request: Request,  # noqa: ARG001
    service_id: int,
    inventory_api: InventoryAPI,
    search: str | None = None,
) -> JSONResponse:
    """Return schemas for a service as JSON for AJAX dropdowns."""
    try:
        items = await fetch_all_dict_items(
            lambda pagination: inventory_api.get(
                f"/services/{service_id}/schemas/",
                params={
                    **pagination.model_dump(),
                    **({"search": search} if search else {}),
                },
            )
        )
    except HTTPException:
        return JSONResponse([])
    return JSONResponse([{"id": s["id"], "name": s["name"]} for s in items])


@router.get("/schemas/{schema_id}/tables", dependencies=[IsAuthenticated])
@csrf_exempt
async def list_tables(
    request: Request,  # noqa: ARG001
    schema_id: int,
    inventory_api: InventoryAPI,
    search: str | None = None,
) -> JSONResponse:
    """Return tables for a schema as JSON for AJAX dropdowns."""
    try:
        items = await fetch_all_dict_items(
            lambda pagination: inventory_api.get(
                f"/schemas/{schema_id}/tables/",
                params={
                    **pagination.model_dump(),
                    **({"search": search} if search else {}),
                },
            )
        )
    except HTTPException:
        return JSONResponse([])
    return JSONResponse([{"id": t["id"], "name": t["name"]} for t in items])
