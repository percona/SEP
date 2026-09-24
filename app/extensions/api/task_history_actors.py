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

"""Declare PMM Extensions' task-history response types and resolve their actor fields.

The tasks service serves :class:`~app.tasks.models.TaskResponse` and
:class:`~app.tasks.models.TaskHistoryResponse` from its own routes, where the
actor fields hold user identifiers and the docstrings say so. PMM Extensions resolves those
identifiers to display names, so it publishes its own subclasses rather than a
contract that describes an identifier and returns a name.

The module deliberately does not import ``app.extensions.deps``, so an app models module
such as ``app.extensions.apps.tasks.models`` can reach these types without acquiring an
edge into the PMM Extensions request layer or a cycle back through it.
"""

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import SERVICE_PRINCIPAL_ID
from app.core.pagination import PaginatedResponse
from app.tasks.models import SYSTEM_USER, Task, TaskHistoryResponse, TaskResponse

__all__ = [
    "SYSTEM_ACTOR_LABELS",
    "TASK_ACTOR_FIELDS",
    "ExtensionsHistoryPayload",
    "ExtensionsHistoryPayloadRow",
    "ExtensionsHistoryPayloadTask",
    "ExtensionsTaskHistoryResponse",
    "ExtensionsTaskResponse",
    "resolve_actor",
    "resolve_history_payload_actors",
    "resolve_task_actors",
    "resolve_task_history_actors",
    "task_actor_fields",
]

#: Display text for the identifiers that stand for system-initiated work.
#: Keyed by the same identifiers :data:`~app.tasks.crud.SYSTEM_EXECUTOR_IDS`
#: filters on, which cannot carry the labels itself: it is a frozenset used as a
#: SQL predicate, and the two identifiers need different text.
SYSTEM_ACTOR_LABELS: dict[str, str] = {
    SYSTEM_USER: "System",
    str(SERVICE_PRINCIPAL_ID): "Service account",
}

#: The task fields that hold a user identifier and render as a display name.
TASK_ACTOR_FIELDS: tuple[str, ...] = ("created_by", "last_updated_by")

_ACTOR_DESCRIPTION = (
    "Display name for the actor: the provider's username when resolvable, a "
    "system label for system-initiated work, otherwise the stored identifier."
)


class ExtensionsTaskResponse(TaskResponse):
    """Represent a task definition as PMM Extensions serves it, with actors resolved.

    Differ from :class:`~app.tasks.models.TaskResponse` only in what the two
    actor fields carry.

    :param created_by: Display name for the task's creator: the provider's
        username when resolvable, a system label for system-initiated work,
        otherwise the stored identifier. ``None`` when none was recorded.
    :param last_updated_by: Display name for the user who last modified the
        task, resolved on the same terms as ``created_by``. ``None`` when none
        was recorded.
    """

    created_by: str | None = Field(description=_ACTOR_DESCRIPTION)
    last_updated_by: str | None = Field(description=_ACTOR_DESCRIPTION)


class ExtensionsTaskHistoryResponse(TaskHistoryResponse):
    """Represent a task-history row as PMM Extensions serves it, with actors resolved.

    :param task: The task this execution belongs to, carrying resolved actors.
    :param executed_by: Display name for the actor that ran the task: the
        provider's username when resolvable, a system label for
        system-initiated work, otherwise the stored identifier. ``None`` when
        none was recorded.
    """

    task: ExtensionsTaskResponse
    executed_by: str | None = Field(default=None, description=_ACTOR_DESCRIPTION)


class _HistoryPassthroughModel(BaseModel):
    """Keep unrecognized upstream keys on the history passthrough models.

    History passthrough models declare only the keys the actor rewrite reads.
    ``extra="allow"`` preserves every other upstream key. Call sites dump with
    ``exclude_unset=True`` (and the detail route sets
    ``response_model_exclude_unset``) so an absent actor key stays absent
    rather than becoming ``null``.
    """

    model_config = ConfigDict(extra="allow")


class ExtensionsHistoryPayloadTask(_HistoryPassthroughModel):
    """Carry the nested-task actor fields the history rewrite may resolve.

    :param created_by: Actor for the nested task's creator. Typed as ``Any`` so
        an unexpected upstream shape validates and round-trips unchanged.
    :param last_updated_by: Actor for the nested task's last updater, on the
        same permissive terms as ``created_by``.
    """

    created_by: Any = None
    last_updated_by: Any = None


class ExtensionsHistoryPayloadRow(_HistoryPassthroughModel):
    """Carry one history-page row's fields the actor rewrite may resolve.

    A non-mapping ``task`` stays on the ``Any`` arm so the row still validates
    and its own ``executed_by`` can resolve. Unknown upstream keys survive via
    ``extra="allow"``.

    :param executed_by: Actor that ran the task. Typed as ``Any`` so an
        unexpected shape validates and is left alone by the rewrite.
    :param task: Nested task carrying actor fields when it is a mapping;
        otherwise the raw upstream value.
    """

    executed_by: Any = None
    task: ExtensionsHistoryPayloadTask | Any = None


class ExtensionsHistoryPayload(_HistoryPassthroughModel):
    """Represent the PMM Extensions task-history page envelope with passthrough extras.

    Declare only ``items``: ``total``, ``offset``, ``limit``, and any other
    upstream keys round-trip through ``extra="allow"`` without int coercion.
    ``items`` accepts a list of typed rows or non-mapping fallbacks, or any
    non-list upstream value so a bad page shape does not fail validation.

    :param items: The page's rows when upstream sent a list; otherwise the raw
        upstream value (including absence, via ``exclude_unset`` on dump).
    """

    items: list[ExtensionsHistoryPayloadRow | Any] | Any = None


def resolve_actor(actor: str | None, username_map: Mapping[str, str]) -> str | None:
    """Resolve one actor identifier to the text a reader should see.

    Consult :data:`SYSTEM_ACTOR_LABELS` ahead of the provider map, so a system
    identifier renders as its label whatever the provider happens to return.

    :param actor: The stored identifier, or ``None`` when none was recorded.
    :param username_map: The active provider's identifier-to-username map.
    :return: The system label, the provider's username, or the identifier
        unchanged when neither resolves it.
    """
    if actor is None:
        return None
    system_label = SYSTEM_ACTOR_LABELS.get(actor)
    if system_label is not None:
        return system_label
    return username_map.get(actor, actor)


def task_actor_fields(
    task: Task | TaskResponse, username_map: Mapping[str, str]
) -> dict[str, str | None]:
    """Resolve a task's actor fields to display text for a response's extras.

    :param task: The task whose stored actor identifiers are resolved.
    :param username_map: The active provider's identifier-to-username map.
    :return: Each field in :data:`TASK_ACTOR_FIELDS` mapped to its display text.
    """
    return {
        field: resolve_actor(getattr(task, field), username_map)
        for field in TASK_ACTOR_FIELDS
    }


def resolve_task_actors(
    task: ExtensionsTaskResponse, username_map: Mapping[str, str]
) -> ExtensionsTaskResponse:
    """Rewrite both actor fields on one task definition, in place.

    :param task: The validated task, rewritten in place.
    :param username_map: The active provider's identifier-to-username map.
    :return: The same task, for use as a call site's expression.
    """
    for field, value in task_actor_fields(task, username_map).items():
        setattr(task, field, value)
    return task


def resolve_task_history_actors(
    page: PaginatedResponse[ExtensionsTaskHistoryResponse],
    username_map: Mapping[str, str],
) -> PaginatedResponse[ExtensionsTaskHistoryResponse]:
    """Rewrite every actor identifier on a task-history page to display text.

    Cover the row's own executor and both actors on its nested task, so no
    actor field is left unresolved where the provider can resolve it. An actor
    the provider does not know keeps its stored identifier.

    :param page: The validated page, rewritten in place.
    :param username_map: The active provider's identifier-to-username map.
    :return: The same page, for use as a route's return expression.
    """
    for item in page.items:
        item.executed_by = resolve_actor(item.executed_by, username_map)
        resolve_task_actors(item.task, username_map)
    return page


def _resolve_payload_actor_key(
    row: _HistoryPassthroughModel, key: str, username_map: Mapping[str, str]
) -> None:
    """Resolve one actor key of a passthrough row or nested task in place.

    Leave the value alone unless it was supplied and is a string or ``None``: the
    permissive models accept any JSON shape, and an unhashable one would raise
    from the map lookup rather than degrade. Skip keys that were never set so
    serialization does not invent an absent actor field.

    :param row: The typed row or nested task, rewritten in place.
    :param key: The actor key to resolve, ignored when the row does not carry it.
    :param username_map: The active provider's identifier-to-username map.
    """
    if key not in row.model_fields_set:
        return
    value = getattr(row, key)
    if value is not None and not isinstance(value, str):
        return
    setattr(row, key, resolve_actor(value, username_map))


def resolve_history_payload_actors(
    payload: ExtensionsHistoryPayload, username_map: Mapping[str, str]
) -> ExtensionsHistoryPayload:
    """Rewrite actor identifiers inside a typed task-history payload.

    Skip any row, any nested task, and any actor value whose shape is not the
    expected one: an unexpected upstream shape degrades that field to its raw
    value rather than failing the whole page. Unknown upstream keys survive on
    the envelope and each row via ``extra="allow"``.

    :param payload: The validated upstream page, rewritten in place.
    :param username_map: The active provider's identifier-to-username map.
    :return: The same payload, for use as a call site's expression.
    """
    if "items" not in payload.model_fields_set or not isinstance(payload.items, list):
        return payload
    for item in payload.items:
        if not isinstance(item, ExtensionsHistoryPayloadRow):
            continue
        _resolve_payload_actor_key(item, "executed_by", username_map)
        if "task" not in item.model_fields_set or not isinstance(
            item.task, ExtensionsHistoryPayloadTask
        ):
            continue
        for key in TASK_ACTOR_FIELDS:
            _resolve_payload_actor_key(item.task, key, username_map)
    return payload
