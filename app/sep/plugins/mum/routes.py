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
from pathlib import Path
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
from app.tasks.models import TaskBackendEnum, TaskOwner

logger = logging.getLogger(__name__)

router = APIRouter()

templates = sep_settings.TEMPLATES
PAYLOAD_PATH = Path(__file__).parent / "mum_payload"
PYTHON_REQUIREMENTS = "PyMongo"
DEFAULT_TASK_NAME = "mum-users"


def _build_default_task_spec() -> dict[str, Any]:
    """Return the canonical specification for the default MUM task."""
    return {
        "name": DEFAULT_TASK_NAME,
        "backend": TaskBackendEnum.PROXY,
        "owner": TaskOwner.MUM,
        "protected": True,
        "alert_on_fail": False,
        "data": {
            "task": "run-python",
            "meta": {
                "requirements": PYTHON_REQUIREMENTS,
            },
            "payload": f"file://{PAYLOAD_PATH}",
        },
    }


def _task_matches_spec(task: dict[str, Any], spec: dict[str, Any]) -> bool:
    """Check whether the stored task matches our expected definition."""
    data = task.get("data") or {}
    spec_data = spec["data"]
    meta = data.get("meta") or {}
    spec_meta = spec_data.get("meta") or {}
    return (
        task.get("backend") == spec["backend"]
        and task.get("owner") == spec["owner"]
        and task.get("alert_on_fail") == spec["alert_on_fail"]
        and task.get("protected") == spec.get("protected", False)
        and data.get("task") == spec_data["task"]
        and data.get("payload") == spec_data["payload"]
        and meta.get("requirements") == spec_meta.get("requirements")
    )


async def _ensure_default_task(tasks_api: TaskAPI) -> dict[str, Any]:
    """Retrieve or create the default MUM task."""
    spec = _build_default_task_spec()
    try:
        existing = await tasks_api.get(f"/{DEFAULT_TASK_NAME}")
    except HTTPException as exc:  # type: ignore[name-defined]
        if exc.status_code != status.HTTP_404_NOT_FOUND:
            raise
        # Task doesn't exist yet - this is expected, we'll create it below
        logger.debug("Default MUM task '%s' not found, will create it", DEFAULT_TASK_NAME)
    else:
        if _task_matches_spec(existing, spec):
            return existing
        updated = await tasks_api.put(f"/{DEFAULT_TASK_NAME}", json=spec)
        return updated
    try:
        created = await tasks_api.post("/", json=spec)
        logger.info("Created default MUM task '%s'", DEFAULT_TASK_NAME)
        return created
    except HTTPException as exc:  # type: ignore[name-defined]
        if exc.status_code != status.HTTP_409_CONFLICT:
            raise
        # Task was created concurrently; fetch and reconcile instead of failing.
        logger.debug("Default MUM task '%s' was created concurrently, fetching it", DEFAULT_TASK_NAME)
        existing = await tasks_api.get(f"/{DEFAULT_TASK_NAME}")
        if _task_matches_spec(existing, spec):
            return existing
        return await tasks_api.put(f"/{DEFAULT_TASK_NAME}", json=spec)


async def _execute_default_task(
    tasks_api: TaskAPI, *, target: str, config: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Dispatch the default MUM task with the provided config.
    
    Args:
        tasks_api: The TaskAPI instance
        target: Executor host name
        config: Configuration dict that will be JSON-stringified and passed as meta.config
        
    Returns:
        Tuple of (task, history) dicts
    """
    default_task = await _ensure_default_task(tasks_api)
    execution_meta = {
        "target": target,
        "config": json.dumps(config),
    }
    history = await tasks_api.post(
        f"/execute/{default_task['name']}", json={"meta": execution_meta}
    )
    return default_task, history


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
        default_task = await _ensure_default_task(tasks_api)
    except HTTPException as exc:  # type: ignore[name-defined]
        logger.warning("Failed to ensure default MUM task: %s", exc)
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
    """Get or create the default MUM task.
    Returns the default MUM task (including its ID) as JSON.
    All MUM operations use this single task with different config arguments.
    """
    try:
        default_task = await _ensure_default_task(tasks_api)
        return JSONResponse(content=default_task, status_code=status.HTTP_200_OK)
    except HTTPException as exc:  # type: ignore[name-defined]
        return JSONResponse(content={"detail": exc.detail}, status_code=exc.status_code)