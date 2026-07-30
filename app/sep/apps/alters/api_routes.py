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

"""Define the custom JSON API routes for the Alters plugin.

The declarative :class:`~app.sep.apps.framework.apps.TaskExecutionApp` in
``app.py`` derives the ``GET /schema`` and paginated ``roots_only`` list routes;
this router carries the per-app routes it keeps custom — the satellite-resolving
detail, the cascade create/update/delete, and the execute route — mounted as its
``extra_routes``. The framework's derived detail route is suppressed
(``capabilities.detail=False``) so the custom ``GET /{task_name}`` here wins.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi import status as http_status

from app.sep.apps.alters.deps import (
    AltersCascadePlan,
    AltersTask,
    build_alters_api_task_response,
    build_alters_task,
    build_pre_checks_task_payload,
    cascade_delete_alters_group,
    cascade_update_alters_group,
    DeletableAltersParent,
    EditableAltersParent,
    ensure_alters_group_update_preserves_names,
    get_alters_task,
    render_alters_create,
    resolve_alters_parent_task,
)
from app.sep.apps.alters.models import (
    AltersCreate,
    AltersTaskResponse,
    AltersTaskResponseCreate,
    AltersTaskResponseUpdate,
)
from app.sep.apps.framework import (
    get_task_latest_history,
    maybe_record_connectivity_warning,
)
from app.sep.apps.framework.api import (
    derive_cascade_create_route,
    derive_execute_route,
)
from app.sep.apps.framework.spec import stamp_form_input
from app.sep.deps import (
    get_username_mapping,
    InventoryAPI,
    TaskAPI,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{task_name}")
async def alters_api_detail(
    task_name: str,
    tasks_api: TaskAPI,
) -> AltersTaskResponse:
    """Retrieve a single parent alters task."""
    parent_task = await resolve_alters_parent_task(task_name, tasks_api)
    latest = await get_task_latest_history(tasks_api, parent_task.name)
    username_mapping = await get_username_mapping()
    return build_alters_api_task_response(
        parent_task,
        status=latest.status,
        last_executed_at=latest.finished_at,
        username_mapping=username_mapping,
    )


derive_cascade_create_route(
    router,
    name="alters_api_create",
    description="Create an alters task group from a JSON payload request body.",
    create_plan=AltersCascadePlan,
    get_task=get_alters_task,
    response_builder=render_alters_create,
    response_model=AltersTaskResponseCreate,
    connectivity_check=True,
)


@router.put("/{task_name}")
async def alters_api_update(
    parent_task: EditableAltersParent,
    body: AltersCreate,
    tasks_api: TaskAPI,
    inventory_api: InventoryAPI,
    *,
    check_connectivity: Annotated[bool, Query()] = True,
) -> AltersTaskResponseUpdate:
    """Update an alters task group from a JSON payload request body.

    :param check_connectivity: Whether to verify the target database is
        reachable after the update. Defaults to ``True``; pass
        ``check_connectivity=false`` to opt out. Note that the form flow
        defaults to ``False`` (HTML checkbox semantics); this asymmetry is
        intentional.
    :type check_connectivity: bool
    """
    ensure_alters_group_update_preserves_names(parent_task.name, body.task_name)

    logger.debug("Update alters task group (JSON path): %s", parent_task.name)
    updated_parent = await build_alters_task(body, inventory_api)
    pre_checks_template = await build_pre_checks_task_payload(
        updated_parent, task_api=tasks_api
    )
    stamp_form_input(updated_parent, body)
    result = await cascade_update_alters_group(
        tasks_api,
        parent_task.name,
        updated_parent,
        pre_checks_template,
        body,
    )
    result.raise_if_failed(op="update")

    updated_task = await get_alters_task(updated_parent.name, tasks_api)
    latest = await get_task_latest_history(tasks_api, updated_task.name)
    username_mapping = await get_username_mapping()
    connectivity_warning = await maybe_record_connectivity_warning(
        tasks_api,
        updated_task.data.get("meta", {}),
        check_connectivity=check_connectivity,
    )
    return build_alters_api_task_response(
        updated_task,
        status=latest.status,
        last_executed_at=latest.finished_at,
        response_model=AltersTaskResponseUpdate,
        connectivity_warning=connectivity_warning,
        username_mapping=username_mapping,
    )


derive_execute_route(
    router,
    name="alters_api_execute",
    description="Execute an alters task (parent, dry-run, or pre-checks).",
    task_dep=AltersTask,
)


@router.delete("/{task_name}", status_code=http_status.HTTP_204_NO_CONTENT)
async def alters_api_delete(
    parent_task: DeletableAltersParent,
    tasks_api: TaskAPI,
) -> None:
    """Delete an alters task group."""
    result = await cascade_delete_alters_group(tasks_api, parent_task.name)
    result.raise_if_failed(op="delete")
