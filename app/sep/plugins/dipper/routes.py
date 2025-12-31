"""Routes for the Dipper plugin."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.sep.config import sep_settings
from app.sep.deps import (
    DefaultContext,
    ExecutorHosts,
    InventoryAPI,
    IsAuthenticated,
    TaskAPI,
)
from app.sep.inventory import CreatedService
from app.sep.middleware import messages
from app.sep.plugins.dipper.constants import DIPPER_SUPPORTED_SERVICE_TYPES
from app.sep.plugins.dipper.deps import (
    get_dipper_execution_meta,
    get_dipper_script_filename,
    resolve_executor_host_for_service,
)
from app.sep.plugins.dipper.models import DipperScript
from app.sep.snippets.models.snippet import SnippetExecutionMeta
from app.sep.utils.jinja import syntax_highlight
from app.tasks.models import TaskHistoryStatusEnum

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES

ExecutionMetaDep = Annotated[SnippetExecutionMeta, Depends(get_dipper_execution_meta)]


async def _list_supported_services(inventory_api: InventoryAPI) -> list[dict]:
    services: list[dict] = []
    for service_type in DIPPER_SUPPORTED_SERVICE_TYPES:
        services.extend(
            await inventory_api.get(
                "/services/", params={"service_type": service_type.value}
            )
        )
    return services


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def dipper_index(
    request: Request,
    context: DefaultContext,
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    executor_hosts: ExecutorHosts,
    service_id: int | None = Query(default=None),
) -> HTMLResponse:
    """Render the Dipper page with service selection and execution history."""
    context["services"] = await _list_supported_services(inventory_api)
    context["selected_service_id"] = service_id
    context["selected_service"] = None
    context["script"] = None
    context["script_preview"] = None
    context["script_form"] = None
    context["history_tasks"] = []
    context["running_tasks"] = []

    if service_id is None:
        return templates.TemplateResponse(
            request=request, name="dipper/index.html", context=context
        )

    try:
        service_data = await inventory_api.get(f"/services/{service_id}")
    except HTTPException as exc:
        messages.error(request, f"Could not load service {service_id}: {exc.detail}")
        return templates.TemplateResponse(
            request=request, name="dipper/index.html", context=context
        )

    if service_data.get("type") not in {
        t.value for t in DIPPER_SUPPORTED_SERVICE_TYPES
    }:
        messages.error(request, "Selected service type is not supported by Dipper")
        return templates.TemplateResponse(
            request=request, name="dipper/index.html", context=context
        )

    selected_service = CreatedService.model_validate(service_data)
    context["selected_service"] = selected_service

    script_filename = get_dipper_script_filename(selected_service.type)
    script = await DipperScript.from_filename(script_filename)
    context["script"] = script
    try:
        preview = await script.get_preview()
        context["script_preview"] = syntax_highlight(
            preview.content, style="monokai", linenos=True, wrapcode=True
        )
    except UnicodeDecodeError:
        logger.exception("Could not decode dipper script for preview")

    resolved_host = resolve_executor_host_for_service(executor_hosts, selected_service)
    if resolved_host is None:
        messages.warning(
            request,
            "Could not map selected service to a Nomad client hostname; execution may fail.",
        )
        resolved_host = next(iter(executor_hosts.keys()), "")

    context["resolved_executor_host"] = resolved_host
    context["script_form"] = script.to_form(
        list({resolved_host}),
        f"/dipper/execute?service_id={selected_service.id}",
    )

    snippet_filename = f"dipper/{selected_service.id}/{script.filename}"
    history_tasks = await tasks_api.get(
        "/exec-artifact/history/", params={"snippet_filename": snippet_filename}
    )
    for history in history_tasks:
        try:
            history["available_files"] = await tasks_api.get(
                f"/history/{history['id']}/files/"
            )
        except HTTPException:
            history["available_files"] = []
    context["history_tasks"] = history_tasks
    context["running_tasks"] = await tasks_api.get(
        "/exec-artifact/history/",
        params={
            "snippet_filename": snippet_filename,
            "status": TaskHistoryStatusEnum.RUNNING,
        },
    )

    return templates.TemplateResponse(
        request=request,
        name="dipper/index.html",
        context=context,
    )


@router.post("/execute", dependencies=[IsAuthenticated])
async def dipper_execute(
    request: Request,
    tasks_api: TaskAPI,
    execution_meta: ExecutionMetaDep,
    service_id: int = Query(...),
) -> RedirectResponse:
    """Dispatch an exec-artifact job for the selected service."""
    await tasks_api.post(
        "/execute/exec-artifact",
        json={"meta": execution_meta.model_dump(by_alias=True)},
    )
    messages.success(request, "Data collection started")
    return RedirectResponse(
        request.url_for("dipper_index").include_query_params(service_id=service_id),
        status_code=status.HTTP_303_SEE_OTHER,
    )
