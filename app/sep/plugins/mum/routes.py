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

import logging
import json
from typing import Any
from pathlib import Path

from fastapi import APIRouter, Request, status, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse


from app.sep.config import sep_settings
from app.sep.deps import (
    DefaultContext,
    TaskAPI,
    IsAuthenticated,
    IsCsrfValidated,
    InventoryAPI,
)
from app.sep.plugins.mum.models import MUMTaskCreateRequest

from app.tasks.models import TaskBackendEnum, TaskOwner
from app.inventory.models import ServiceTypeEnum

logger = logging.getLogger(__name__)

router = APIRouter()

templates = sep_settings.TEMPLATES


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
    return JSONResponse(
        content={
            "executor_hosts": list(executor_hosts.values()),
            "services": services,
        }
    )


@router.post(
    "/ui/execute/{task_name}",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=JSONResponse,
)
async def mum_execute_task(
    task_name: str,
    body: dict[str, Any],
    tasks_api: TaskAPI,
) -> JSONResponse:
    """Dispatch an existing MUM task by name to a selected executor host.
    Body must contain: {"target": "<executor-host-name>"}
    """
    target = body.get("target")
    if not target:
        return JSONResponse(
            content={"detail": "'target' is required"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    try:
        history = await tasks_api.post(
            f"/execute/{task_name}", json={"meta": {"target": target}}
        )
        return JSONResponse(content=history, status_code=status.HTTP_201_CREATED)
    except HTTPException as exc:  # type: ignore[name-defined]
        return JSONResponse(content={"detail": exc.detail}, status_code=exc.status_code)

@router.post(
    "/ui/create-user",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=JSONResponse,
)
async def mum_create_user(
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
        payload_path = Path(__file__).parent / "mum_payload"
        dynamic_name = f"mum-create-user-{int(__import__('time').time())}"
        config_obj: dict[str, Any] = {
            "action": "create_user",
            "username": username,
            "password": password,
            "roles": roles,
            "db": db_name,
        }
        task_data: dict[str, Any] = {
            "name": dynamic_name,
            "backend": TaskBackendEnum.PROXY,
            "owner": TaskOwner.MUM,
            "alert_on_fail": False,
            "data": {
                "task": "run-python",
                "meta": {
                    "config": json.dumps(config_obj),
                    "requirements": "PyMongo",
                },
                "payload": f"file://{payload_path}",
            },
        }
        created_task = await tasks_api.post("/", json=task_data)
        history = await tasks_api.post(
            f"/execute/{dynamic_name}", json={"meta": {"target": target}}
        )
        return JSONResponse(
            content={"task": created_task, "history": history},
            status_code=status.HTTP_201_CREATED,
        )
    except HTTPException as exc:  # type: ignore[name-defined]
        return JSONResponse(content={"detail": exc.detail}, status_code=exc.status_code)


@router.post(
    "/ui/update-user",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=JSONResponse,
)
async def mum_update_user(
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
        payload_path = Path(__file__).parent / "mum_payload"
        dynamic_name = f"mum-update-user-{int(__import__('time').time())}"
        config_obj: dict[str, Any] = {
            "action": "update_user",
            "username": username,
            "db": db_name,
        }
        if isinstance(password, str) and password:
            config_obj["password"] = password
        if roles is not None:
            config_obj["roles"] = roles

        task_data: dict[str, Any] = {
            "name": dynamic_name,
            "backend": TaskBackendEnum.PROXY,
            "owner": TaskOwner.MUM,
            "alert_on_fail": False,
            "data": {
                "task": "run-python",
                "meta": {
                    "config": json.dumps(config_obj),
                    "requirements": "PyMongo",
                },
                "payload": f"file://{payload_path}",
            },
        }
        created_task = await tasks_api.post("/", json=task_data)
        history = await tasks_api.post(
            f"/execute/{dynamic_name}", json={"meta": {"target": target}}
        )
        return JSONResponse(
            content={"task": created_task, "history": history},
            status_code=status.HTTP_201_CREATED,
        )
    except HTTPException as exc:  # type: ignore[name-defined]
        return JSONResponse(content={"detail": exc.detail}, status_code=exc.status_code)


@router.post(
    "/ui/delete-user",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=JSONResponse,
)
async def mum_delete_user(
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
        payload_path = Path(__file__).parent / "mum_payload"
        dynamic_name = f"mum-delete-user-{int(__import__('time').time())}"
        config_obj: dict[str, Any] = {
            "action": "delete_user",
            "username": username,
            "db": db_name,
        }
        task_data: dict[str, Any] = {
            "name": dynamic_name,
            "backend": TaskBackendEnum.PROXY,
            "owner": TaskOwner.MUM,
            "alert_on_fail": False,
            "data": {
                "task": "run-python",
                "meta": {
                    "config": json.dumps(config_obj),
                    "requirements": "PyMongo",
                },
                "payload": f"file://{payload_path}",
            },
        }
        created_task = await tasks_api.post("/", json=task_data)
        history = await tasks_api.post(
            f"/execute/{dynamic_name}", json={"meta": {"target": target}}
        )
        return JSONResponse(
            content={"task": created_task, "history": history},
            status_code=status.HTTP_201_CREATED,
        )
    except HTTPException as exc:  # type: ignore[name-defined]
        return JSONResponse(content={"detail": exc.detail}, status_code=exc.status_code)

@router.post(
    "/ui/usertask",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=JSONResponse,
)
async def create_mum_task(
    create_task_json: MUMTaskCreateRequest,
    tasks_api: TaskAPI,
) -> JSONResponse:
    """Create a general MUM task using the run-python template.
    Creates a PROXY task that references the protected `run-python` task. The created
    task can later be executed (dispatched) with a target selected in the UI.
    Returns the created task (including its ID) as JSON.
    """
    try:
        payload_path = Path(__file__).parent / "mum_payload"
        # Make task name dynamic to act like a short-lived session name
        dynamic_name = f"{create_task_json.name}-{int(__import__('time').time())}"
        task_data: dict[str, Any] = {
            "name": dynamic_name,
            "backend": TaskBackendEnum.PROXY,
            "owner": TaskOwner.MUM,
            "alert_on_fail": create_task_json.alert_on_fail,
            "data": {
                "task": "run-python",
                "meta": {
                    # Forward the user payload as script config (opaque to backend)
                    "config": create_task_json.payload,
                    # Default requirements for MUM scripts
                    "requirements": "PyMongo",
                    # `target` will be provided when executing the task from UI
                },
                # Use the bundled Python payload for MUM as the script body
                "payload": f"file://{payload_path}",
            },
        }

        created_task = await tasks_api.post("/", json=task_data)
        # Return the created Task so the frontend can store id/name for later execution
        return JSONResponse(content=created_task, status_code=status.HTTP_201_CREATED)
    except HTTPException as exc:  # type: ignore[name-defined]
        return JSONResponse(content={"detail": exc.detail}, status_code=exc.status_code)