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

"""Cascade POST/PUT/DELETE across a parent task and its derived/predecessor tasks."""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Literal, TYPE_CHECKING

from app.core.exceptions import HTTPInternalServerErrorException, HTTPNotFoundException
from app.sep.apps.framework.spec import RESERVED_FORM_KEY

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.core.requests.remote_api import RemoteAPI
    from app.sep.apps.framework.schema import ChainedPredecessor, DerivedTask

__all__ = [
    "CascadeFailure",
    "CascadeResult",
    "build_derived_payload",
    "build_predecessor_chain_execute_body",
    "build_predecessor_payload",
    "cascade_create_independent_tasks",
    "cascade_create_predecessors",
    "cascade_create_tasks",
    "cascade_delete_predecessors",
    "cascade_delete_tasks",
    "cascade_update_predecessors",
    "cascade_update_tasks",
]

logger = logging.getLogger(__name__)

_CASCADE_PARTIAL_FAILURE_MESSAGES: dict[str, str] = {
    "create": "Partial create failure; incomplete task group",
    "update": "Partial update failure; inconsistent task group",
    "delete": "Partial delete failure; orphaned tasks",
}


@dataclass(frozen=True, slots=True)
class CascadeFailure:
    """Represent one per-leg failure surfaced by a best-effort cascade.

    :param task_name: The name of the task whose operation failed.
    :type task_name: str
    :param exception: The exception raised by the underlying ``TaskAPI`` call.
    :type exception: BaseException
    """

    task_name: str
    exception: BaseException


@dataclass(slots=True)
class CascadeResult:
    """Represent the outcome of a best-effort PUT or DELETE cascade.

    :param successes: Names of tasks whose operation succeeded.
    :param failures: Per-leg failures collected without raising.
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

    def raise_if_failed(self, *, op: Literal["create", "update", "delete"]) -> None:
        """Raise HTTP 500 when the cascade collected one or more failures.

        :param op: The cascade operation that produced this result.
        :raises HTTPInternalServerErrorException: When ``self.failures`` is non-empty.
        """
        if self.success:
            return
        detail: dict[str, Any] = {
            "message": _CASCADE_PARTIAL_FAILURE_MESSAGES[op],
            "errors": {
                failure.task_name: str(failure.exception) for failure in self.failures
            },
        }
        raise HTTPInternalServerErrorException(detail=detail)


def build_derived_payload(
    parent_payload: dict[str, Any], derived_spec: DerivedTask
) -> dict[str, Any]:
    """Build the cascade payload for one derived task.

    Deep-copies ``parent_payload``, drops the parent's ``RESERVED_FORM_KEY``
    create-form stamp from the child's ``data`` (a derived task never prefills an
    edit form, so it must not carry the parent's stamp), suffixes ``name`` with
    ``derived_spec.name_suffix``, applies ``arg_substitutions`` literally to
    ``data["meta"]["args"]`` (when present and string-typed), applies
    ``payload_substitutions`` literally to ``data["payload"]`` (when present
    and string-typed), assigns each ``data_overrides`` entry directly onto
    ``data`` in iteration order, and sets ``data["parent"]`` when
    ``parent_link`` is true. The caller's ``parent_payload`` is never mutated.

    :param parent_payload: The parent task's serialised payload (typically
        ``parent.model_dump()``).
    :param derived_spec: The declarative spec for this derived task.
    :return: A new dict ready to POST or PUT as a task payload.
    """
    payload = copy.deepcopy(parent_payload)
    child_data = payload.get("data")
    if isinstance(child_data, dict):
        child_data.pop(RESERVED_FORM_KEY, None)
    parent_name = payload["name"]
    payload["name"] = f"{parent_name}{derived_spec.name_suffix}"
    if (
        derived_spec.arg_substitutions
        or derived_spec.payload_substitutions
        or derived_spec.data_overrides
        or derived_spec.parent_link
    ):
        data = payload.setdefault("data", {})
        _apply_arg_substitutions(data, derived_spec.arg_substitutions)
        _apply_payload_substitutions(data, derived_spec.payload_substitutions)
        if derived_spec.data_overrides:
            for key, value in derived_spec.data_overrides.items():
                data[key] = value
        if derived_spec.parent_link:
            data["parent"] = parent_name
    return payload


def _apply_arg_substitutions(
    data: dict[str, Any], substitutions: dict[str, str] | None
) -> None:
    """Apply literal ``str.replace`` substitutions to ``data["meta"]["args"]`` in place.

    No-op when ``substitutions`` is falsy, when ``data["meta"]`` is not a
    dict, or when ``data["meta"]["args"]`` is not a string.

    :param data: The derived payload's ``data`` mapping, mutated in place.
    :type data: dict[str, Any]
    :param substitutions: Ordered mapping of ``(old, new)`` literal
        substring pairs, applied in dict insertion order.
    :type substitutions: dict[str, str] | None
    """
    if not substitutions:
        return
    meta = data.get("meta")
    if not isinstance(meta, dict) or not isinstance(meta.get("args"), str):
        return
    args = meta["args"]
    for old, new in substitutions.items():
        args = args.replace(old, new)
    meta["args"] = args


def _apply_payload_substitutions(
    data: dict[str, Any], substitutions: dict[str, str] | None
) -> None:
    """Apply literal ``str.replace`` substitutions to ``data["payload"]`` in place.

    No-op when ``substitutions`` is falsy or when ``data["payload"]`` is
    not a string.

    :param data: The derived payload's ``data`` mapping, mutated in place.
    :type data: dict[str, Any]
    :param substitutions: Ordered mapping of ``(old, new)`` literal
        substring pairs, applied in dict insertion order.
    :type substitutions: dict[str, str] | None
    """
    if not substitutions:
        return
    payload_path = data.get("payload")
    if not isinstance(payload_path, str):
        return
    for old, new in substitutions.items():
        payload_path = payload_path.replace(old, new)
    data["payload"] = payload_path


async def cascade_create_tasks(
    tasks_api: RemoteAPI,
    parent_payload: dict[str, Any],
    derived_specs: Sequence[DerivedTask],
) -> None:
    """POST the parent then each derived task; roll back on any failure.

    Every task is POSTed to the Tasks API root (``/``), matching the
    project-wide TaskAPI convention. On any POST failure, already-created
    tasks are deleted in reverse creation order via ``DELETE /{task_name}``.
    A rollback DELETE that itself fails is logged at WARNING and the
    rollback loop continues; the original POST exception is what surfaces
    to the caller.

    :param tasks_api: The :class:`RemoteAPI` for the tasks sub-app.
    :type tasks_api: RemoteAPI
    :param parent_payload: The parent task's serialised payload.
    :type parent_payload: dict[str, Any]
    :param derived_specs: The list of derived-task specs to cascade.
    :type derived_specs: Sequence[DerivedTask]
    :raises Exception: Re-raises whatever exception ``tasks_api.post``
        produced (commonly :class:`fastapi.HTTPException` for non-2xx
        responses, but any transport-level error such as
        :class:`aiohttp.ClientError` or :class:`asyncio.TimeoutError` can
        propagate) after the rollback DELETEs complete.
    """
    created_names = []
    try:
        await tasks_api.post("/", json=parent_payload)
        created_names.append(parent_payload["name"])
        for spec in derived_specs:
            child_payload = build_derived_payload(parent_payload, spec)
            await tasks_api.post("/", json=child_payload)
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
    derived_existing_names: Sequence[str],
    derived_specs: Sequence[DerivedTask],
) -> CascadeResult:
    """PUT the parent and each derived task, best-effort.

    Each leg is attempted independently when the parent payload preserves
    the parent's existing ``name`` — per-leg failures are collected into the
    returned :class:`CascadeResult`. The PUT URL path uses the *existing*
    task name (per the Tasks API contract); the updated payload, including
    any new ``name``, goes in the body.

    When ``parent_updated["name"]`` differs from ``parent_existing_name``
    (a rename) **and** the parent PUT fails, the derived loop is **skipped**
    rather than executed best-effort: each derived child payload built from
    ``parent_updated`` would carry the new ``data["parent"]`` link, so
    applying it would point a successfully-PUT child at a parent task that
    was never renamed and does not exist under that name. The skipped legs
    surface as :class:`CascadeFailure` entries so the caller can observe
    them.

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
    :type derived_existing_names: Sequence[str]
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
    parent_failed = False
    try:
        await tasks_api.put(f"/{parent_existing_name}", json=parent_updated)
        result.successes.append(parent_updated["name"])
    except Exception as exc:  # noqa: BLE001
        result.failures.append(CascadeFailure(parent_existing_name, exc))
        parent_failed = True
    parent_renamed = parent_updated["name"] != parent_existing_name
    if parent_failed and parent_renamed:
        for existing_name in derived_existing_names:
            result.failures.append(
                CascadeFailure(
                    existing_name,
                    RuntimeError(
                        "Skipped derived PUT because the parent rename failed; "
                        "applying it would orphan the derived task under a "
                        "non-existent parent name."
                    ),
                )
            )
        return result
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
    derived_names: Sequence[str],
) -> CascadeResult:
    """DELETE every derived task first, then the parent, best-effort.

    The caller passes the *actual* derived task names rather than the
    declarative :class:`DerivedTask` specs: the cascade does not recompute
    names from ``parent_name`` + ``name_suffix`` because a previous partial
    rename could leave the stored derived names out of sync with the
    schema-suffix convention, and recomputing would silently 404 on
    orphaned children. The caller is expected to fetch the current children
    (for example via a ``parent`` foreign key lookup on the Tasks API)
    before invoking this helper.

    HTTP 404 on any leg is tolerated as success — the desired end state
    (the task is absent) is already achieved. All other failures accumulate
    into the returned :class:`CascadeResult`.

    :param tasks_api: The :class:`RemoteAPI` for the tasks sub-app.
    :type tasks_api: RemoteAPI
    :param parent_name: The name of the parent task.
    :type parent_name: str
    :param derived_names: The actual stored names of the derived tasks to
        delete, fetched by the caller.
    :type derived_names: Sequence[str]
    :return: A :class:`CascadeResult` recording per-leg outcomes.
    :rtype: CascadeResult
    """
    result = CascadeResult()
    for derived_name in derived_names:
        await _delete_one(tasks_api, derived_name, result)
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
    except HTTPNotFoundException:
        result.successes.append(task_name)
    except Exception as exc:  # noqa: BLE001
        result.failures.append(CascadeFailure(task_name, exc))


def build_predecessor_payload(
    parent_payload: dict[str, Any],
    predecessor_payload: dict[str, Any],
    predecessor_spec: ChainedPredecessor,
) -> dict[str, Any]:
    """Build the cascade payload for one chained predecessor.

    Deep-copies ``predecessor_payload``, overrides ``name`` with
    ``f"{parent_name}{spec.name_suffix}"`` so the schema-declared suffix is
    authoritative, and sets ``data["parent"]`` when ``parent_link`` is true.
    The caller's payloads are never mutated.

    :param parent_payload: The parent task's serialised payload (read-only
        here; the parent's ``name`` is used to derive the predecessor name).
    :type parent_payload: dict[str, Any]
    :param predecessor_payload: The predecessor task's plugin-built payload.
        The consuming plugin's POST handler constructs this imperatively.
    :type predecessor_payload: dict[str, Any]
    :param predecessor_spec: The declarative spec for this predecessor.
    :type predecessor_spec: ChainedPredecessor
    :return: A new dict ready to POST or PUT as a task payload.
    :rtype: dict[str, Any]
    """
    payload = copy.deepcopy(predecessor_payload)
    parent_name = parent_payload["name"]
    payload["name"] = f"{parent_name}{predecessor_spec.name_suffix}"
    if predecessor_spec.parent_link:
        payload.setdefault("data", {})["parent"] = parent_name
    return payload


def build_predecessor_chain_execute_body(
    parent_name: str,
    predecessor_specs: Sequence[ChainedPredecessor],
) -> dict[str, Any]:
    """Build the JSON body for ``POST /execute/{first_predecessor_name}``.

    The first predecessor in ``predecessor_specs`` is the execute target;
    ``chain_task_names`` lists any remaining predecessors followed by the
    parent. ``chain_on_failure`` is derived from the first spec's
    ``on_failure`` policy (``"continue"`` maps to ``True``, ``"halt"`` to
    ``False``).

    :param parent_name: The parent task name.
    :param predecessor_specs: Ordered predecessor specs (same order as
        :func:`cascade_create_predecessors`).
    :return: A dict with ``chain_task_names`` and ``chain_on_failure`` ready
        for the tasks sub-app execute endpoint.
    :raises ValueError: When ``predecessor_specs`` is empty.
    """
    if not predecessor_specs:
        raise ValueError(
            "build_predecessor_chain_execute_body requires at least one "
            "predecessor spec."
        )
    built_names = [f"{parent_name}{spec.name_suffix}" for spec in predecessor_specs]
    return {
        "chain_task_names": [*built_names[1:], parent_name],
        "chain_on_failure": predecessor_specs[0].on_failure == "continue",
    }


async def cascade_create_predecessors(
    tasks_api: RemoteAPI,
    parent_payload: dict[str, Any],
    predecessor_specs_with_payloads: Sequence[
        tuple[ChainedPredecessor, dict[str, Any]]
    ],
) -> None:
    """POST the parent then every predecessor; roll back on any failure.

    Cascade order (parent-first, matching :func:`cascade_create_tasks`):

    1. POST the parent to ``/``.
    2. POST each predecessor in declared order to ``/``. The payload is
       built via :func:`build_predecessor_payload` (``parent_link``
       applied, ``name`` suffixed from the parent's ``name``).

    Chain execution is not fired here. When the user (or plugin handler)
    starts the first predecessor, build the execute body via
    :func:`build_predecessor_chain_execute_body` and call
    ``POST /execute/{first_predecessor_name}``.

    Every task is POSTed to the Tasks API root (``/``). On any POST
    failure, already-created tasks are DELETEd in reverse creation order.
    A rollback DELETE that itself fails is logged at WARNING and the
    rollback loop continues; the original POST exception is what surfaces
    to the caller.

    The empty-predecessor case is a programmer error: the consuming
    plugin should call :func:`cascade_create_tasks` (or POST the parent
    directly) instead. :class:`ValueError` is raised so the misuse
    surfaces at test time rather than silently downgrading to a
    single-task POST.

    :param tasks_api: The :class:`RemoteAPI` for the tasks sub-app.
    :type tasks_api: RemoteAPI
    :param parent_payload: The parent task's serialised payload. The
        ``name`` key must be set before invocation — it is read to derive
        the predecessor names in step 2.
    :type parent_payload: dict[str, Any]
    :param predecessor_specs_with_payloads: Ordered list of
        ``(spec, predecessor_payload)`` tuples; the consuming plugin
        builds each predecessor payload.
    :type predecessor_specs_with_payloads:
        Sequence[tuple[ChainedPredecessor, dict[str, Any]]]
    :raises ValueError: When ``predecessor_specs_with_payloads`` is empty.
    :raises Exception: Re-raises whatever ``tasks_api.post`` produced
        (commonly :class:`fastapi.HTTPException`, but any transport-level
        error such as :class:`asyncio.TimeoutError` can propagate) after
        rollback DELETEs complete.
    """
    if not predecessor_specs_with_payloads:
        raise ValueError(
            "cascade_create_predecessors requires at least one predecessor; "
            "callers must not invoke this helper for schemas without predecessors."
        )
    created_names = []
    try:
        await tasks_api.post("/", json=parent_payload)
        created_names.append(parent_payload["name"])
        for spec, pred_payload in predecessor_specs_with_payloads:
            built = build_predecessor_payload(parent_payload, pred_payload, spec)
            await tasks_api.post("/", json=built)
            created_names.append(built["name"])
    except Exception:
        for task_name in reversed(created_names):
            try:
                await tasks_api.delete(f"/{task_name}")
            except Exception as rollback_exc:  # noqa: BLE001
                logger.warning(
                    "Rollback DELETE failed for %r during "
                    "cascade_create_predecessors rollback: %s",
                    task_name,
                    rollback_exc,
                )
        raise


async def cascade_create_independent_tasks(
    tasks_api: RemoteAPI,
    parent_payload: dict[str, Any],
    child_payloads: Sequence[dict[str, Any]],
) -> None:
    """POST the parent then each independent child; roll back on any failure.

    Unlike :func:`cascade_create_tasks`, the children are not derived from
    the parent via substitutions — each ``child_payload`` is fully built
    by the caller. Unlike :func:`cascade_create_predecessors`, children
    are not named via :func:`build_predecessor_payload` or linked with
    ``data["parent"]``.

    Every task is POSTed to the Tasks API root (``/``). On any POST
    failure, already-created tasks are DELETEd in reverse creation
    order. A rollback DELETE that itself fails is logged at WARNING
    and the rollback loop continues; the original POST exception is
    what surfaces to the caller.

    :param tasks_api: The :class:`RemoteAPI` for the tasks sub-app.
    :type tasks_api: RemoteAPI
    :param parent_payload: The parent task's serialised payload.
    :type parent_payload: dict[str, Any]
    :param child_payloads: The list of independently-built child
        payloads, POSTed in declared order.
    :type child_payloads: Sequence[dict[str, Any]]
    :raises Exception: Re-raises whatever exception ``tasks_api.post``
        produced after the rollback DELETEs complete.
    """
    created_names: list[str] = []
    try:
        await tasks_api.post("/", json=parent_payload)
        created_names.append(parent_payload["name"])
        for child in child_payloads:
            await tasks_api.post("/", json=child)
            created_names.append(child["name"])
    except Exception:
        for task_name in reversed(created_names):
            try:
                await tasks_api.delete(f"/{task_name}")
            except Exception as rollback_exc:  # noqa: BLE001
                logger.warning(
                    "Rollback DELETE failed for %r during "
                    "cascade_create_independent rollback: %s",
                    task_name,
                    rollback_exc,
                )
        raise


async def cascade_update_predecessors(
    tasks_api: RemoteAPI,
    parent_existing_name: str,
    parent_updated: dict[str, Any],
    predecessor_existing_names: Sequence[str],
    predecessor_specs_with_payloads: Sequence[
        tuple[ChainedPredecessor, dict[str, Any]]
    ],
) -> CascadeResult:
    """PUT the parent and each predecessor, best-effort.

    Each leg is attempted independently — per-leg failures are collected
    into the returned :class:`CascadeResult`. The PUT URL path uses the
    *existing* task name; the updated payload goes in the body.

    Renames are rejected upfront with :class:`ValueError`. The chain
    wiring fired at create time stores the task names verbatim in celery's
    execution request, and this helper does NOT re-fire ``POST /execute``.
    Renaming the parent or any predecessor would leave the stored chain
    referencing names that no longer resolve, so the next chained
    execution would 404. Consumers that need to rename tasks in a chain
    must tear down and rebuild it (delete-then-create cascade) rather
    than relying on this helper.

    :param tasks_api: The :class:`RemoteAPI` for the tasks sub-app.
    :type tasks_api: RemoteAPI
    :param parent_existing_name: The current name of the parent task
        (used in the PUT URL).
    :type parent_existing_name: str
    :param parent_updated: The updated parent payload. ``parent_updated["name"]``
        MUST equal ``parent_existing_name``.
    :type parent_updated: dict[str, Any]
    :param predecessor_existing_names: Current predecessor task names,
        aligned with ``predecessor_specs_with_payloads`` by index. Each
        name MUST equal the name produced by
        :func:`build_predecessor_payload` for the matching spec.
    :type predecessor_existing_names: Sequence[str]
    :param predecessor_specs_with_payloads: Ordered list of
        ``(spec, predecessor_payload)`` tuples.
    :type predecessor_specs_with_payloads:
        Sequence[tuple[ChainedPredecessor, dict[str, Any]]]
    :return: A :class:`CascadeResult` recording per-leg outcomes.
    :rtype: CascadeResult
    :raises ValueError: When
        ``len(predecessor_existing_names) != len(predecessor_specs_with_payloads)``,
        when ``parent_updated["name"] != parent_existing_name``, or when
        any built predecessor name differs from the matching existing name.
    """
    if len(predecessor_existing_names) != len(predecessor_specs_with_payloads):
        raise ValueError(
            f"predecessor_existing_names length {len(predecessor_existing_names)} "
            f"does not match predecessor_specs_with_payloads length "
            f"{len(predecessor_specs_with_payloads)}"
        )
    if parent_updated["name"] != parent_existing_name:
        raise ValueError(
            "cascade_update_predecessors does not support renaming the parent: "
            f"parent_updated['name']={parent_updated['name']!r} differs from "
            f"parent_existing_name={parent_existing_name!r}. The chain wired at "
            "create time stores task names verbatim and this helper does not "
            "re-fire POST /execute; rename via delete-then-create cascade instead."
        )
    built_predecessors = [
        (existing_name, build_predecessor_payload(parent_updated, pred_payload, spec))
        for existing_name, (spec, pred_payload) in zip(
            predecessor_existing_names,
            predecessor_specs_with_payloads,
            strict=True,
        )
    ]
    renamed_predecessors = [
        (existing_name, built["name"])
        for existing_name, built in built_predecessors
        if built["name"] != existing_name
    ]
    if renamed_predecessors:
        raise ValueError(
            "cascade_update_predecessors does not support renaming predecessors: "
            f"{renamed_predecessors!r}. The chain wired at create time stores "
            "task names verbatim and this helper does not re-fire POST /execute; "
            "rename via delete-then-create cascade instead."
        )
    result = CascadeResult()
    try:
        await tasks_api.put(f"/{parent_existing_name}", json=parent_updated)
        result.successes.append(parent_updated["name"])
    except Exception as exc:  # noqa: BLE001
        result.failures.append(CascadeFailure(parent_existing_name, exc))
    for existing_name, built in built_predecessors:
        try:
            await tasks_api.put(f"/{existing_name}", json=built)
            result.successes.append(built["name"])
        except Exception as exc:  # noqa: BLE001
            result.failures.append(CascadeFailure(existing_name, exc))
    return result


async def cascade_delete_predecessors(
    tasks_api: RemoteAPI,
    parent_name: str,
    predecessor_names: Sequence[str],
) -> CascadeResult:
    """DELETE every predecessor first, then the parent, best-effort.

    Identical contract to :func:`cascade_delete_tasks` (just named for
    the predecessor schema field). The caller passes the *actual* stored
    predecessor names — the cascade does not recompute names from
    ``name_suffix`` because a previous partial rename could leave the
    stored names out of sync with the schema-suffix convention, and
    recomputing would silently 404 on orphaned children.

    HTTP 404 on any leg is tolerated as success; all other failures
    accumulate into the returned :class:`CascadeResult`. Uses the shared
    :func:`_delete_one` helper.

    :param tasks_api: The :class:`RemoteAPI` for the tasks sub-app.
    :type tasks_api: RemoteAPI
    :param parent_name: The name of the parent task.
    :type parent_name: str
    :param predecessor_names: The actual stored names of the predecessor
        tasks, fetched by the caller.
    :type predecessor_names: Sequence[str]
    :return: A :class:`CascadeResult` recording per-leg outcomes.
    :rtype: CascadeResult
    """
    result = CascadeResult()
    for predecessor_name in predecessor_names:
        await _delete_one(tasks_api, predecessor_name, result)
    await _delete_one(tasks_api, parent_name, result)
    return result
