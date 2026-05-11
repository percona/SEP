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

"""Cascade POST/PUT/DELETE across a parent task and N derived siblings."""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from fastapi import HTTPException, status

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.core.requests.remote_api import RemoteAPI
    from app.sep.plugins.framework.schema import DerivedTask

__all__ = [
    "CascadeFailure",
    "CascadeResult",
    "build_derived_payload",
    "cascade_create_tasks",
    "cascade_delete_tasks",
    "cascade_update_tasks",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CascadeFailure:
    """Represent one per-leg failure surfaced by a best-effort cascade.

    :param task_name: The name of the task whose operation failed.
    :type task_name: str
    :param exception: The exception raised by the underlying ``TaskAPI`` call.
    :type exception: BaseException
    """

    task_name: str
    exception: BaseException


@dataclass
class CascadeResult:
    """Represent the outcome of a best-effort PUT or DELETE cascade.

    :param successes: Names of tasks whose operation completed cleanly.
    :type successes: list[str]
    :param failures: Per-leg failures collected without raising.
    :type failures: list[CascadeFailure]
    """

    successes: list[str] = field(default_factory=list)
    failures: list[CascadeFailure] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Return ``True`` when every leg succeeded.

        :return: Whether the cascade collected zero failures.
        :rtype: bool
        """
        return not self.failures


def build_derived_payload(
    parent_payload: dict[str, Any], derived_spec: DerivedTask
) -> dict[str, Any]:
    """Build the cascade payload for one derived task.

    Deep-copies ``parent_payload``, suffixes ``name`` with
    ``derived_spec.name_suffix``, applies ``arg_substitutions`` literally to
    ``data["meta"]["args"]`` (when present and string-typed), and sets
    ``data["parent"]`` when ``parent_link`` is true. The caller's
    ``parent_payload`` is never mutated.

    :param parent_payload: The parent task's serialised payload (typically
        ``parent.model_dump()``).
    :type parent_payload: dict[str, Any]
    :param derived_spec: The declarative spec for this derived task.
    :type derived_spec: DerivedTask
    :return: A new dict ready to POST or PUT as a task payload.
    :rtype: dict[str, Any]
    """
    payload = copy.deepcopy(parent_payload)
    parent_name = payload["name"]
    payload["name"] = f"{parent_name}{derived_spec.name_suffix}"
    if derived_spec.arg_substitutions:
        data = payload.setdefault("data", {})
        meta = data.get("meta")
        if isinstance(meta, dict) and isinstance(meta.get("args"), str):
            args = meta["args"]
            for old, new in derived_spec.arg_substitutions.items():
                args = args.replace(old, new)
            meta["args"] = args
    if derived_spec.parent_link:
        payload.setdefault("data", {})["parent"] = parent_name
    return payload


async def cascade_create_tasks(
    tasks_api: RemoteAPI,
    parent_payload: dict[str, Any],
    derived_specs: Sequence[DerivedTask],
    *,
    path: str = "/",
) -> None:
    """POST the parent then each derived task; roll back on any failure.

    On any POST failure, already-created tasks are deleted in reverse
    creation order. A rollback DELETE that itself fails is logged at WARNING
    and the rollback loop continues; the original POST exception is what
    surfaces to the caller.

    :param tasks_api: The :class:`RemoteAPI` for the tasks sub-app.
    :type tasks_api: RemoteAPI
    :param parent_payload: The parent task's serialised payload.
    :type parent_payload: dict[str, Any]
    :param derived_specs: The list of derived-task specs to cascade.
    :type derived_specs: Sequence[DerivedTask]
    :param path: The POST path on the tasks sub-app. Defaults to ``"/"``.
    :type path: str
    :raises HTTPException: Re-raises the original POST exception after the
        rollback DELETEs complete.
    """
    created_names = []
    try:
        await tasks_api.post(path, json=parent_payload)
        created_names.append(parent_payload["name"])
        for spec in derived_specs:
            child_payload = build_derived_payload(parent_payload, spec)
            await tasks_api.post(path, json=child_payload)
            created_names.append(child_payload["name"])
    except Exception:
        for task_name in reversed(created_names):
            try:
                await tasks_api.delete(f"/{task_name}")
            except Exception as rollback_exc:  # noqa: BLE001
                logger.warning(
                    "Rollback DELETE failed for %r during cascade_create rollback: %s",
                    task_name,
                    rollback_exc,
                )
        raise


async def cascade_update_tasks(
    tasks_api: RemoteAPI,
    parent_existing_name: str,
    parent_updated: dict[str, Any],
    derived_existing_names: list[str],
    derived_specs: Sequence[DerivedTask],
) -> CascadeResult:
    """PUT the parent and each derived task, best-effort.

    Parent failure does not abort derived updates — each leg is attempted
    independently and per-leg failures are collected into the returned
    :class:`CascadeResult`. The PUT URL path uses the *existing* task name
    (per the Tasks API contract); the updated payload, including any new
    ``name``, goes in the body.

    The caller is responsible for ensuring ``derived_existing_names`` matches
    ``derived_specs`` in length and order — the function rejects a mismatch
    with :class:`ValueError` rather than silently zipping to the shorter list.

    :param tasks_api: The :class:`RemoteAPI` for the tasks sub-app.
    :type tasks_api: RemoteAPI
    :param parent_existing_name: The current name of the parent task (used in
        the PUT URL; any rename goes in ``parent_updated["name"]``).
    :type parent_existing_name: str
    :param parent_updated: The updated parent payload (may include a new
        ``name``).
    :type parent_updated: dict[str, Any]
    :param derived_existing_names: Current derived task names, aligned with
        ``derived_specs`` by index.
    :type derived_existing_names: list[str]
    :param derived_specs: The derived-task specs to cascade.
    :type derived_specs: Sequence[DerivedTask]
    :return: A :class:`CascadeResult` recording per-leg outcomes.
    :rtype: CascadeResult
    :raises ValueError: When ``len(derived_existing_names) != len(derived_specs)``.
    """
    if len(derived_existing_names) != len(derived_specs):
        raise ValueError(
            f"derived_existing_names length {len(derived_existing_names)} "
            f"does not match derived_specs length {len(derived_specs)}"
        )
    result = CascadeResult()
    try:
        await tasks_api.put(f"/{parent_existing_name}", json=parent_updated)
        result.successes.append(parent_updated["name"])
    except Exception as exc:  # noqa: BLE001
        result.failures.append(CascadeFailure(parent_existing_name, exc))
    for existing_name, spec in zip(derived_existing_names, derived_specs, strict=True):
        child_payload = build_derived_payload(parent_updated, spec)
        try:
            await tasks_api.put(f"/{existing_name}", json=child_payload)
            result.successes.append(child_payload["name"])
        except Exception as exc:  # noqa: BLE001
            result.failures.append(CascadeFailure(existing_name, exc))
    return result


async def cascade_delete_tasks(
    tasks_api: RemoteAPI,
    parent_name: str,
    derived_specs: Sequence[DerivedTask],
) -> CascadeResult:
    """DELETE every derived task first, then the parent, best-effort.

    HTTP 404 on any leg is tolerated as success — the desired end state
    (the task is absent) is already achieved. All other failures accumulate
    into the returned :class:`CascadeResult`.

    :param tasks_api: The :class:`RemoteAPI` for the tasks sub-app.
    :type tasks_api: RemoteAPI
    :param parent_name: The name of the parent task.
    :type parent_name: str
    :param derived_specs: The derived-task specs whose names are derived from
        ``parent_name`` plus each spec's ``name_suffix``.
    :type derived_specs: Sequence[DerivedTask]
    :return: A :class:`CascadeResult` recording per-leg outcomes.
    :rtype: CascadeResult
    """
    result = CascadeResult()
    for spec in derived_specs:
        child_name = f"{parent_name}{spec.name_suffix}"
        await _delete_one(tasks_api, child_name, result)
    await _delete_one(tasks_api, parent_name, result)
    return result


async def _delete_one(
    tasks_api: RemoteAPI, task_name: str, result: CascadeResult
) -> None:
    """Issue one DELETE, tolerate 404, and record other failures on ``result``.

    :param tasks_api: The :class:`RemoteAPI` for the tasks sub-app.
    :type tasks_api: RemoteAPI
    :param task_name: The task name to DELETE.
    :type task_name: str
    :param result: The :class:`CascadeResult` to update in place.
    :type result: CascadeResult
    """
    try:
        await tasks_api.delete(f"/{task_name}")
        result.successes.append(task_name)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            result.successes.append(task_name)
        else:
            result.failures.append(CascadeFailure(task_name, exc))
    except Exception as exc:  # noqa: BLE001
        result.failures.append(CascadeFailure(task_name, exc))
