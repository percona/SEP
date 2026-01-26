"""Routes for the Dipper plugin."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
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
from app.sep.plugins.dipper.constants import (
    CollectorTypeEnum,
    DIPPER_SCRIPT_BY_SERVICE_TYPE,
)
from app.sep.plugins.dipper.deps import (
    DipperScriptDep,
    get_dipper_execution_meta,
    get_dipper_script_filename,
    has_pmm_script,
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
    for service_type in DIPPER_SCRIPT_BY_SERVICE_TYPE:
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
    service_id: int | None = None,
    collector_type: CollectorTypeEnum = CollectorTypeEnum.ENVIRONMENT,
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
    context["collector_type"] = collector_type
    context["pmm_available"] = False

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

    if service_data.get("type") not in {t.value for t in DIPPER_SCRIPT_BY_SERVICE_TYPE}:
        messages.error(request, "Selected service type is not supported by Dipper")
        return templates.TemplateResponse(
            request=request, name="dipper/index.html", context=context
        )

    selected_service = CreatedService.model_validate(service_data)
    context["selected_service"] = selected_service
    context["pmm_available"] = has_pmm_script(selected_service.type)

    script_filename = get_dipper_script_filename(selected_service.type, collector_type)
    script = await DipperScript.from_path(script_filename, update_meta=True)
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
    execute_url = f"/dipper/execute?service_id={selected_service.id}&collector_type={collector_type.value}"
    context["script_form"] = script.to_form(
        list({resolved_host}),
        execute_url,
    )

    snippet_filename = f"dipper/{selected_service.id}/{script.filename}"
    history_tasks = await tasks_api.get(
        f"/{script.execution_task_name}/history/",
        params={"snippet_filename": snippet_filename},
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
        f"/{script.execution_task_name}/history/",
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
    script: DipperScriptDep,
    service_id: int,
    collector_type: CollectorTypeEnum = CollectorTypeEnum.ENVIRONMENT,
) -> RedirectResponse:
    """Dispatch an exec-artifact job for the selected service."""
    await tasks_api.post(
        f"/execute/{script.execution_task_name}",
        json={"meta": execution_meta.model_dump(by_alias=True, exclude_none=True)},
    )
    messages.success(request, "Data collection started")
    return RedirectResponse(
        request.url_for("dipper_index").include_query_params(
            service_id=service_id, collector_type=collector_type.value
        ),
        status_code=status.HTTP_303_SEE_OTHER,
    )
