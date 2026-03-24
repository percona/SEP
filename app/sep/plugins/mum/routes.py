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
from uuid import uuid4

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
from app.sep.plugins.mum.task import (
    MUM_TASK_NAME_BY_ACTION,
    get_mum_task as get_mum_task_spec,
)

logger = logging.getLogger(__name__)

router = APIRouter()

templates = sep_settings.TEMPLATES

DEFAULT_MUM_ACTION = "list_users"


def _redact_config(config: dict[str, Any] | None) -> dict[str, Any] | None:
    if config is None:
        return None
    redacted = dict(config)
    if "password" in redacted:
        redacted["password"] = "***"
    return redacted


async def _create_nomad_config_variable(
    tasks_api: TaskAPI,
    *,
    config: dict[str, Any],
    job_prefix: str,
    namespace: str | None = None,
) -> str:
    path = f"sep/runtime/mum/{job_prefix}"
    payload: dict[str, Any] = {
        "path": path,
        "data": {"config": dict(config)},
    }
    if namespace:
        payload["namespace"] = namespace
    try:
        await tasks_api.post("/nomad/variables/", json=payload)
    except HTTPException as exc:  # type: ignore[name-defined]
        logger.error(
            "Failed to create Nomad variable for MUM task '%s': %s (status: %s)",
            job_prefix,
            exc.detail,
            exc.status_code,
        )
        raise
    return path


async def _delete_nomad_config_variable(
    tasks_api: TaskAPI,
    *,
    path: str,
    namespace: str | None = None,
) -> None:
    """Best-effort deletion for temporary Nomad variable paths."""
    try:
        await tasks_api.delete(
            f"/nomad/variables/{path}",
            params={"namespace": namespace} if namespace else None,
        )
    except HTTPException as exc:  # type: ignore[name-defined]
        logger.warning(
            "Failed to delete Nomad variable '%s' after dispatch error: %s (status: %s)",
            path,
            exc.detail,
            exc.status_code,
        )


def _resolve_mum_task_name(action: str | None) -> str:
    """Resolve a MUM task name for an action."""
    if action is None:
        return MUM_TASK_NAME_BY_ACTION[DEFAULT_MUM_ACTION]
    if action not in MUM_TASK_NAME_BY_ACTION:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported MUM action '{action}'.",
        )
    return MUM_TASK_NAME_BY_ACTION[action]


async def _ensure_mum_task(tasks_api: TaskAPI, task_name: str) -> dict[str, Any]:
    """Ensure a MUM task exists, creating it if necessary."""
    # First try to get the task via API
    try:
        task = await tasks_api.get(f"/{task_name}")
        logger.debug("MUM task '%s' already exists", task_name)
        return task
    except HTTPException as exc:  # type: ignore[name-defined]
        if exc.status_code != status.HTTP_404_NOT_FOUND:
            logger.error(
                "Failed to get MUM task '%s': %s (status: %s)",
                task_name,
                exc.detail,
                exc.status_code,
            )
            raise

    # Task doesn't exist, create it using the plugin's task definition
    logger.info(
        "MUM task '%s' not found, creating it from plugin definition", task_name
    )
    task_spec = get_mum_task_spec(task_name)

    # Convert Task model to dict for API
    task_data = {
        "name": task_spec.name,
        "backend": task_spec.backend.value,
        "owner": task_spec.owner.value,
        "protected": task_spec.protected,
        "alert_on_fail": task_spec.alert_on_fail,
        "data": task_spec.data,
    }

    try:
        created = await tasks_api.post("/", json=task_data)
        logger.info(
            "Successfully created MUM task '%s' (ID: %s)",
            task_name,
            created.get("id"),
        )
        return created
    except HTTPException as exc:  # type: ignore[name-defined]
        logger.error(
            "Failed to create MUM task '%s': %s (status: %s)",
            task_name,
            exc.detail,
            exc.status_code,
        )
        raise


async def _execute_mum_task(
    tasks_api: TaskAPI,
    *,
    task_name: str,
    target: str,
    config: dict[str, Any] | None = None,
    config_nomad_variable: str | None = None,
    config_nomad_variable_namespace: str | None = None,
    meta: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Dispatch a MUM task with the provided config."""
    logger.debug("Executing MUM task '%s' for target '%s'", task_name, target)
    default_task = await _ensure_mum_task(tasks_api, task_name)

    execution_meta = {"target": target}
    if meta:
        execution_meta.update(meta)
    if config is not None and not config_nomad_variable:
        execution_meta["config"] = json.dumps(config)
    if config_nomad_variable:
        execution_meta["config_nomad_variable"] = config_nomad_variable
        if config_nomad_variable_namespace:
            execution_meta["config_nomad_variable_namespace"] = (
                config_nomad_variable_namespace
            )
        logger.debug(
            "Executing task '%s' on target '%s' with config from Nomad variable '%s'",
            task_name,
            target,
            config_nomad_variable,
        )
    else:
        logger.debug(
            "Executing task '%s' on target '%s' with config: %s",
            task_name,
            target,
            _redact_config(config),
        )
    try:
        history = await tasks_api.post(
            f"/execute/{task_name}", json={"meta": execution_meta}
        )
        logger.info(
            "Successfully executed task '%s' (history ID: %s)",
            task_name,
            history.get("id"),
        )
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
        name="mum/index.html.j2",
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
        default_task_name = _resolve_mum_task_name(None)
        default_task = await _ensure_mum_task(tasks_api, default_task_name)
    except HTTPException as exc:  # type: ignore[name-defined]
        logger.warning("Failed to ensure MUM task: %s", exc)
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
    """List MongoDB users by executing the MUM list task.
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
        task_name = _resolve_mum_task_name(config_obj["action"])
        default_task, history = await _execute_mum_task(
            tasks_api,
            task_name=task_name,
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
        job_token = uuid4().hex
        job_prefix = f"mum-{job_token}"
        config_nomad_variable = await _create_nomad_config_variable(
            tasks_api,
            config=config_obj,
            job_prefix=job_prefix,
        )
        config_obj.pop("password", None)
        task_name = _resolve_mum_task_name(config_obj["action"])
        try:
            default_task, history = await _execute_mum_task(
                tasks_api,
                task_name=task_name,
                target=target,
                config=None,
                config_nomad_variable=config_nomad_variable,
                meta={"_job_id_prefix": job_prefix},
            )
        except Exception:
            await _delete_nomad_config_variable(tasks_api, path=config_nomad_variable)
            raise
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

        config_nomad_variable = None
        exec_meta: dict[str, Any] | None = None
        if "password" in config_obj:
            job_token = uuid4().hex
            job_prefix = f"mum-{job_token}"
            config_nomad_variable = await _create_nomad_config_variable(
                tasks_api,
                config=config_obj,
                job_prefix=job_prefix,
            )
            exec_meta = {"_job_id_prefix": job_prefix}
            config_obj.pop("password", None)

        task_name = _resolve_mum_task_name(config_obj["action"])
        try:
            default_task, history = await _execute_mum_task(
                tasks_api,
                task_name=task_name,
                target=target,
                config=None if config_nomad_variable else config_obj,
                config_nomad_variable=config_nomad_variable,
                meta=exec_meta,
            )
        except Exception:
            if config_nomad_variable:
                await _delete_nomad_config_variable(
                    tasks_api, path=config_nomad_variable
                )
            raise
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
        task_name = _resolve_mum_task_name(config_obj["action"])
        default_task, history = await _execute_mum_task(
            tasks_api,
            task_name=task_name,
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
    action: str | None = None,
) -> JSONResponse:
    """Get a MUM task by action, defaulting to list-users."""
    try:
        task_name = _resolve_mum_task_name(action)
        task = await _ensure_mum_task(tasks_api, task_name)
        return JSONResponse(content=task, status_code=status.HTTP_200_OK)
    except HTTPException as exc:  # type: ignore[name-defined]
        return JSONResponse(content={"detail": exc.detail}, status_code=exc.status_code)