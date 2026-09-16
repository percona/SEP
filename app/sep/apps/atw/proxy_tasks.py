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

A proxy is a **materialized copy** of the root's behavioural policy — owner,
anonymization mask, output path, alert hooks — because those are resolved off the
dispatched task. That is why nothing here is memoized: a cache keyed on the root's
name would keep dispatching under a superseded policy for as long as it stayed warm,
and for the mask that means the wrong PII treatment. The root is read on every
resolution, and a proxy that no longer matches it is rewritten rather than refused.
Resolution happens once per distinct root per batch, so the reads scale with the
interpreters a request touches, not with its items.
"""

import logging
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import ValidationError

from app.core.exceptions import (
    HTTPBadRequestException,
    HTTPConflictException,
    HTTPNotFoundException,
)
from app.core.requests import as_json_object, RemoteAPI
from app.core.security import require_internal_token
from app.sep.apps.atw.recorder import RUN_RESULT_RECORDER
from app.sep.apps.atw.send import get_tasks_api
from app.tasks.models import ANY_OWNER, TaskBackendEnum, TaskWrite

logger = logging.getLogger(__name__)

#: Prefix distinguishing ATW's proxy from the interpreter root it wraps.
ATW_PROXY_TASK_PREFIX = "atw__"


def atw_proxy_task_name(root_task_name: str) -> str:
    """Return the ATW proxy task name wrapping ``root_task_name``.

    :param root_task_name: The interpreter task the proxy dispatches through.
    :return: The proxy's task name.
    """
    return f"{ATW_PROXY_TASK_PREFIX}{root_task_name}"


def _inherited_from_root(root: Mapping[str, Any]) -> dict[str, Any]:
    """Extract the behavioural fields a proxy must reproduce from the root it wraps.

    Every field here is resolved off the **dispatched** task rather than the root:
    ``prepare_task_history`` reads ``anonymize_mask`` directly and derives the
    default mask from ``owner``; ``read_run_result`` reads ``output_files_path``;
    and the dispatch-failure alert reads ``alert_on_fail`` / ``alert_detail_builder``.
    Wrapping a task therefore substitutes the proxy's values for the root's, so the
    proxy has to carry the root's own.

    Hardcoding them instead would be correct only for the seeded interpreter roots.
    ``SnippetInterpreterConfig.task`` is a plain overridable setting, so an operator
    may point ATW at a task with a different owner, mask or output path — and the
    substitution is silent: the wrong PII policy applies, or results are read from a
    path the executor never wrote to.

    ``run_result_recorder`` is deliberately absent: carrying ATW's own is the entire
    reason the proxy exists.

    :param root: The fetched root task payload.
    :return: The fields to copy onto the proxy, as a create-and-validate pair.
    """
    return {
        # Defaulted because TaskWrite.owner is non-optional; the seeded roots leave
        # it at this value anyway.
        "owner": root.get("owner") or ANY_OWNER,
        "anonymize_mask": root.get("anonymize_mask"),
        "output_files_path": root.get("output_files_path"),
        "alert_on_fail": bool(root.get("alert_on_fail")),
        "alert_detail_builder": root.get("alert_detail_builder"),
    }


def _build_proxy_task_write(root_task_name: str, root: Mapping[str, Any]) -> TaskWrite:
    """Build the proxy task ATW creates for ``root_task_name``.

    The payload is deliberately thin — ``data`` carries only ``task``, with no
    ``meta`` and no ``payload`` key — because ``prepare_task_history`` merges a
    proxy's own meta *over* the caller's and substitutes its own payload for the
    caller's, either of which would override what the run itself asked for.

    Everything else behavioural is copied from the root, so wrapping a task changes
    where the recorder points and nothing else — see :func:`_inherited_from_root`.

    :param root_task_name: The interpreter task the proxy dispatches through.
    :param root: The fetched root task, whose behavioural fields are copied.
    :return: The create payload for the proxy task.
    """
    return TaskWrite(
        name=atw_proxy_task_name(root_task_name),
        backend=TaskBackendEnum.PROXY,
        data={"task": root_task_name},
        run_result_recorder=RUN_RESULT_RECORDER,
        **_inherited_from_root(root),
    )


def _is_expected_proxy(
    task: Mapping[str, Any], root_task_name: str, root: Mapping[str, Any]
) -> bool:
    """Check whether an existing task is the proxy this module would have created.

    A name collision proves only that *a* task owns the name. ``update_task`` lets
    any of these fields be edited after creation, and each one this design depends
    on changes behaviour silently if wrong — so every one is checked rather than
    trusting the name.

    ``meta`` and ``payload`` are both checked for *absence* because
    ``prepare_task_history`` lets a proxy's own copy of either override the run's:
    a proxy that acquired a ``payload`` key would substitute it into every
    diagnostics dispatch thereafter.

    The behavioural fields are compared against the **root's** values through the
    same helper that supplies them at creation, so the two cannot drift: a proxy
    left behind by an earlier configuration, or reshaped afterwards, fails here
    rather than silently applying the wrong policy.

    :param task: The upstream task payload to validate.
    :param root_task_name: The interpreter task the proxy must dispatch through.
    :param root: The fetched root task, whose behavioural fields the proxy must
        reproduce.
    :return: ``True`` when every field matches what ATW requires.
    """
    data = task.get("data")
    if not isinstance(data, dict):
        return False
    inherited = _inherited_from_root(root)
    return (
        task.get("backend") == TaskBackendEnum.PROXY.value
        and data.get("task") == root_task_name
        and "meta" not in data
        and "payload" not in data
        and task.get("run_result_recorder") == RUN_RESULT_RECORDER
        and all(task.get(field) == value for field, value in inherited.items())
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
    tasks_api: RemoteAPI, root_task_name: str, root: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Create the proxy task, resolving a concurrent creator's win by re-fetching.

    Both 409 and 400 are treated as a race rather than an error:
    ``TaskManager.create``'s duplicate precheck answers 409 only when it *sees* the
    row, so a concurrent insert instead trips the commit branch and raises a 400.
    Handling only 409 would turn a live race into a failed dispatch.

    :param tasks_api: The authenticated Tasks API client.
    :param root_task_name: The interpreter task the proxy dispatches through.
    :param root: The fetched root task, whose behavioural fields are copied.
    :return: The created or concurrently-created task, or ``None`` if it vanished.
    :raises HTTPException: Propagated for any upstream error status other than the
        ``409`` / ``400`` pair that a concurrent creator produces.
    :raises OSError: Propagated from the Tasks API when the transport itself fails.
    """
    try:
        task_write = _build_proxy_task_write(root_task_name, root)
    except ValidationError:
        # The payload is assembled from an arbitrary configured root, so it can be
        # rejected for reasons this module does not enumerate — a root name within
        # the 255-character limit whose prefixed form is not, or any inherited field
        # the model refuses. Declining keeps "every degradation dispatches under the
        # root" true instead of surfacing a 500 from a dispatch that could proceed.
        logger.exception(
            "Could not build ATW's proxy task for %s; dispatching unwrapped.",
            root_task_name,
        )
        return None
    try:
        return as_json_object(await tasks_api.post("/", json=task_write.model_dump()))
    except (HTTPConflictException, HTTPBadRequestException):
        logger.info(
            "ATW proxy task %s was created concurrently; validating the winner.",
            task_write.name,
        )
        return await _fetch_task(tasks_api, task_write.name)


async def _sync_proxy_task(
    tasks_api: RemoteAPI, root_task_name: str, root: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Rewrite an existing proxy so it matches the root's current behaviour.

    ``PUT /{task_name}`` replaces the task wholesale, and the payload is rebuilt from
    the root, so this both repairs a proxy left over from an earlier interpreter
    configuration and picks up a policy edit on the root itself.

    :param tasks_api: The authenticated Tasks API client.
    :param root_task_name: The interpreter task the proxy dispatches through.
    :param root: The fetched root task, whose behavioural fields are copied.
    :return: The updated task, or ``None`` when the payload could not be built.
    :raises HTTPException: Propagated from an upstream error status.
    :raises OSError: Propagated from the Tasks API when the transport itself fails.
    """
    try:
        task_write = _build_proxy_task_write(root_task_name, root)
    except ValidationError:
        logger.exception(
            "Could not build ATW's proxy task for %s; dispatching unwrapped.",
            root_task_name,
        )
        return None
    logger.info(
        "Re-syncing ATW proxy task %s to the current behaviour of %s.",
        task_write.name,
        root_task_name,
    )
    return as_json_object(
        await tasks_api.put(f"/{task_write.name}", json=task_write.model_dump())
    )


async def _resolve_one(tasks_api: RemoteAPI, root_task_name: str) -> str | None:
    """Fetch, validate, re-sync or create ATW's proxy for one interpreter root.

    The root is read on every resolution rather than cached. The proxy is a
    *materialized copy* of the root's behavioural policy, so any window in which the
    root is not read is a window in which a superseded policy keeps being applied —
    and for ``anonymize_mask`` that means the wrong PII treatment. Reading it is the
    only way to know, so it is read.

    :param tasks_api: The authenticated Tasks API client.
    :param root_task_name: The interpreter task to dispatch through.
    :return: The proxy task name, or ``None`` to dispatch under the root unchanged.
    :raises HTTPException: Propagated from an upstream error status that is neither a
        genuine ``404`` nor the create race's ``409`` / ``400``.
    :raises OSError: Propagated from the Tasks API when the transport itself fails.
    """
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
    if root.get("run_result_recorder"):
        # maybe_record_run resolves exactly one recorder with no chaining, so
        # wrapping would substitute ATW's for the root's and silently stop
        # whatever that one records.
        logger.warning(
            "Interpreter task %s already declares a run-result recorder (%r); "
            "dispatching unwrapped rather than displacing it, and letting the "
            "reconciliation sweep supply ATW's outcome.",
            root_task_name,
            root.get("run_result_recorder"),
        )
        return None
    proxy_name = atw_proxy_task_name(root_task_name)
    proxy = await _fetch_task(tasks_api, proxy_name)
    if proxy is None:
        proxy = await _create_proxy_task(tasks_api, root_task_name, root)
    elif not _is_expected_proxy(proxy, root_task_name, root):
        # The proxy exists but no longer matches the root — an interpreter re-pointed
        # at a task with a different policy, or the root's own policy edited. Re-sync
        # rather than refuse: refusing would degrade this interpreter permanently,
        # since nothing else ever repairs the row.
        proxy = await _sync_proxy_task(tasks_api, root_task_name, root)
    if proxy is None or not _is_expected_proxy(proxy, root_task_name, root):
        logger.error(
            "Task %s exists but is not the proxy ATW requires and could not be "
            "reconciled to it (backend=%r, data=%r, run_result_recorder=%r); "
            "dispatching unwrapped so the sweep supplies the outcome instead.",
            proxy_name,
            None if proxy is None else proxy.get("backend"),
            None if proxy is None else proxy.get("data"),
            None if proxy is None else proxy.get("run_result_recorder"),
        )
        return None
    return proxy_name


async def resolve_atw_proxy_tasks(
    root_task_names: Iterable[str],
) -> dict[str, str | None]:
    """Resolve the proxy to dispatch through for each distinct interpreter root.

    Resolved once per root for a whole batch rather than once per item: the roots in
    a batch are the handful its snippets' interpreters name, so a twenty-item request
    costs the same upstream traffic as a one-item request.

    Nothing is memoized across calls. The proxy copies the root's behavioural policy,
    so a cache keyed on the root's *name* would keep applying a superseded
    ``anonymize_mask`` for as long as it stayed warm; reading the root each time is
    what makes the policy live, and the reads are per request, not per run.

    The client is built here and authenticates as the service principal, so creating
    or repairing a proxy does not depend on the caller's own task permissions and the
    function works identically from a worker.

    :param root_task_names: The interpreter tasks the batch's snippets would dispatch
        under; duplicates are resolved once.
    :return: The proxy name per root, or ``None`` against a root to dispatch under it
        unchanged.
    :raises HTTPException: Propagated from an upstream error status that is neither a
        genuine ``404`` nor the create race's ``409`` / ``400``. A dispatch failing
        because the Tasks API is unreachable should surface, not be silently
        downgraded to an unwrapped run.
    :raises OSError: Propagated from the Tasks API when the transport itself fails.
    :raises RuntimeError: Propagated from ``require_internal_token`` when no internal
        token is configured.
    """
    client = await get_tasks_api()
    with client.auth(require_internal_token()) as tasks_api:
        return {
            root_task_name: await _resolve_one(tasks_api, root_task_name)
            for root_task_name in dict.fromkeys(root_task_names)
        }
