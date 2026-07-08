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

"""Define routes for the backups plugin."""

import logging
from typing import Annotated

import yaml
from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import FutureDatetime

from app.core.alerts.config import alert_settings
from app.core.pagination import fetch_all_dict_items
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.backup_pg.deps import (
    BackupGeneratedTask,
    BackupsIndexContext,
    BackupsTask,
    parse_backup_task_data,
)
from app.sep.apps.backup_pg.models import BackupType
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
from app.tasks.models import TaskHistoryStatusEnum

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES


@router.get(
    "/",
    dependencies=[IsAuthenticated],
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def pg_backups_index(
    request: Request,
    context: BackupsIndexContext,
) -> HTMLResponse:
    """Render the PG backups plugin index page.

    Deprecated in favour of the React ``backup_pg`` plugin; functional until Wave 3.
    """
    return templates.TemplateResponse(
        request=request,
        name="backup_pg/index.html.j2",
        context=context,
    )


@router.post(
    "/",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def pg_backups_create(
    request: Request,
    task: BackupGeneratedTask,
    task_api: TaskAPI,
    *,
    check_connectivity: CheckConnectivityFlag,
) -> RedirectResponse:
    """Create new backups task.

    Deprecated in favour of the React ``backup_pg`` plugin; functional until Wave 3.
    """
    logger.debug("Create backups task: %s", task)
    await task_api.post(
        "/",
        json=task.model_dump(),
    )
    await maybe_check_connectivity(
        request,
        task_api,
        task.data.get("meta", {}),
        check_connectivity=check_connectivity,
    )
    task_path = request.url_for("pg_backups_detail", task_name=task.name)
    return RedirectResponse(
        task_path,
        status_code=status.HTTP_303_SEE_OTHER,
    )  # TODO: Custom redirect class  # noqa: TD002, TD003


@router.get(
    "/{task_name}",
    dependencies=[IsAuthenticated],
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def pg_backups_detail(
    task: BackupsTask,
    request: Request,
    context: DefaultContext,
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    executor_hosts_ctx: ExecutorHostsCtx,
) -> HTMLResponse:
    """Retrieve backups task.

    Deprecated in favour of the React ``backup_pg`` plugin; functional until Wave 3.
    """
    data = task.data
    meta = data["meta"]
    decoded_entities = task.anonymized_entities
    task_config = yaml.safe_load(meta["config"])
    server_config = task_config["SERVER_LIST"][0]

    parsed_task_data = parse_backup_task_data(task.model_dump())

    task_data = {
        "name": task.name,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "hostname": meta["target"],
        "meta": meta,
        "host": server_config["HOST"],
        "port": server_config.get("PORT") or 3306,
        "backup_type": BackupType(server_config["BACKUP_TYPE"]).name,
        "entities": {entity.name: entity.value for entity in decoded_entities},
        "delete_url": request.url_for("pg_backups_delete", task_name=task.name),
        "config": task_config.get("ALL_SERVERS", {}),
        "is_edit_enabled": not task.protected,
        "is_edit_form_present": False,
        "alert_on_fail": task.alert_on_fail,
    }

    task_data.update(parsed_task_data)

    context["task"] = task_data
    response = await tasks_api.get(f"/{task.name}/history/")
    context["history"] = response["items"]
    response = await tasks_api.get(
        f"/{task.name}/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
    )
    context["running_tasks"] = response["items"]
    context["stats"] = await tasks_api.get(f"/stats/{task.name}")

    context["executor_hosts"] = executor_hosts_ctx.with_host(
        task_data["hostname"]
    ).as_template_list()

    try:
        context["services"] = await fetch_all_dict_items(
            lambda pagination: inventory_api.get(
                "/services/",
                params={
                    "service_type": ServiceTypeEnum.POSTGRESQL,
                    **pagination.model_dump(),
                },
            )
        )
    except HTTPException:
        context["services"] = []

    context["alert_on_fail_default"] = task.alert_on_fail
    context["alert_on_fail_available"] = bool(alert_settings.PROVIDERS)
    context["chainable_tasks"] = await get_chainable_tasks(
        tasks_api, task.owner, meta["target"], task.name
    )

    return templates.TemplateResponse(
        request=request,
        name="backup_pg/details.html.j2",
        context=context,
    )


@router.post(
    "/{task_name}",
    dependencies=[IsAuthenticated, IsCsrfValidated, HasNoConflictedRunningTasks],
    response_class=RedirectResponse,
    include_in_schema=False,
)
async def pg_backups_execute(
    request: Request,
    task: BackupsTask,
    tasks_api: TaskAPI,
    eta: Annotated[FutureDatetime | None, Form()] = None,
    chain_task_names: Annotated[list[str] | None, Form()] = None,
    chain_on_failure: Annotated[bool | None, Form()] = None,
) -> RedirectResponse:
    """Execute backups task.

    Deprecated in favour of the React ``backup_pg`` plugin; functional until Wave 3.
    """
    await tasks_api.post(
        f"/execute/{task.name}",
        json={
            "eta": eta,
            "chain_task_names": chain_task_names,
            "chain_on_failure": chain_on_failure,
        },
    )
    task_path = request.url_for("pg_backups_detail", task_name=task.name)
    return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{task_name}/delete",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
    include_in_schema=False,
)
async def pg_backups_delete(
    task: BackupsTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Delete backups task.

    Deprecated in favour of the React ``backup_pg`` plugin; functional until Wave 3.

    :param task: The PG backups task to delete, resolved by the
        ``BackupsTask`` dependency from the ``task_name`` path param.
    :type task: BackupsTask
    :param tasks_api: The tasks-API client used to issue the delete call.
    :type tasks_api: TaskAPI
    :return: HTTP 303 redirect to the plugin index.
    :rtype: RedirectResponse
    """
    await tasks_api.delete(f"/{task.name}")
    return RedirectResponse("/backup_pg", status_code=status.HTTP_303_SEE_OTHER)
