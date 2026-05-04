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

"""Define the JSON API router for the Dipper plugin.

Mounted at ``/api/plugins/dipper/`` via ``plugins_router`` in
``app/sep/api/router.py``. Authentication is enforced at the ``api_router``
level and redeclared per route for safety. Route layout:

* ``GET /schema``          — static plugin schema
* ``GET /``                — placeholder list (dipper has no saved tasks)
* ``GET /script-preview``  — preview the collector script for a service
* ``POST /``               — execute a collector script against a service
"""

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi import status as http_status

from app.core.exceptions import HTTPNotFoundException, HTTPUnprocessableEntityException
from app.sep.deps import InventoryAPI, IsApiAuthenticated, TaskAPI
from app.sep.inventory import CreatedService
from app.sep.plugins.dipper.constants import CollectorTypeEnum
from app.sep.plugins.dipper.deps import (
    build_dipper_execution_meta,
    get_dipper_script_preview,
)
from app.sep.plugins.dipper.models import (
    DipperExecuteWrite,
    DipperExecutionResponse,
)
from app.sep.plugins.dipper.schema import dipper_schema
from app.sep.plugins.framework.api import schema_endpoint
from app.sep.plugins.snippets.models import ScriptPreviewResponse

logger = logging.getLogger(__name__)

router = APIRouter()
schema_endpoint(router=router, plugin_schema=dipper_schema)


@router.get("/", dependencies=[IsApiAuthenticated])
async def dipper_api_list() -> list[Any]:
    """Return an empty list; dipper has no saved task configurations.

    :return: Empty list.
    :rtype: list[Any]
    """
    return []


@router.get("/script-preview", dependencies=[IsApiAuthenticated])
async def dipper_api_script_preview(
    service_id: int,
    collector_type: CollectorTypeEnum,
    inventory_api: InventoryAPI,
) -> ScriptPreviewResponse:
    """Return a preview of the collector script for the given service.

    :param service_id: Inventory ID of the database service.
    :type service_id: int
    :param collector_type: Which collector variant to preview.
    :type collector_type: CollectorTypeEnum
    :param inventory_api: Async client for the inventory sub-app.
    :type inventory_api: RemoteAPI
    :return: Preview content alongside language and truncation metadata.
    :rtype: ScriptPreviewResponse
    :raises HTTPNotFoundException: When the service does not exist or no
        script is available for the service/collector combination.
    :raises HTTPUnprocessableEntityException: When the script contains
        non-UTF-8 bytes.
    """
    service_data = await inventory_api.get(f"/services/{service_id}")
    service = CreatedService.model_validate(service_data)
    try:
        return await get_dipper_script_preview(service, collector_type)
    except HTTPNotFoundException as exc:
        raise HTTPUnprocessableEntityException(
            detail=(
                f"No {collector_type.value!r} collector script is available"
                f" for {service.type.value!r} services."
            )
        ) from exc


@router.post(
    "/",
    response_model=DipperExecutionResponse,
    status_code=http_status.HTTP_201_CREATED,
    dependencies=[IsApiAuthenticated],
)
async def dipper_api_execute(
    request: Request,
    body: DipperExecuteWrite,
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
) -> DipperExecutionResponse:
    """Execute a Dipper collector script against a database service.

    Delegates all script resolution, PMM defaults merging, argument
    validation, and metadata assembly to ``build_dipper_execution_meta``.

    :param request: The HTTP request (used to derive the artifact download URL).
    :type request: Request
    :param body: Validated JSON request body.
    :type body: DipperExecuteWrite
    :param inventory_api: Async client for the inventory sub-app.
    :type inventory_api: RemoteAPI
    :param tasks_api: Async client for the tasks sub-app.
    :type tasks_api: RemoteAPI
    :return: Execution response with the created task identifier.
    :rtype: DipperExecutionResponse
    :raises HTTPNotFoundException: When the service does not exist.
    :raises HTTPUnprocessableEntityException: When the script/args are invalid.
    """
    service_data = await inventory_api.get(f"/services/{body.service_id}")
    service = CreatedService.model_validate(service_data)
    execution_meta, execution_task_name = await build_dipper_execution_meta(
        service, body, request
    )
    logger.info(
        "Executing [%s] dipper script %r for service %d",
        execution_meta.interpreter,
        execution_meta.snippet_filename,
        service.id,
    )
    created = await tasks_api.post(
        f"/execute/{execution_task_name}",
        json={"meta": execution_meta.model_dump(by_alias=True, exclude_none=True)},
    )
    return DipperExecutionResponse(
        task_id=created.get("id") if isinstance(created, dict) else None,
        task_name=execution_task_name,
        snippet_filename=execution_meta.snippet_filename,
        service_id=service.id,
        collector_type=body.collector_type,
    )
