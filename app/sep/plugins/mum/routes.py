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

import asyncio
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
        "backend": TaskBackendEnum.PROXY.value,  # Convert enum to string
        "owner": TaskOwner.MUM.value,  # Convert enum to string
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
    # Compare backend and owner as strings (they may come as enums or strings from API)
    task_backend = str(task.get("backend", ""))
    spec_backend = str(spec["backend"])
    task_owner = str(task.get("owner", ""))
    spec_owner = str(spec["owner"])
    return (
        task_backend == spec_backend
        and task_owner == spec_owner
        and task.get("alert_on_fail") == spec["alert_on_fail"]
        and task.get("protected") == spec.get("protected", False)
        and data.get("task") == spec_data["task"]
        and data.get("payload") == spec_data["payload"]
        and meta.get("requirements") == spec_meta.get("requirements")
    )


async def _ensure_default_task(tasks_api: TaskAPI) -> dict[str, Any]:
    """Retrieve or create the default MUM task."""
    spec = _build_default_task_spec()
    logger.debug("Ensuring default MUM task '%s' exists", DEFAULT_TASK_NAME)
    try:
        existing = await tasks_api.get(f"/{DEFAULT_TASK_NAME}")
        logger.debug("Task '%s' exists, checking if it matches spec", DEFAULT_TASK_NAME)
        if _task_matches_spec(existing, spec):
            logger.debug("Default MUM task '%s' exists and matches spec", DEFAULT_TASK_NAME)
            return existing
        logger.info("Default MUM task '%s' exists but doesn't match spec, updating it", DEFAULT_TASK_NAME)
        updated = await tasks_api.put(f"/{DEFAULT_TASK_NAME}", json=spec)
        logger.info("Successfully updated default MUM task '%s'", DEFAULT_TASK_NAME)
        return updated
    except HTTPException as exc:  # type: ignore[name-defined]
        if exc.status_code != status.HTTP_404_NOT_FOUND:
            logger.error("Failed to get default MUM task '%s': %s (status: %s)", DEFAULT_TASK_NAME, exc.detail, exc.status_code)
            raise
        # Task doesn't exist yet - this is expected, we'll create it below
        logger.info("Default MUM task '%s' not found (404), will create it now", DEFAULT_TASK_NAME)
    try:
        logger.info("Creating default MUM task '%s' with spec: %s", DEFAULT_TASK_NAME, json.dumps(spec, indent=2))
        try:
            created = await tasks_api.post("/", json=spec)
            logger.info("POST request to create task succeeded. Response keys: %s", list(created.keys()) if isinstance(created, dict) else type(created))
            if isinstance(created, dict):
                logger.debug("Created task details: name=%s, id=%s, backend=%s, owner=%s", 
                           created.get("name"), created.get("id"), created.get("backend"), created.get("owner"))
        except HTTPException as create_exc:  # type: ignore[name-defined]
            logger.error("HTTPException during task creation POST: status=%s, detail=%s", 
                        create_exc.status_code, create_exc.detail)
            raise
        except Exception as create_exc:
            logger.exception("Unexpected exception during task creation POST request: %s", create_exc)
            raise
        if not created or not isinstance(created, dict):
            logger.error("Task creation returned invalid response: %s", created)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Task creation returned invalid response: {type(created)}"
            )
        logger.info("Successfully created default MUM task '%s' (ID: %s)", DEFAULT_TASK_NAME, created.get("id"))
        # Verify the task was actually created and is accessible
        # Retry a few times in case of eventual consistency
        for attempt in range(3):
            try:
                verify_task = await tasks_api.get(f"/{DEFAULT_TASK_NAME}")
                logger.debug("Verified task creation - task exists: %s (attempt %d)", verify_task.get("name"), attempt + 1)
                # Ensure the task is not marked as a template
                if verify_task.get("is_template"):
                    logger.warning("Task '%s' was created as a template, this should not happen", DEFAULT_TASK_NAME)
                return created
            except HTTPException as verify_exc:  # type: ignore[name-defined]
                if verify_exc.status_code == status.HTTP_404_NOT_FOUND and attempt < 2:
                    logger.debug("Task not yet available, retrying in 0.1s (attempt %d)", attempt + 1)
                    await asyncio.sleep(0.1)
                    continue
                raise
        return created
    except HTTPException as exc:  # type: ignore[name-defined]
        if exc.status_code == status.HTTP_409_CONFLICT:
            # Task was created concurrently; fetch and reconcile instead of failing.
            logger.info("Got 409 conflict when creating task '%s', attempting to fetch existing task", DEFAULT_TASK_NAME)
            # Retry fetching a few times in case of eventual consistency
            for fetch_attempt in range(3):
                try:
                    existing = await tasks_api.get(f"/{DEFAULT_TASK_NAME}")
                    logger.info("Successfully fetched task '%s' after 409 conflict (attempt %d)", DEFAULT_TASK_NAME, fetch_attempt + 1)
                    if _task_matches_spec(existing, spec):
                        logger.debug("Concurrently created task matches spec")
                        return existing
                    logger.info("Task '%s' exists but doesn't match spec, updating it", DEFAULT_TASK_NAME)
                    return await tasks_api.put(f"/{DEFAULT_TASK_NAME}", json=spec)
                except HTTPException as fetch_exc:  # type: ignore[name-defined]
                    if fetch_exc.status_code == status.HTTP_404_NOT_FOUND and fetch_attempt < 2:
                        logger.warning("Got 409 conflict but task '%s' doesn't exist yet (404), retrying in 0.2s (attempt %d)", 
                                      DEFAULT_TASK_NAME, fetch_attempt + 1)
                        await asyncio.sleep(0.2)
                        continue
                    logger.error("Got 409 conflict but task '%s' still doesn't exist after retries (status: %s). "
                               "This suggests the creation failed or there's a race condition. Original 409 error: %s",
                               DEFAULT_TASK_NAME, fetch_exc.status_code, exc.detail)
                    # If we still can't find it after retries, try creating again
                    logger.info("Attempting to create task '%s' again after 409->404 issue", DEFAULT_TASK_NAME)
                    try:
                        created_retry = await tasks_api.post("/", json=spec)
                        logger.info("Successfully created task '%s' on retry", DEFAULT_TASK_NAME)
                        return created_retry
                    except HTTPException as retry_exc:  # type: ignore[name-defined]
                        logger.error("Retry creation also failed: status=%s, detail=%s", retry_exc.status_code, retry_exc.detail)
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Task creation conflict occurred but task '{DEFAULT_TASK_NAME}' was not found and retry creation failed. "
                                   f"Original 409 error: {exc.detail}, Retry error: {retry_exc.detail}"
                        ) from retry_exc
        # For any other error status, log and raise
        logger.error("Failed to create default MUM task '%s': %s (status: %s). Spec was: %s", 
                    DEFAULT_TASK_NAME, exc.detail, exc.status_code, json.dumps(spec, indent=2))
        raise


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
    logger.debug("_execute_default_task called for target '%s'", target)
    try:
        default_task = await _ensure_default_task(tasks_api)
        logger.debug("_ensure_default_task returned: %s", default_task.get("name") if default_task else "None")
    except Exception as ensure_exc:
        logger.exception("Exception in _ensure_default_task: %s", ensure_exc)
        raise
    
    if not default_task or not default_task.get("name"):
        logger.error("_ensure_default_task returned invalid task: %s", default_task)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to ensure default MUM task exists",
        )
    task_name = default_task["name"]
    logger.info("Preparing to execute task '%s' on target '%s'", task_name, target)
    
    # Verify the task exists before trying to execute it
    try:
        verify_task = await tasks_api.get(f"/{task_name}")
        logger.debug("Verified task '%s' exists before execution", task_name)
    except HTTPException as verify_exc:  # type: ignore[name-defined]
        logger.error("Task '%s' does not exist when trying to execute! Status: %s, Detail: %s", 
                    task_name, verify_exc.status_code, verify_exc.detail)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Task '{task_name}' was not found when attempting to execute. This should not happen.",
        ) from verify_exc
    
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
    """Get or create the default MUM task.
    Returns the default MUM task (including its ID) as JSON.
    All MUM operations use this single task with different config arguments.
    """
    try:
        default_task = await _ensure_default_task(tasks_api)
        return JSONResponse(content=default_task, status_code=status.HTTP_200_OK)
    except HTTPException as exc:  # type: ignore[name-defined]
        return JSONResponse(content={"detail": exc.detail}, status_code=exc.status_code)