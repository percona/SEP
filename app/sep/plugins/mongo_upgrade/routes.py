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

import asyncio
import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.sep.deps import ExecutorHosts, TaskAPI

logger = logging.getLogger(__name__)

router = APIRouter()

_TERMINAL_STATUSES = frozenset({"failed", "success", "stopped", "stale"})


class _DiscoverRun(BaseModel):
    host_id: str
    host_name: str
    task_history_id: str


class _DiscoverResponse(BaseModel):
    runs: list[_DiscoverRun]


class _TopologyEntry(BaseModel):
    host_id: str
    task_history_id: str
    status: str
    role: str | None = None
    set_name: str | None = None
    me: str | None = None
    hosts: list[str] | None = None
    mongod_version: str | None = None


class _UpgradeRequest(BaseModel):
    target: str
    mongo_release: str
    mongo_version: str = ""
    restart_service: str = "mongod"
    chain_targets: list[str] = []


class _UpgradeResponse(BaseModel):
    task_history_id: str


async def _dispatch_discover(tasks_api: TaskAPI, host_id: str, host_name: str) -> _DiscoverRun:
    history = await tasks_api.post(
        "/execute/discover-mongo",
        json={"meta": {"target": host_id}},
    )
    return _DiscoverRun(host_id=host_id, host_name=host_name, task_history_id=str(history["id"]))


async def _parse_role_from_logs(tasks_api: TaskAPI, task_history_id: str) -> dict[str, Any]:
    last_json: dict[str, Any] = {}
    try:
        async for raw_line in tasks_api.stream(
            f"/history/{task_history_id}/logs/",
            params={"tail": "10"},
        ):
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                log_entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = log_entry.get("msg") or log_entry.get("message", "")
            if not msg:
                continue
            try:
                parsed = json.loads(msg)
                if "role" in parsed:
                    last_json = parsed
            except (json.JSONDecodeError, TypeError):
                continue
    except Exception:
        logger.warning("Failed to stream logs for task history %s", task_history_id, exc_info=True)
    return last_json


@router.post("/upgrade", response_model=_UpgradeResponse, status_code=201)
async def start_upgrade(body: _UpgradeRequest, tasks_api: TaskAPI) -> _UpgradeResponse:
    meta: dict[str, Any] = {
        "target": body.target,
        "mongo_release": body.mongo_release,
    }
    if body.mongo_version:
        meta["mongo_version"] = body.mongo_version
    if body.restart_service:
        meta["restart_service"] = body.restart_service

    request: dict[str, Any] = {"meta": meta}
    if body.chain_targets:
        request["chain_task_names"] = ["upgrade-mongo"] * len(body.chain_targets)
        request["chain_targets"] = body.chain_targets

    history = await tasks_api.post("/execute/upgrade-mongo", json=request)
    return _UpgradeResponse(task_history_id=str(history["id"]))


@router.post("/discover", response_model=_DiscoverResponse, status_code=201)
async def discover_topology(
    executor_hosts: ExecutorHosts,
    tasks_api: TaskAPI,
) -> _DiscoverResponse:
    runs = await asyncio.gather(
        *(_dispatch_discover(tasks_api, host_id, host_id) for host_id in executor_hosts),
        return_exceptions=True,
    )
    successful: list[_DiscoverRun] = []
    for host_id, result in zip(executor_hosts, runs):
        if isinstance(result, Exception):
            logger.warning("Failed to dispatch discover-mongo on %s: %s", host_id, result)
        else:
            successful.append(result)
    return _DiscoverResponse(runs=successful)


@router.get("/topology-status", response_model=list[_TopologyEntry])
async def topology_status(
    ids: Annotated[str, Query(description="Comma-separated task_history_ids")],
    tasks_api: TaskAPI,
) -> list[_TopologyEntry]:
    task_history_ids = [i.strip() for i in ids.split(",") if i.strip()]

    async def _fetch_one(task_history_id: str) -> _TopologyEntry:
        history = await tasks_api.get(f"/history/{task_history_id}")
        status = (history.get("status") or "").lower()
        execution_request = history.get("execution_request") or {}
        meta = execution_request.get("meta") or {}
        host_id = meta.get("target") or execution_request.get("target") or ""

        role_data: dict[str, Any] = {}
        if status in _TERMINAL_STATUSES:
            role_data = await _parse_role_from_logs(tasks_api, task_history_id)

        return _TopologyEntry(
            host_id=host_id,
            task_history_id=task_history_id,
            status=status,
            role=role_data.get("role"),
            set_name=role_data.get("setName"),
            me=role_data.get("me"),
            hosts=role_data.get("hosts"),
            mongod_version=role_data.get("mongodVersion"),
        )

    results = await asyncio.gather(
        *(_fetch_one(tid) for tid in task_history_ids),
        return_exceptions=True,
    )
    entries: list[_TopologyEntry] = []
    for tid, result in zip(task_history_ids, results):
        if isinstance(result, Exception):
            logger.warning("Failed to fetch topology status for %s: %s", tid, result)
            entries.append(
                _TopologyEntry(
                    host_id="",
                    task_history_id=tid,
                    status="error",
                    role="unreachable",
                )
            )
        else:
            entries.append(result)
    return entries
