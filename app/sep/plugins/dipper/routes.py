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
    DipperScriptWithMetaDep,
    get_dipper_execution_meta,
    get_dipper_script_filename,
    get_pmm_form_defaults,
    has_pmm_script,
    resolve_executor_host_for_service,
    resolve_pmm_executor_host,
    SupportedDipperServices,
)
from app.sep.plugins.dipper.models import DipperScript
from app.sep.snippets.models.snippet import SnippetExecutionMeta
from app.sep.utils.jinja import syntax_highlight
from app.tasks.models import TaskHistoryStatusEnum

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES

ExecutionMetaDep = Annotated[SnippetExecutionMeta, Depends(get_dipper_execution_meta)]


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def dipper_index(
    request: Request,
    context: DefaultContext,
    inventory_api: InventoryAPI,
    supported_services: SupportedDipperServices,
    tasks_api: TaskAPI,
    executor_hosts: ExecutorHosts,
    service_id: int | None = None,
    collector_type: CollectorTypeEnum = CollectorTypeEnum.ENVIRONMENT,
) -> HTMLResponse:
    """Render the Dipper page with service selection and execution history."""
    context |= {
        "services": supported_services,
        "selected_service_id": service_id,
        "collector_type": collector_type,
    }

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

    script_filename = get_dipper_script_filename(selected_service.type, collector_type)
    script = await DipperScript.from_path(script_filename, update_meta=True)
    try:
        preview = await script.get_preview()
        context["script_preview"] = syntax_highlight(
            preview.content, style="monokai", linenos=True, wrapcode=True
        )
    except UnicodeDecodeError:
        logger.exception("Could not decode dipper script for preview")

    default_executor_host = None
    if collector_type == CollectorTypeEnum.PMM:
        resolved_executor_host = resolve_pmm_executor_host(executor_hosts)
        if resolved_executor_host is None:
            messages.warning(
                request,
                "Failed to resolve PMM server to an execution target; please select manually.",
            )
            default_executor_host = resolve_executor_host_for_service(
                executor_hosts, selected_service
            )
    else:
        resolved_executor_host = resolve_executor_host_for_service(
            executor_hosts, selected_service
        )
        if resolved_executor_host is None:
            messages.warning(
                request,
                "Could not map selected service to an execution target; please select manually.",
            )

    form_defaults = (
        get_pmm_form_defaults(
            resolved_executor_host,
            selected_service.name,
            selected_service.node.name if selected_service.node else None,
        )
        if collector_type == CollectorTypeEnum.PMM
        else None
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

    context |= {
        "is_pmm_script_available": has_pmm_script(selected_service.type),
        "selected_service": selected_service,
        "script": script,
        "script_execution_url": str(
            request.url_for("dipper_execute").include_query_params(
                service_id=selected_service.id, collector_type=collector_type.value
            )
        ),
        "executor_hosts": {resolved_executor_host}
        if resolved_executor_host
        else set(executor_hosts),
        "resolved_executor_host": resolved_executor_host,
        "default_executor_host": default_executor_host,
        "form_defaults": form_defaults,
        "history_tasks": history_tasks,
        "running_tasks": await tasks_api.get(
            f"/{script.execution_task_name}/history/",
            params={
                "snippet_filename": snippet_filename,
                "status": TaskHistoryStatusEnum.RUNNING,
            },
        ),
    }
    logger.debug("Context for Dipper index page: %s", context)

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
    script: DipperScriptWithMetaDep,
    service_id: int,
    collector_type: CollectorTypeEnum = CollectorTypeEnum.ENVIRONMENT,
) -> RedirectResponse:
    """Dispatch a dipper task for the selected service."""
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
