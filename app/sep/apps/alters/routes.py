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

"""Define routes for the alters plugin."""

import logging
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import FutureDatetime

from app.core.alerts.config import alert_settings
from app.core.pagination import fetch_all_dict_items
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.alters.deps import (
    alters_executor_matches_service_host,
    AltersIndexContext,
    AltersLegacyForm,
    AltersTask,
    build_alters_task,
    build_pre_checks_task_payload,
    cascade_create_alters_group,
    cascade_delete_alters_group,
    cascade_update_alters_group,
    DeletableAltersParent,
    extract_service_info,
    map_alters_legacy_form,
    parse_alters_task_args,
    UnprotectedAltersTask,
)
from app.sep.apps.framework.deprecation import DeprecatedJinja2Route
from app.sep.config import sep_settings
from app.sep.connectivity import maybe_check_connectivity
from app.sep.deps import (
    CheckConnectivityFlag,
    DefaultContext,
    ExecutorHostsCtx,
    get_chainable_tasks,
    HasNoConflictedRunningTasks,
    InventoryAPI,
    IsAuthenticated,
    IsCsrfValidated,
    TaskAPI,
)
from app.sep.utils.decorators import csrf_exempt
from app.sep.utils.jinja import syntax_highlight
from app.tasks.models import TaskHistoryStatusEnum

logger = logging.getLogger(__name__)
router = APIRouter(route_class=DeprecatedJinja2Route)
templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def alters_index(
    request: Request,
    context: AltersIndexContext,
) -> HTMLResponse:
    """Homepage of alters plugin."""
    return templates.TemplateResponse(
        request=request,
        name="alters/index.html.j2",
        context=context,
    )


@router.get("/table/{table_id}/details", dependencies=[IsAuthenticated])
@csrf_exempt
async def get_table_details(
    request: Request,  # noqa: ARG001
    table_id: int,
    inventory_api: InventoryAPI,
    syntax_highlight_style: str | None = None,
) -> JSONResponse:
    """Get table details including create statement and keys."""
    try:
        table = await inventory_api.get(f"/tables/{table_id}")
        create = table["create"]
        if syntax_highlight_style:
            create = syntax_highlight(create, "sql", style=syntax_highlight_style)
        return JSONResponse(
            {
                "id": table["id"],
                "name": table["name"],
                "create": create,
                "keys": table["keys"],
            }
        )
    except HTTPException:
        return JSONResponse(
            {"error": "Failed to fetch table details"},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post(
    "/", dependencies=[IsAuthenticated, IsCsrfValidated], response_class=HTMLResponse
)
async def alters_create(
    request: Request,
    form: Annotated[AltersLegacyForm, Form()],
    task_api: TaskAPI,
    inventory_api: InventoryAPI,
    *,
    check_connectivity: CheckConnectivityFlag,
) -> RedirectResponse:
    """Create the alters task group (parent, dry-run, and pre-checks tasks)."""
    logger.debug("Create alters tasks: %s", form.task_name)
    create = map_alters_legacy_form(form)
    parent_task = await build_alters_task(create, inventory_api)
    pre_checks_template = await build_pre_checks_task_payload(
        parent_task, task_api=task_api
    )
    await cascade_create_alters_group(
        task_api,
        parent_task,
        pre_checks_template,
        create,
    )

    await maybe_check_connectivity(
        request,
        task_api,
        parent_task.data.get("meta", {}),
        check_connectivity=check_connectivity,
    )

    task_path = request.url_for("alters_detail", task_name=parent_task.name)
    return RedirectResponse(
        task_path,
        status_code=status.HTTP_303_SEE_OTHER,
    )  # TODO: Custom redirect class  # noqa: TD002, TD003


@router.get("/{task_name}", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def alters_detail(
    task: AltersTask,
    request: Request,
    context: DefaultContext,
    tasks_api: TaskAPI,
    inventory_api: InventoryAPI,
    executor_hosts_ctx: ExecutorHostsCtx,
) -> HTMLResponse:
    """Retrieve alters task."""
    data = task.data

    # If the task has a parent, redirect to the parent task detail page
    if data.get("parent"):
        task_path = request.url_for("alters_detail", task_name=data["parent"])
        return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)

    meta = data["meta"]
    decoded_entities = task.anonymized_entities
    task_data = {
        "name": task.name,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "created_by": task.created_by,
        "last_updated_by": task.last_updated_by,
        "hostname": meta["target"],
        "table": f"{meta['_schema_name']}.{meta['_table_name']}",
        "cmd": f"{meta['command']} {meta['args']}",
        "meta": meta,
        "entities": {entity.name: entity.value for entity in decoded_entities},
        "delete_url": request.url_for("alters_delete", task_name=task.name),
        "dry_run_url": request.url_for(
            "alters_execute", task_name=task.name + "-dry-run"
        ),
        "pre_checks_url": request.url_for(
            "alters_execute", task_name=task.name + "-pre-checks"
        ),
        "alert_on_fail": task.alert_on_fail,
    }
    task_data.update(extract_service_info(meta))
    task_data["pre_checks_mysql_config_file"] = meta.get(
        "_pre_checks_mysql_config_file", "~/.my.cnf"
    )

    context["task"] = task_data
    # TODO(yan): Refactor/reuse like with get_tasks_context  # noqa: TD003
    response = await tasks_api.get(f"/{task.name}/history/")
    context["history"] = response["items"]
    response = await tasks_api.get(f"/{task.name}-dry-run/history/")
    context["history_dry_run"] = response["items"]
    response = await tasks_api.get(f"/{task.name}-pre-checks/history/")
    context["history_pre_checks"] = response["items"]
    response = await tasks_api.get(
        f"/{task.name}/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
    )
    context["running_tasks"] = response["items"]
    response = await tasks_api.get(
        f"/{task.name}-dry-run/history/",
        params={"status": TaskHistoryStatusEnum.RUNNING},
    )
    context["running_tasks"] += response["items"]
    response = await tasks_api.get(
        f"/{task.name}-pre-checks/history/",
        params={"status": TaskHistoryStatusEnum.RUNNING},
    )
    context["running_tasks"] += response["items"]
    context["stats"] = await tasks_api.get(f"/stats/{task.name}")

    task_data.update(parse_alters_task_args(meta))

    try:
        services = await fetch_all_dict_items(
            lambda pagination: inventory_api.get(
                "/services/",
                params={
                    "service_type": ServiceTypeEnum.MYSQL,
                    **pagination.model_dump(),
                },
            )
        )
    except HTTPException as exc:
        services = []
        logger.warning("Failed to get services: %s", exc)

    context["executor_hosts"] = executor_hosts_ctx.with_host(
        task_data["hostname"]
    ).as_template_list()
    context["has_matching_executor"] = alters_executor_matches_service_host(
        meta, executor_hosts_ctx.hosts
    )
    context["services"] = services
    context["alert_on_fail_default"] = task_data["alert_on_fail"]
    context["alert_on_fail_available"] = bool(alert_settings.PROVIDERS)
    context["chainable_tasks"] = await get_chainable_tasks(
        tasks_api, task.owner, meta["target"], task.name
    )

    return templates.TemplateResponse(
        request=request,
        name="alters/details.html.j2",
        context=context,
    )


@router.post(
    "/{task_name}",
    dependencies=[IsAuthenticated, IsCsrfValidated, HasNoConflictedRunningTasks],
    response_class=RedirectResponse,
)
async def alters_execute(
    request: Request,
    task: AltersTask,
    tasks_api: TaskAPI,
    eta: Annotated[FutureDatetime | None, Form()] = None,
    chain_task_names: Annotated[list[str] | None, Form()] = None,
    chain_on_failure: Annotated[bool | None, Form()] = None,
) -> RedirectResponse:
    """Execute alters task."""
    await tasks_api.post(
        f"/execute/{task.name}",
        json={
            "eta": eta,
            "chain_task_names": chain_task_names,
            "chain_on_failure": chain_on_failure,
        },
    )
    parent_name = task.data.get("parent") or task.name
    task_path = request.url_for("alters_detail", task_name=parent_name)
    return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{task_name}/update",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def alters_update(
    request: Request,
    task: UnprotectedAltersTask,
    form: Annotated[AltersLegacyForm, Form()],
    tasks_api: TaskAPI,
    inventory_api: InventoryAPI,
) -> RedirectResponse:
    """Update the alters task group."""
    logger.debug("Updating alters task: %s", form.task_name)
    create = map_alters_legacy_form(form)
    updated_parent = await build_alters_task(create, inventory_api)
    pre_checks_template = await build_pre_checks_task_payload(
        updated_parent, task_api=tasks_api
    )
    result = await cascade_update_alters_group(
        tasks_api,
        task.name,
        updated_parent,
        pre_checks_template,
        create,
    )
    result.raise_if_failed(op="update")

    return RedirectResponse(
        request.url_for("alters_detail", task_name=updated_parent.name),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/{task_name}/delete",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def alters_delete(
    parent_task: DeletableAltersParent,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Delete the alters task group."""
    result = await cascade_delete_alters_group(tasks_api, parent_task.name)
    result.raise_if_failed(op="delete")
    return RedirectResponse("/alters", status_code=status.HTTP_303_SEE_OTHER)
