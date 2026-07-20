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

Mounted at ``/api/apps/dipper/`` via ``apps_router`` in
``app/sep/api/router.py``. Authentication is enforced at the ``api_router``
mount level (``IsApiAuthenticated``) and by ``RequireBearerForUnsafeMethods``
on the ``apps_router``. Route layout:

* ``GET /schema``          — static plugin schema
* ``GET /``                — Dipper execution history
* ``GET /form-schema``     — context-specific execute form schema
* ``GET /script-preview``  — preview the collector script for a service
* ``POST /``               — execute a collector script against a service
"""

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi import status as http_status

from app.core.exceptions import HTTPNotFoundException, HTTPUnprocessableEntityException
from app.core.pagination import build_proxied_page, PaginatedResponse, PaginationDep
from app.sep.apps.dipper.constants import CollectorTypeEnum
from app.sep.apps.dipper.deps import (
    build_dipper_execution_meta,
    fetch_pmm_node_service_names,
    get_dipper_script_preview,
    get_pmm_form_defaults,
    load_dipper_script,
    PMMAPIDep,
    resolve_pmm_executor_host,
)
from app.sep.apps.dipper.models import (
    DipperExecuteWrite,
    DipperExecutionResponse,
)
from app.sep.apps.dipper.schema import build_dipper_form_schema, dipper_schema
from app.sep.apps.framework.api import schema_endpoint
from app.sep.apps.framework.schema import AppSchema
from app.sep.apps.framework.script_helpers import post_task_execution
from app.sep.apps.framework.script_source import ScriptPreviewResponse
from app.sep.deps import ExecutorHosts, InventoryAPI, TaskAPI
from app.sep.inventory import CreatedService

logger = logging.getLogger(__name__)

router = APIRouter()
schema_endpoint(router=router, plugin_schema=dipper_schema)


def _execution_request_for(history: dict[str, Any]) -> dict[str, Any]:
    """Return a task-history row's execution request mapping."""
    value = history.get("execution_request") or history.get("executionRequest")
    return value if isinstance(value, dict) else {}


def _snippet_filename_for(history: dict[str, Any]) -> str | None:
    """Return a task-history row's snippet filename metadata."""
    request = _execution_request_for(history)
    meta = request.get("meta")
    # The tasks API serialises snippet_filename inside a nested ``meta`` dict for
    # newer Nomad driver versions, and directly on the request for older records;
    # both snake_case and camelCase keys appear across task history rows.
    if isinstance(meta, dict):
        value = meta.get("_snippet_filename") or meta.get("snippet_filename")
        return str(value) if value else None
    value = request.get("_snippet_filename") or request.get("snippet_filename")
    return str(value) if value else None


@router.get("/")
async def dipper_api_list(
    tasks_api: TaskAPI, pagination: PaginationDep
) -> PaginatedResponse[dict[str, Any]]:
    """Return Dipper execution history rows.

    :param tasks_api: Async client for the tasks sub-app.
    :param pagination: Validated offset/limit forwarded to the upstream history call.
    :return: A paginated envelope of task-history rows filtered to Dipper runs. Because
        the ``dipper/`` filter runs client-side, ``total`` is the filtered count of the
        current page, not a global count across all pages.
    """
    response = await tasks_api.get(
        "/history/", params={"offset": pagination.offset, "limit": pagination.limit}
    )
    items = [
        item
        for item in response.get("items", [])
        if (_snippet_filename_for(item) or "").startswith("dipper/")
    ]
    return build_proxied_page(items, response, pagination, client_side_filtered=True)


@router.get(
    "/form-schema",
    response_model_by_alias=True,
)
async def dipper_api_form_schema(
    service_id: int,
    collector_type: CollectorTypeEnum,
    inventory_api: InventoryAPI,
    executor_hosts: ExecutorHosts,
    pmm_api: PMMAPIDep,
) -> AppSchema:
    """Return the selected Dipper payload's dynamic execution schema.

    :param service_id: Inventory ID of the database service.
    :type service_id: int
    :param collector_type: Which collector variant to render.
    :type collector_type: CollectorTypeEnum
    :param inventory_api: Async client for the inventory sub-app.
    :type inventory_api: RemoteAPI
    :param executor_hosts: Available executor hosts keyed by hostname.
    :type executor_hosts: dict
    :param pmm_api: The configured PMM API client, or ``None`` when PMM is not
        configured (injected via ``PMMAPIDep``).
    :type pmm_api: PMMRemoteAPI | None
    :return: Context-specific schema including payload parameters.
    """
    service_data = await inventory_api.get(f"/services/{service_id}")
    service = CreatedService.model_validate(service_data)
    try:
        script = await load_dipper_script(service, collector_type, update_meta=True)
    except HTTPNotFoundException as exc:
        raise HTTPUnprocessableEntityException(
            detail=(
                f"No {collector_type.value!r} collector script is available"
                f" for {service.type.value!r} services."
            )
        ) from exc
    defaults = None
    node_options: list[str] = []
    service_options: list[str] = []
    if collector_type == CollectorTypeEnum.PMM:
        defaults = get_pmm_form_defaults(
            resolve_pmm_executor_host(executor_hosts),
            service.name,
            service.node.name if service.node else "",
        )
        node_options, service_options = await fetch_pmm_node_service_names(pmm_api)
    return build_dipper_form_schema(
        script,
        service.id,
        collector_type.value,
        defaults=defaults,
        node_options=node_options,
        service_options=service_options,
    )


@router.get("/script-preview")
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
    :raises HTTPNotFoundException: When the service does not exist.
    :raises HTTPUnprocessableEntityException: When no script is available for
        the service/collector combination, or when the script contains
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
    status_code=http_status.HTTP_201_CREATED,
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
    task_id = await post_task_execution(tasks_api, execution_task_name, execution_meta)
    return DipperExecutionResponse(
        task_id=task_id,
        task_name=execution_task_name,
        snippet_filename=execution_meta.snippet_filename,
        service_id=service.id,
        collector_type=body.collector_type,
    )
