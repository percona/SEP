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

"""Define routes for the Inventory App."""

import logging
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Form,
    Header,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.exceptions import HTTPBadRequestException
from app.core.pagination import fetch_all_dict_items
from app.inventory.models import ServiceTypeEnum
from app.sep.api.host_resolution import resolve_executor_name_by_address
from app.sep.apps.framework.deprecation import DeprecatedJinja2Route
from app.sep.apps.inventory.deps import (
    build_available_syncers,
    filter_syncers_by_name,
    InternalTokenDep,
    SyncersDep,
)
from app.sep.apps.inventory.models import InventorySyncScheduleCreateForm
from app.sep.apps.inventory.sync import (
    get_internal_token,
    run_inventory_sync,
    run_node_sync,
    run_schema_sync,
    run_service_sync,
)
from app.sep.config import sep_settings
from app.sep.crud import SyncItemManager
from app.sep.deps import (
    AVAILABLE_TIMEZONES,
    CreatedNodeDep,
    CreatedSchemaDep,
    CreatedServiceDep,
    CreatedTableDep,
    DefaultContext,
    InventoryAPI,
    IsAuthenticated,
    IsCsrfValidated,
    SessionDep,
    TaskAPI,
)
from app.sep.inventory import Node, Schema, Service, SourceEnum, Table
from app.sep.middleware import messages
from app.sep.models import SyncInventoryEntityTypeEnum
from app.tasks.connectivity.models import ConnectivityCheckResponse

logger = logging.getLogger(__name__)
router = APIRouter(route_class=DeprecatedJinja2Route)
templates = sep_settings.TEMPLATES

CONNECTABLE_SERVICE_TYPES = frozenset(
    {
        ServiceTypeEnum.MYSQL,
        ServiceTypeEnum.POSTGRESQL,
        ServiceTypeEnum.MONGODB,
    }
)


def _is_scheduled_sync_enabled() -> bool:
    """Return whether scheduled inventory sync is enabled.

    The feature requires a non-empty internal service token; ``Settings``
    derives one from ``SECRET_KEY`` when it is unset, so this is effectively
    always enabled in a booted deployment.

    :return: True if scheduled sync is enabled.
    :rtype: bool
    """
    return get_internal_token() is not None


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def node_list(
    session: SessionDep,
    syncers: SyncersDep,
    request: Request,
    context: DefaultContext,
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
) -> HTMLResponse:
    """List Nodes."""
    context["inventory"] = await fetch_all_dict_items(
        lambda pagination: inventory_api.get("/nodes/", params=pagination.model_dump())
    )
    context["source_enum"] = SourceEnum
    context["sync_is_running"] = await SyncItemManager.sync_is_running(
        session,
        SyncInventoryEntityTypeEnum.INVENTORY,
    )
    context["available_syncers"] = build_available_syncers(
        syncers,
        lambda syncer: syncer.can_sync_inventory(),
    )
    context["can_sync"] = bool(context["available_syncers"])
    context["scheduled_sync_enabled"] = _is_scheduled_sync_enabled()
    context["sync_schedules"] = await tasks_api.get("/inventory-sync/periodic/")
    context["AVAILABLE_TIMEZONES"] = AVAILABLE_TIMEZONES
    return templates.TemplateResponse(
        request=request,
        name="inventory/node-list.html.j2",
        context=context,
    )


@router.post(
    "/sync/",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    include_in_schema=False,
)
async def sync_inventory(
    syncers: SyncersDep,
    background_tasks: BackgroundTasks,
    internal_token: InternalTokenDep,
    syncer_name: Annotated[str | None, Form(alias="syncer")] = None,
) -> RedirectResponse:
    """Start inventory sync as a background task.

    Deprecated in favour of the React sync control at
    ``POST /api/apps/inventory/sync/``; functional until Wave 3.
    """
    try:
        selected = filter_syncers_by_name(
            syncers,
            syncer_name,
            lambda syncer: syncer.can_sync_inventory(),
        )
    except ValueError as exc:
        raise HTTPBadRequestException(str(exc)) from exc
    background_tasks.add_task(run_inventory_sync, internal_token, *selected)
    return RedirectResponse("/inventory/", status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/schedule/",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    include_in_schema=False,
)
async def schedule_create(
    syncers: SyncersDep,
    tasks_api: TaskAPI,
    schedule: Annotated[InventorySyncScheduleCreateForm, Form()],
    referer: Annotated[str, Header()] = "/inventory/",
) -> RedirectResponse:
    """Attach a periodic schedule to the inventory-sync task.

    Deprecated in favour of the React schedule UI; functional until
    Wave 3 when the Jinja2 path is retired.

    Validate the optional ``syncer`` field and the interval/crontab shape at
    form-submit time using ``filter_syncers_by_name`` and explicit checks so
    invalid input fails fast with a friendly redirect rather than silently
    misfiring inside the worker. When ``syncer`` is unset the schedule runs
    every configured syncer; when set it targets only that syncer.

    :param syncers: The configured syncers from ``SyncersDep``.
    :type syncers: SyncersDep
    :param tasks_api: The Tasks API client.
    :type tasks_api: TaskAPI
    :param schedule: The submitted attach form.
    :type schedule: InventorySyncScheduleCreateForm
    :param referer: The originating page used for the redirect on success.
    :type referer: str
    :return: A 303 redirect back to the originating page.
    :rtype: RedirectResponse
    :raises HTTPBadRequestException: If ``SEP_INTERNAL_TOKEN`` is not
        configured, the syncer name is unknown, or both / neither schedule
        mode is supplied.
    """
    if not _is_scheduled_sync_enabled():
        raise HTTPBadRequestException(
            "SEP_INTERNAL_TOKEN must be configured before attaching an "
            "inventory-sync schedule.",
        )
    if schedule.syncer:
        try:
            filter_syncers_by_name(
                syncers,
                schedule.syncer,
                lambda candidate: candidate.can_sync_inventory(),
            )
        except ValueError as exc:
            raise HTTPBadRequestException(str(exc)) from exc
    if schedule.interval and schedule.crontab:
        raise HTTPBadRequestException(
            "Cannot specify both interval and crontab; choose one schedule mode.",
        )
    if not schedule.interval and not schedule.crontab:
        raise HTTPBadRequestException(
            "Either interval or crontab must be specified.",
        )
    payload = schedule.to_periodic_task_payload()
    logger.debug("Attaching inventory-sync schedule, %s", payload)
    await tasks_api.post("/inventory-sync/periodic/", json=payload)
    return RedirectResponse(referer, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{node_id}", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def node_detail(
    session: SessionDep,
    syncers: SyncersDep,
    request: Request,
    node: CreatedNodeDep,
    context: DefaultContext,
) -> HTMLResponse:
    """Retrieve Node Details."""
    context["node"] = node
    context["sync_is_running"] = await SyncItemManager.sync_is_running(
        session,
        SyncInventoryEntityTypeEnum.NODE,
    )
    context["available_syncers"] = build_available_syncers(
        syncers,
        lambda syncer: syncer.can_sync_node(node),
    )
    context["can_sync"] = bool(context["available_syncers"])
    return templates.TemplateResponse(
        request=request,
        name="inventory/node-detail.html.j2",
        context=context,
    )


@router.post("/{node_id}/sync/", dependencies=[IsAuthenticated, IsCsrfValidated])
async def sync_node(
    node: CreatedNodeDep,
    syncers: SyncersDep,
    background_tasks: BackgroundTasks,
    internal_token: InternalTokenDep,
    syncer_name: Annotated[str | None, Form(alias="syncer")] = None,
) -> RedirectResponse:
    """Start node sync as a background task."""
    try:
        selected = filter_syncers_by_name(
            syncers,
            syncer_name,
            lambda syncer: syncer.can_sync_node(node),
        )
    except ValueError as exc:
        raise HTTPBadRequestException(str(exc)) from exc
    background_tasks.add_task(run_node_sync, node, internal_token, *selected)
    return RedirectResponse(
        f"/inventory/{node.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/", dependencies=[IsAuthenticated, IsCsrfValidated])
async def node_create(
    inventory_api: InventoryAPI,
    node_data: Annotated[Node, Form()],
) -> RedirectResponse:
    """Create Node."""
    await inventory_api.post("/nodes/", json=node_data.model_dump(exclude={"services"}))
    return RedirectResponse("/inventory/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{node_id}/delete", dependencies=[IsAuthenticated, IsCsrfValidated])
async def node_delete(
    node_id: int,
    inventory_api: InventoryAPI,
) -> RedirectResponse:
    """Delete Node."""
    await inventory_api.delete(f"/nodes/{node_id}")
    return RedirectResponse("/inventory/", status_code=status.HTTP_303_SEE_OTHER)


@router.get(
    "/services/{service_id}",
    dependencies=[IsAuthenticated],
    response_class=HTMLResponse,
)
async def service_detail(
    session: SessionDep,
    syncers: SyncersDep,
    request: Request,
    service: CreatedServiceDep,
    context: DefaultContext,
) -> HTMLResponse:
    """Retrieve Service Details."""
    context["service"] = service
    context["sync_is_running"] = await SyncItemManager.sync_is_running(
        session,
        SyncInventoryEntityTypeEnum.SERVICE,
    )
    context["available_syncers"] = build_available_syncers(
        syncers,
        lambda syncer: syncer.can_sync_service(service),
    )
    context["can_sync"] = bool(context["available_syncers"])
    context["can_check_connectivity"] = service.type in CONNECTABLE_SERVICE_TYPES
    return templates.TemplateResponse(
        request=request,
        name="inventory/service-detail.html.j2",
        context=context,
    )


@router.post(
    "/services/{service_id}/sync/", dependencies=[IsAuthenticated, IsCsrfValidated]
)
async def sync_service(
    service: CreatedServiceDep,
    syncers: SyncersDep,
    background_tasks: BackgroundTasks,
    internal_token: InternalTokenDep,
    syncer_name: Annotated[str | None, Form(alias="syncer")] = None,
) -> RedirectResponse:
    """Start service sync as a background task."""
    try:
        selected = filter_syncers_by_name(
            syncers,
            syncer_name,
            lambda syncer: syncer.can_sync_service(service),
        )
    except ValueError as exc:
        raise HTTPBadRequestException(str(exc)) from exc
    background_tasks.add_task(run_service_sync, service, internal_token, *selected)
    return RedirectResponse(
        f"/inventory/services/{service.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/services/{service_id}/check-connectivity/",
    dependencies=[IsAuthenticated, IsCsrfValidated],
)
async def check_service_connectivity(
    request: Request,
    service: CreatedServiceDep,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Check database connectivity for a service via Nomad."""
    redirect = RedirectResponse(
        f"/inventory/services/{service.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    if service.type not in CONNECTABLE_SERVICE_TYPES:
        messages.error(
            request,
            f"Connectivity check is not supported for {service.type.name} services",
        )
        return redirect
    if service.node is None or service.port is None:
        messages.error(
            request,
            f"Connectivity check failed for {service.name}: "
            "missing node or port information",
        )
        return redirect
    # Fetch executor hosts inline rather than via ``ExecutorHosts`` so we can
    # early-abort with a ``service.name``-specific flash; the dep continues
    # with an empty mapping and would emit a second, generic flash on failure.
    try:
        executor_hosts: dict[str, str] = await tasks_api.get("/hosts/")
    except HTTPException as exc:
        logger.warning(
            "Tasks API error fetching executor hosts for service %s: %s",
            service.id,
            exc.detail,
        )
        messages.error(
            request,
            f"Connectivity check failed for {service.name}: {exc.detail}",
        )
        return redirect
    except Exception:
        logger.exception(
            "Failed to fetch executor hosts for connectivity check on service %s",
            service.id,
        )
        messages.error(
            request,
            f"Connectivity check failed for {service.name}: "
            "could not reach the Tasks API",
        )
        return redirect
    executor_target = resolve_executor_name_by_address(
        service.node.address, executor_hosts
    )
    if executor_target is None:
        messages.error(
            request,
            f"Connectivity check failed for {service.name}: "
            f"no executor host is registered for address "
            f"{service.node.address!r} (inventory node {service.node.name!r}).",
        )
        return redirect
    try:
        result = ConnectivityCheckResponse.model_validate(
            await tasks_api.post(
                "/connectivity-check/",
                json={
                    "target": executor_target,
                    "host": service.node.address,
                    "port": service.port,
                    "service_type": service.type.value,
                },
            )
        )
        if result.success:
            messages.success(
                request,
                f"Connectivity check passed for {service.name}",
            )
        else:
            messages.error(
                request,
                f"Connectivity check failed for {service.name}: "
                f"{result.error or 'Unknown error'}",
            )
    except HTTPException as exc:
        logger.warning(
            "Connectivity check API error for service %s: %s",
            service.id,
            exc.detail,
        )
        messages.error(
            request,
            f"Connectivity check failed for {service.name}: {exc.detail}",
        )
    except Exception:
        logger.exception("Connectivity check failed for service %s", service.id)
        messages.error(
            request,
            f"Connectivity check failed for {service.name}: "
            "could not reach the Tasks API",
        )
    return redirect


@router.post("/{node_id}/services/", dependencies=[IsAuthenticated, IsCsrfValidated])
async def service_create_for_node(
    node_id: int,
    inventory_api: InventoryAPI,
    service_data: Annotated[Service, Form()],
) -> RedirectResponse:
    """Create Service for Node."""
    await inventory_api.post(
        f"/nodes/{node_id}/services/",
        json=service_data.model_dump(exclude={"schemas"}),
    )
    return RedirectResponse(
        f"/inventory/{node_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/services/{service_id}/delete", dependencies=[IsAuthenticated, IsCsrfValidated]
)
async def service_delete(
    inventory_api: InventoryAPI,
    service: CreatedServiceDep,
) -> RedirectResponse:
    """Delete Service."""
    await inventory_api.delete(f"/services/{service.id}")
    return RedirectResponse(
        f"/inventory/{service.node_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get(
    "/schemas/{schema_id}",
    dependencies=[IsAuthenticated],
    response_class=HTMLResponse,
)
async def schema_detail(
    session: SessionDep,
    syncers: SyncersDep,
    request: Request,
    schema: CreatedSchemaDep,
    context: DefaultContext,
) -> HTMLResponse:
    """Retrieve Schema Details."""
    context["schema"] = schema
    context["sync_is_running"] = await SyncItemManager.sync_is_running(
        session,
        SyncInventoryEntityTypeEnum.SCHEMA,
    )
    context["available_syncers"] = build_available_syncers(
        syncers,
        lambda syncer: syncer.can_sync_schema(schema),
    )
    context["can_sync"] = bool(context["available_syncers"])
    return templates.TemplateResponse(
        request=request,
        name="inventory/schema-detail.html.j2",
        context=context,
    )


@router.post(
    "/schemas/{schema_id}/sync/", dependencies=[IsAuthenticated, IsCsrfValidated]
)
async def sync_schema(
    schema: CreatedSchemaDep,
    syncers: SyncersDep,
    background_tasks: BackgroundTasks,
    internal_token: InternalTokenDep,
    syncer_name: Annotated[str | None, Form(alias="syncer")] = None,
) -> RedirectResponse:
    """Start schema sync as a background task."""
    try:
        selected = filter_syncers_by_name(
            syncers,
            syncer_name,
            lambda syncer: syncer.can_sync_schema(schema),
        )
    except ValueError as exc:
        raise HTTPBadRequestException(str(exc)) from exc
    background_tasks.add_task(run_schema_sync, schema, internal_token, *selected)
    return RedirectResponse(
        f"/inventory/schemas/{schema.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/services/{service_id}/schemas/", dependencies=[IsAuthenticated, IsCsrfValidated]
)
async def schema_create_for_service(
    service_id: int,
    inventory_api: InventoryAPI,
    schema_data: Annotated[Schema, Form()],
) -> RedirectResponse:
    """Create Schema for Service."""
    await inventory_api.post(
        f"/services/{service_id}/schemas/",
        json=schema_data.model_dump(exclude={"tables"}),
    )
    return RedirectResponse(
        f"/inventory/services/{service_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/schemas/{schema_id}/delete", dependencies=[IsAuthenticated, IsCsrfValidated]
)
async def schema_delete(
    inventory_api: InventoryAPI,
    schema: CreatedSchemaDep,
) -> RedirectResponse:
    """Delete Schema."""
    await inventory_api.delete(f"/schemas/{schema.id}")
    return RedirectResponse(
        f"/inventory/services/{schema.service_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/schemas/{schema_id}/tables/", dependencies=[IsAuthenticated, IsCsrfValidated]
)
async def table_create_for_schema(
    schema_id: int,
    inventory_api: InventoryAPI,
    table_data: Annotated[Table, Form()],
) -> RedirectResponse:
    """Create Table for Schema."""
    await inventory_api.post(
        f"/schemas/{schema_id}/tables/",
        json=table_data.model_dump(),
    )
    return RedirectResponse(
        f"/inventory/schemas/{schema_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/tables/{table_id}/delete", dependencies=[IsAuthenticated, IsCsrfValidated]
)
async def table_delete(
    inventory_api: InventoryAPI,
    table: CreatedTableDep,
) -> RedirectResponse:
    """Delete Table."""
    await inventory_api.delete(f"/tables/{table.id}")
    return RedirectResponse(
        f"/inventory/schemas/{table.schema_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
