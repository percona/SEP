# Copyright (C) 2025 Percona LLC
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

"""Define routes for the MUM Plugin."""

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse

from app.inventory.models import ServiceTypeEnum
from app.sep.config import sep_settings
from app.sep.deps import (
    DefaultContext,
    InventoryAPI,
    IsAuthenticated,
    TaskAPI,
)
from app.sep.utils.decorators import csrf_exempt

logger = logging.getLogger(__name__)

router = APIRouter()

templates = sep_settings.TEMPLATES
DEFAULT_TASK_NAME = "mum-users"


async def _get_default_task(tasks_api: TaskAPI) -> dict[str, Any]:
    """Retrieve the default MUM task. The task must already exist and be pre-configured.
    
    Raises HTTPException if the task is not found.
    """
    try:
        task = await tasks_api.get(f"/{DEFAULT_TASK_NAME}")
        logger.debug("Retrieved default MUM task '%s'", DEFAULT_TASK_NAME)
        return task
    except HTTPException as exc:  # type: ignore[name-defined]
        logger.error("Default MUM task '%s' not found (status: %s): %s", 
                    DEFAULT_TASK_NAME, exc.status_code, exc.detail)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MUM task '{DEFAULT_TASK_NAME}' not found. The task must be pre-configured and available."
        ) from exc


async def _execute_default_task(
    tasks_api: TaskAPI, *, target: str, config: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Dispatch the default MUM task with the provided config.
    
    The task must already exist and be pre-configured.
    
    Args:
        tasks_api: The TaskAPI instance
        target: Executor host name
        config: Configuration dict that will be JSON-stringified and passed as meta.config
        
    Returns:
        Tuple of (task, history) dicts
    """
    logger.debug("Executing default MUM task for target '%s'", target)
    default_task = await _get_default_task(tasks_api)
    task_name = default_task["name"]
    
    execution_meta = {
        "target": target,
        "config": json.dumps(config),
    }
    logger.debug("Executing task '%s' on target '%s' with config: %s", task_name, target, config)
    try:
        history = await tasks_api.post(
            f"/execute/{task_name}", json={"meta": execution_meta}
        )
        logger.info("Successfully executed task '%s' (history ID: %s)", task_name, history.get("id"))
        return default_task, history
    except HTTPException as exc:  # type: ignore[name-defined]
        logger.error("Failed to execute task '%s': %s (status: %s)", task_name, exc.detail, exc.status_code)
        raise


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def mum_index(
    request: Request,
    context: DefaultContext,
) -> HTMLResponse:
    """Homepage of MUM Plugin."""
    return templates.TemplateResponse(
        request=request,
        name="mum/index.html",
        context=context,
    )


@router.get("/ui/options", dependencies=[IsAuthenticated], response_class=JSONResponse)
async def mum_options(
    request: Request,
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
) -> JSONResponse:
    """Return executor hosts and MongoDB services for MUM UI."""
    services = await inventory_api.get(
        "/services/", params={"service_type": ServiceTypeEnum.MONGODB}
    )
    # Optional: attach schemas like server-side templates do
    for service in services:
        try:
            service["schemas"] = await inventory_api.get(
                f"/services/{service['id']}/schemas/"
            )
        except Exception:
            service["schemas"] = []
    try:
        executor_hosts = await tasks_api.get("/hosts/")
    except HTTPException:
        executor_hosts = {}
    try:
        default_task = await _get_default_task(tasks_api)
    except HTTPException as exc:  # type: ignore[name-defined]
        logger.warning("Failed to get default MUM task: %s", exc)
        default_task = None
    return JSONResponse(
        content={
            "executor_hosts": [
                {"name": name, "address": address}
                for name, address in executor_hosts.items()
            ],
            "services": services,
            "default_task": default_task,
        }
    )


@router.post(
    "/ui/list-users",
    dependencies=[IsAuthenticated],
    response_class=JSONResponse,
)
@csrf_exempt
async def mum_list_users(
    request: Request,  # noqa: ARG001
    body: dict[str, Any],
    tasks_api: TaskAPI,
) -> JSONResponse:
    """List MongoDB users by executing the default MUM task.
    Expects JSON body with:
    - target: executor host name (required)
    """
    logger.debug("Received list-users request with body: %s", body)
    target = body.get("target")
    if not target:
        return JSONResponse(
            content={"detail": "'target' is required"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        config_obj: dict[str, Any] = {
            "action": "list_users",
        }
        logger.debug("Listing users for target '%s'", target)
        default_task, history = await _execute_default_task(
            tasks_api,
            target=target,
            config=config_obj,
        )
        logger.info("Successfully executed list_users for target '%s' (history ID: %s)", target, history.get("id"))
        return JSONResponse(
            content={"task": default_task, "history": history},
            status_code=status.HTTP_201_CREATED,
        )
    except HTTPException as exc:  # type: ignore[name-defined]
        logger.error("Failed to list users for target '%s': %s (status: %s)", target, exc.detail, exc.status_code)
        return JSONResponse(content={"detail": exc.detail}, status_code=exc.status_code)
    except Exception as exc:
        logger.exception("Unexpected error while listing users for target '%s'", target)
        return JSONResponse(
            content={"detail": f"Internal error: {str(exc)}"},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

@router.post(
    "/ui/create-user",
    dependencies=[IsAuthenticated],
    response_class=JSONResponse,
)
@csrf_exempt
async def mum_create_user(
    request: Request,  # noqa: ARG001
    body: dict[str, Any],
    tasks_api: TaskAPI,
) -> JSONResponse:
    """Create and execute a one-off task to create a MongoDB user.
    Expects JSON body with:
    - target: executor host name (required)
    - username: MongoDB username (required)
    - password: MongoDB password (required)
    - roles: list of builtin roles or role dicts (optional)
    - db: database for role scope (optional, defaults to 'admin')
    """
    target = body.get("target")
    if not target:
        return JSONResponse(
            content={"detail": "'target' is required"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    username = body.get("username")
    password = body.get("password")
    roles = body.get("roles", [])
    db_name = body.get("db") or "admin"
    if not username or not password:
        return JSONResponse(
            content={"detail": "'username' and 'password' are required"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        config_obj: dict[str, Any] = {
            "action": "create_user",
            "username": username,
            "password": password,
            "roles": roles,
            "db": db_name,
        }
        default_task, history = await _execute_default_task(
            tasks_api,
            target=target,
            config=config_obj,
        )
        return JSONResponse(
            content={"task": default_task, "history": history},
            status_code=status.HTTP_201_CREATED,
        )
    except HTTPException as exc:  # type: ignore[name-defined]
        return JSONResponse(content={"detail": exc.detail}, status_code=exc.status_code)


@router.post(
    "/ui/update-user",
    dependencies=[IsAuthenticated],
    response_class=JSONResponse,
)
@csrf_exempt
async def mum_update_user(
    request: Request,  # noqa: ARG001
    body: dict[str, Any],
    tasks_api: TaskAPI,
) -> JSONResponse:
    """Create and execute a one-off task to update a MongoDB user.
    Expects JSON body with:
    - target: executor host name (required)
    - username: MongoDB username (required)
    - password: MongoDB password (optional)
    - roles: list of builtin roles or role dicts (optional)
    - db: database for role scope (optional, defaults to 'admin')
    """
    target = body.get("target")
    if not target:
        return JSONResponse(
            content={"detail": "'target' is required"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    username = body.get("username")
    if not username:
        return JSONResponse(
            content={"detail": "'username' is required"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    db_name = body.get("db") or "admin"
    password = body.get("password")
    roles = body.get("roles")

    try:
        config_obj: dict[str, Any] = {
            "action": "update_user",
            "username": username,
            "db": db_name,
        }
        if isinstance(password, str) and password:
            config_obj["password"] = password
        if roles is not None:
            config_obj["roles"] = roles

        default_task, history = await _execute_default_task(
            tasks_api,
            target=target,
            config=config_obj,
        )
        return JSONResponse(
            content={"task": default_task, "history": history},
            status_code=status.HTTP_201_CREATED,
        )
    except HTTPException as exc:  # type: ignore[name-defined]
        return JSONResponse(content={"detail": exc.detail}, status_code=exc.status_code)


@router.post(
    "/ui/delete-user",
    dependencies=[IsAuthenticated],
    response_class=JSONResponse,
)
@csrf_exempt
async def mum_delete_user(
    request: Request,  # noqa: ARG001
    body: dict[str, Any],
    tasks_api: TaskAPI,
) -> JSONResponse:
    """Create and execute a one-off task to delete a MongoDB user.
    Expects JSON body with:
    - target: executor host name (required)
    - username: MongoDB username (required)
    - db: database where the user exists (optional, defaults to 'admin')
    """
    target = body.get("target")
    if not target:
        return JSONResponse(
            content={"detail": "'target' is required"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    username = body.get("username")
    if not username:
        return JSONResponse(
            content={"detail": "'username' is required"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    db_name = body.get("db") or "admin"

    try:
        config_obj: dict[str, Any] = {
            "action": "delete_user",
            "username": username,
            "db": db_name,
        }
        default_task, history = await _execute_default_task(
            tasks_api,
            target=target,
            config=config_obj,
        )
        return JSONResponse(
            content={"task": default_task, "history": history},
            status_code=status.HTTP_201_CREATED,
        )
    except HTTPException as exc:  # type: ignore[name-defined]
        return JSONResponse(content={"detail": exc.detail}, status_code=exc.status_code)

@router.post(
    "/ui/usertask",
    dependencies=[IsAuthenticated],
    response_class=JSONResponse,
)
@csrf_exempt
async def get_mum_task(
    request: Request,  # noqa: ARG001
    tasks_api: TaskAPI,
) -> JSONResponse:
    """Get the default MUM task.
    Returns the default MUM task (including its ID) as JSON.
    The task must be pre-configured and available.
    All MUM operations use this single task with different config arguments.
    """
    try:
        default_task = await _get_default_task(tasks_api)
        return JSONResponse(content=default_task, status_code=status.HTTP_200_OK)
    except HTTPException as exc:  # type: ignore[name-defined]
        return JSONResponse(content={"detail": exc.detail}, status_code=exc.status_code)