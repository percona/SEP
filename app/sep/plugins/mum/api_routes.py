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

"""JSON API routes for the MUM plugin, mounted at /api/plugins/mum/ by the shared API router."""

from typing import Any
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel

from app.sep.deps import TaskAPI
from app.sep.plugins.mum.routes import (
    _create_nomad_config_variable,
    _delete_nomad_config_variable,
    _execute_mum_task,
    _resolve_mum_task_name,
)

router = APIRouter()


class _TargetOnly(BaseModel):
    target: str


class _UserCreate(BaseModel):
    target: str
    username: str
    password: str
    roles: list[Any] = []
    db: str = "admin"


class _UserUpdate(BaseModel):
    target: str
    username: str
    password: str | None = None
    roles: list[Any] | None = None
    db: str = "admin"


class _UserDelete(BaseModel):
    target: str
    username: str
    db: str = "admin"


class _RoleCreate(BaseModel):
    target: str
    role: str
    db: str = "admin"
    privileges: list[Any] = []
    inheritedRoles: list[Any] = []


class _RoleUpdate(BaseModel):
    target: str
    role: str
    db: str = "admin"
    privileges: list[Any] = []
    inheritedRoles: list[Any] = []


class _RoleDelete(BaseModel):
    target: str
    role: str
    db: str = "admin"


@router.post("/ui/list-users", status_code=201)
async def api_list_users(body: _TargetOnly, tasks_api: TaskAPI) -> dict[str, Any]:
    task_name = _resolve_mum_task_name("list_users")
    task, history = await _execute_mum_task(
        tasks_api,
        task_name=task_name,
        target=body.target,
        config={"action": "list_users"},
        meta={"_nonce": uuid4().hex},
    )
    return {"task": task, "history": history}


@router.post("/ui/list-roles", status_code=201)
async def api_list_roles(body: _TargetOnly, tasks_api: TaskAPI) -> dict[str, Any]:
    task_name = _resolve_mum_task_name("list_roles")
    task, history = await _execute_mum_task(
        tasks_api,
        task_name=task_name,
        target=body.target,
        config={"action": "list_roles"},
        meta={"_nonce": uuid4().hex},
    )
    return {"task": task, "history": history}


@router.post("/ui/create-user", status_code=201)
async def api_create_user(body: _UserCreate, tasks_api: TaskAPI) -> dict[str, Any]:
    config_obj: dict[str, Any] = {
        "action": "create_user",
        "username": body.username,
        "password": body.password,
        "roles": body.roles,
        "db": body.db,
    }
    task_name = _resolve_mum_task_name("create_user")
    job_prefix = f"mum-{uuid4().hex}"
    config_nomad_variable = await _create_nomad_config_variable(
        tasks_api, config=config_obj, job_prefix=job_prefix
    )
    config_obj.pop("password", None)
    try:
        task, history = await _execute_mum_task(
            tasks_api,
            task_name=task_name,
            target=body.target,
            config=None,
            config_nomad_variable=config_nomad_variable,
            meta={"_job_id_prefix": job_prefix},
        )
    except Exception:
        await _delete_nomad_config_variable(tasks_api, path=config_nomad_variable)
        raise
    return {"task": task, "history": history}


@router.post("/ui/update-user", status_code=201)
async def api_update_user(body: _UserUpdate, tasks_api: TaskAPI) -> dict[str, Any]:
    config_obj: dict[str, Any] = {
        "action": "update_user",
        "username": body.username,
        "db": body.db,
    }
    if body.password:
        config_obj["password"] = body.password
    if body.roles is not None:
        config_obj["roles"] = body.roles

    config_nomad_variable = None
    exec_meta: dict[str, Any] | None = None
    if "password" in config_obj:
        job_prefix = f"mum-{uuid4().hex}"
        config_nomad_variable = await _create_nomad_config_variable(
            tasks_api, config=config_obj, job_prefix=job_prefix
        )
        exec_meta = {"_job_id_prefix": job_prefix}
        config_obj.pop("password", None)

    task_name = _resolve_mum_task_name("update_user")
    try:
        task, history = await _execute_mum_task(
            tasks_api,
            task_name=task_name,
            target=body.target,
            config=None if config_nomad_variable else config_obj,
            config_nomad_variable=config_nomad_variable,
            meta=exec_meta,
        )
    except Exception:
        if config_nomad_variable:
            await _delete_nomad_config_variable(tasks_api, path=config_nomad_variable)
        raise
    return {"task": task, "history": history}


@router.post("/ui/delete-user", status_code=201)
async def api_delete_user(body: _UserDelete, tasks_api: TaskAPI) -> dict[str, Any]:
    config_obj: dict[str, Any] = {
        "action": "delete_user",
        "username": body.username,
        "db": body.db,
    }
    task_name = _resolve_mum_task_name("delete_user")
    task, history = await _execute_mum_task(
        tasks_api, task_name=task_name, target=body.target, config=config_obj
    )
    return {"task": task, "history": history}


@router.post("/ui/create-role", status_code=201)
async def api_create_role(body: _RoleCreate, tasks_api: TaskAPI) -> dict[str, Any]:
    config_obj: dict[str, Any] = {
        "action": "create_role",
        "role": body.role,
        "db": body.db,
        "privileges": body.privileges,
        "inheritedRoles": body.inheritedRoles,
    }
    task_name = _resolve_mum_task_name("create_role")
    task, history = await _execute_mum_task(
        tasks_api, task_name=task_name, target=body.target, config=config_obj
    )
    return {"task": task, "history": history}


@router.post("/ui/update-role", status_code=201)
async def api_update_role(body: _RoleUpdate, tasks_api: TaskAPI) -> dict[str, Any]:
    config_obj: dict[str, Any] = {
        "action": "update_role",
        "role": body.role,
        "db": body.db,
        "privileges": body.privileges,
        "inheritedRoles": body.inheritedRoles,
    }
    task_name = _resolve_mum_task_name("update_role")
    task, history = await _execute_mum_task(
        tasks_api, task_name=task_name, target=body.target, config=config_obj
    )
    return {"task": task, "history": history}


@router.post("/ui/delete-role", status_code=201)
async def api_delete_role(body: _RoleDelete, tasks_api: TaskAPI) -> dict[str, Any]:
    config_obj: dict[str, Any] = {
        "action": "delete_role",
        "role": body.role,
        "db": body.db,
    }
    task_name = _resolve_mum_task_name("delete_role")
    task, history = await _execute_mum_task(
        tasks_api, task_name=task_name, target=body.target, config=config_obj
    )
    return {"task": task, "history": history}
