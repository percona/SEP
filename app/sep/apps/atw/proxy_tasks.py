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

"""Resolve the ATW-owned PROXY task that carries ATW's run-result recorder.

ATW's recorder cannot be stamped on the task its snippets dispatch under today:
those resolve to the shared ``exec-artifact`` / ``exec-python-artifact`` rows,
which are ``protected=True`` and seeded inside ``app/tasks/``, and
``TaskExecuteRequest`` carries no per-execution recorder override. A
``backend=PROXY`` task names a root task in ``data["task"]`` and carries its own
``run_result_recorder``; ``TaskHistory`` binds to the *dispatched* task while
``get_root_task`` is consulted only to pick the executor, so the proxy's recorder
fires and execution still runs under the root.

Every degradation here returns ``None``, meaning "dispatch under the root
unchanged". Correctness then falls back to the reconciliation sweep, which is
strictly better than refusing to dispatch or wrapping a task whose behaviour is
unknown.
"""

import logging
from collections.abc import Mapping
from typing import Any

from async_lru import alru_cache

from app.core.exceptions import (
    HTTPBadRequestException,
    HTTPConflictException,
    HTTPNotFoundException,
)
from app.core.requests import as_json_object, RemoteAPI
from app.core.security import require_internal_token
from app.sep.apps.atw.recorder import RUN_RESULT_RECORDER
from app.sep.apps.atw.send import get_tasks_api
from app.tasks.execution.executors.nomad.steps import RUN_SCRIPT_OUTPUT_FILES_PATH
from app.tasks.models import ANY_OWNER, TaskBackendEnum, TaskWrite

logger = logging.getLogger(__name__)

#: Prefix distinguishing ATW's proxy from the interpreter root it wraps.
ATW_PROXY_TASK_PREFIX = "atw__"

#: How long a validated resolution is memoized. A proxy deleted out from under a
#: warm cache makes dispatch fail until this expires, then self-heals.
_PROXY_CACHE_TTL = 300

#: One entry per interpreter root ATW can dispatch under; the set is tiny and
#: fixed by the snippet interpreter configuration.
_PROXY_CACHE_MAXSIZE = 8


def atw_proxy_task_name(root_task_name: str) -> str:
    """Return the ATW proxy task name wrapping ``root_task_name``.

    :param root_task_name: The interpreter task the proxy dispatches through.
    :return: The proxy's task name.
    """
    return f"{ATW_PROXY_TASK_PREFIX}{root_task_name}"


def _build_proxy_task_write(root_task_name: str) -> TaskWrite:
    """Build the proxy task ATW creates for ``root_task_name``.

    The payload is deliberately thin — ``data`` carries only ``task``, with no
    ``meta`` and no ``payload`` key — because ``prepare_task_history`` merges a
    proxy's own meta *over* the caller's and would otherwise overwrite the run's
    execution meta with the proxy's.

    ``owner`` and ``anonymize_mask`` are not cosmetic: ``prepare_task_history``
    resolves the anonymization mask off the **proxy**, not the root, so both are
    set to reproduce today's resolution byte-for-byte. ``output_files_path`` is
    copied across for the same reason — ``read_run_result`` reads it off the
    dispatched task, and leaving it unset silently disables result reading.

    :param root_task_name: The interpreter task the proxy dispatches through.
    :return: The create payload for the proxy task.
    """
    return TaskWrite(
        name=atw_proxy_task_name(root_task_name),
        owner=ANY_OWNER,
        backend=TaskBackendEnum.PROXY,
        data={"task": root_task_name},
        run_result_recorder=RUN_RESULT_RECORDER,
        output_files_path=RUN_SCRIPT_OUTPUT_FILES_PATH,
        anonymize_mask=None,
    )


def _is_expected_proxy(task: Mapping[str, Any], root_task_name: str) -> bool:
    """Check whether an existing task is the proxy this module would have created.

    A name collision proves only that *a* task owns the name. ``update_task`` lets
    any of these fields be edited after creation, and each one this design depends
    on changes behaviour silently if wrong — so every one is checked rather than
    trusting the name.

    :param task: The upstream task payload to validate.
    :param root_task_name: The interpreter task the proxy must dispatch through.
    :return: ``True`` when every field matches what ATW requires.
    """
    data = task.get("data")
    if not isinstance(data, dict):
        return False
    return (
        task.get("backend") == TaskBackendEnum.PROXY.value
        and data.get("task") == root_task_name
        and "meta" not in data
        and task.get("run_result_recorder") == RUN_RESULT_RECORDER
        and task.get("output_files_path") == RUN_SCRIPT_OUTPUT_FILES_PATH
        and task.get("owner") == ANY_OWNER
        and task.get("anonymize_mask") is None
    )


async def _fetch_task(tasks_api: RemoteAPI, name: str) -> dict[str, Any] | None:
    """Fetch one task by name, mapping a genuine absence to ``None``.

    Narrowed to :class:`HTTPNotFoundException` rather than ``HTTPException``: a
    non-JSON 404 from a proxy or gateway stays a bare ``HTTPException`` and must
    propagate, because treating an infrastructure failure as "the task does not
    exist" would have this module create a duplicate.

    :param tasks_api: The authenticated Tasks API client.
    :param name: The task name to fetch.
    :return: The task payload, or ``None`` when no such task exists.
    :raises HTTPException: Propagated for any upstream error status other than a
        JSON ``404`` — including a non-JSON ``404``, which signals a proxy or
        gateway failure rather than a missing task.
    :raises OSError: Propagated from the Tasks API when the transport itself fails.
    """
    try:
        return as_json_object(await tasks_api.get(f"/{name}"))
    except HTTPNotFoundException:
        return None


async def _create_proxy_task(
    tasks_api: RemoteAPI, root_task_name: str
) -> dict[str, Any] | None:
    """Create the proxy task, resolving a concurrent creator's win by re-fetching.

    Both 409 and 400 are treated as a race rather than an error:
    ``TaskManager.create``'s duplicate precheck answers 409 only when it *sees* the
    row, so a concurrent insert instead trips the commit branch and raises a 400.
    Handling only 409 would turn a live race into a failed dispatch.

    :param tasks_api: The authenticated Tasks API client.
    :param root_task_name: The interpreter task the proxy dispatches through.
    :return: The created or concurrently-created task, or ``None`` if it vanished.
    :raises HTTPException: Propagated for any upstream error status other than the
        ``409`` / ``400`` pair that a concurrent creator produces.
    :raises OSError: Propagated from the Tasks API when the transport itself fails.
    """
    task_write = _build_proxy_task_write(root_task_name)
    try:
        return as_json_object(await tasks_api.post("/", json=task_write.model_dump()))
    except (HTTPConflictException, HTTPBadRequestException):
        logger.info(
            "ATW proxy task %s was created concurrently; validating the winner.",
            task_write.name,
        )
        return await _fetch_task(tasks_api, task_write.name)


@alru_cache(maxsize=_PROXY_CACHE_MAXSIZE, ttl=_PROXY_CACHE_TTL)
async def _resolve_atw_proxy_task(root_task_name: str) -> str | None:
    """Fetch, validate, or create ATW's proxy for one interpreter root.

    Takes only the root task name so the memoization key stays hashable and
    process-wide; the client is built here rather than passed in, because a
    request-scoped ``RemoteAPI`` would defeat the cache and is unavailable to a
    worker.

    :param root_task_name: The interpreter task to dispatch through.
    :return: The proxy task name, or ``None`` to dispatch under the root unchanged.
    :raises HTTPException: Propagated from an upstream error status that is neither a
        genuine ``404`` nor the create race's ``409`` / ``400``.
    :raises OSError: Propagated from the Tasks API when the transport itself fails.
    :raises RuntimeError: Propagated from ``require_internal_token`` when no internal
        token is configured.
    """
    client = await get_tasks_api()
    with client.auth(require_internal_token()) as tasks_api:
        root = await _fetch_task(tasks_api, root_task_name)
        if root is None:
            logger.warning(
                "Interpreter task %s does not exist upstream; dispatching unwrapped.",
                root_task_name,
            )
            return None
        if root.get("backend") == TaskBackendEnum.PROXY.value:
            # get_root_task resolves exactly one hop, so a proxy-of-a-proxy still
            # reaches get_executor as PROXY and raises "Unsupported backend",
            # breaking every dispatch under this interpreter.
            logger.warning(
                "Interpreter task %s is itself a PROXY; dispatching unwrapped to "
                "avoid a two-hop chain.",
                root_task_name,
            )
            return None
        proxy_name = atw_proxy_task_name(root_task_name)
        proxy = await _fetch_task(tasks_api, proxy_name)
        if proxy is None:
            proxy = await _create_proxy_task(tasks_api, root_task_name)
        if proxy is None or not _is_expected_proxy(proxy, root_task_name):
            logger.error(
                "Task %s exists but is not the proxy ATW requires (backend=%r, "
                "data=%r, run_result_recorder=%r); dispatching unwrapped so the "
                "reconciliation sweep supplies the outcome instead.",
                proxy_name,
                None if proxy is None else proxy.get("backend"),
                None if proxy is None else proxy.get("data"),
                None if proxy is None else proxy.get("run_result_recorder"),
            )
            return None
        return proxy_name


def clear_atw_proxy_task_cache() -> None:
    """Reset the memoized proxy resolutions.

    Provide a single public entry point for tests to wipe the ``alru_cache`` on
    :func:`_resolve_atw_proxy_task`, which is process-wide and would otherwise carry
    one test's resolution into the next. Production code does not need this — the
    cache honors its own TTL, and a degraded resolution is evicted as it is returned.

    :return: ``None``.
    """
    _resolve_atw_proxy_task.cache_clear()


async def ensure_atw_proxy_task(root_task_name: str) -> str | None:
    """Return the ATW proxy task to dispatch ``root_task_name`` through.

    Only a validated resolution stays memoized: a degraded answer is evicted
    before returning, so a poisoned or half-created row is re-examined on the next
    dispatch rather than pinned for the cache TTL.

    :param root_task_name: The interpreter task the snippet would dispatch under.
    :return: The proxy task name, or ``None`` to dispatch under the root unchanged.
    :raises HTTPException: Propagated from an upstream error status that is neither a
        genuine ``404`` nor the create race's ``409`` / ``400``. A dispatch failing
        because the Tasks API is unreachable should surface, not be silently
        downgraded to an unwrapped run.
    :raises OSError: Propagated from the Tasks API when the transport itself fails.
    :raises RuntimeError: Propagated from ``require_internal_token`` when no internal
        token is configured.
    """
    proxy_name = await _resolve_atw_proxy_task(root_task_name)
    if proxy_name is None:
        _resolve_atw_proxy_task.cache_invalidate(root_task_name)
    return proxy_name
