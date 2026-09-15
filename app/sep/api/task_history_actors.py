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

"""Declare SEP's task-history response types and resolve their actor fields.

The tasks service serves :class:`~app.tasks.models.TaskResponse` and
:class:`~app.tasks.models.TaskHistoryResponse` from its own routes, where the
actor fields hold user identifiers and the docstrings say so. SEP resolves those
identifiers to display names, so it publishes its own subclasses rather than a
contract that describes an identifier and returns a name.

The module deliberately does not import ``app.sep.deps``, so an app models module
such as ``app.sep.apps.tasks.models`` can reach these types without acquiring an
edge into the SEP request layer or a cycle back through it.
"""

from collections.abc import Mapping
from typing import Any

from pydantic import Field

from app.api.deps import SERVICE_PRINCIPAL_ID
from app.core.pagination import PaginatedResponse
from app.tasks.models import SYSTEM_USER, TaskHistoryResponse, TaskResponse

__all__ = [
    "SYSTEM_ACTOR_LABELS",
    "SepTaskHistoryResponse",
    "SepTaskResponse",
    "resolve_actor",
    "resolve_history_payload_actors",
    "resolve_task_actors",
    "resolve_task_history_actors",
]

#: Display text for the identifiers that stand for system-initiated work.
#: Keyed by the same identifiers :data:`~app.tasks.crud.SYSTEM_EXECUTOR_IDS`
#: filters on, which cannot carry the labels itself: it is a frozenset used as a
#: SQL predicate, and the two identifiers need different text.
SYSTEM_ACTOR_LABELS: dict[str, str] = {
    SYSTEM_USER: "System",
    str(SERVICE_PRINCIPAL_ID): "Service account",
}

_ACTOR_DESCRIPTION = (
    "Display name for the actor: the provider's username when resolvable, a "
    "system label for system-initiated work, otherwise the stored identifier."
)


class SepTaskResponse(TaskResponse):
    """Represent a task definition as SEP serves it, with actors resolved.

    Differ from :class:`~app.tasks.models.TaskResponse` only in what the two
    actor fields carry.

    :param created_by: Display name for the task's creator, or ``None`` when
        none was recorded.
    :param last_updated_by: Display name for the user who last modified the
        task, or ``None`` when none was recorded.
    """

    created_by: str | None = Field(description=_ACTOR_DESCRIPTION)
    last_updated_by: str | None = Field(description=_ACTOR_DESCRIPTION)


class SepTaskHistoryResponse(TaskHistoryResponse):
    """Represent a task-history row as SEP serves it, with actors resolved.

    :param task: The task this execution belongs to, carrying resolved actors.
    :param executed_by: Display name for the actor that ran the task, or
        ``None`` when none was recorded.
    """

    task: SepTaskResponse
    executed_by: str | None = Field(default=None, description=_ACTOR_DESCRIPTION)


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


def resolve_task_actors(
    task: SepTaskResponse, username_map: Mapping[str, str]
) -> SepTaskResponse:
    """Rewrite both actor fields on one task definition, in place.

    :param task: The validated task, rewritten in place.
    :param username_map: The active provider's identifier-to-username map.
    :return: The same task, for use as a call site's expression.
    """
    task.created_by = resolve_actor(task.created_by, username_map)
    task.last_updated_by = resolve_actor(task.last_updated_by, username_map)
    return task


def resolve_task_history_actors(
    page: PaginatedResponse[SepTaskHistoryResponse],
    username_map: Mapping[str, str],
) -> PaginatedResponse[SepTaskHistoryResponse]:
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
    row: dict[str, Any], key: str, username_map: Mapping[str, str]
) -> None:
    """Resolve one actor key of an unvalidated row in place.

    Leave the value alone unless it is a string or ``None``: the row has not been
    through model validation, so a key can hold any JSON shape, and an unhashable
    one would raise from the map lookup rather than degrade.

    :param row: The unvalidated row or nested task, rewritten in place.
    :param key: The actor key to resolve, ignored when the row does not carry it.
    :param username_map: The active provider's identifier-to-username map.
    """
    if key not in row:
        return
    value = row[key]
    if value is not None and not isinstance(value, str):
        return
    row[key] = resolve_actor(value, username_map)


def resolve_history_payload_actors(
    payload: dict[str, Any], username_map: Mapping[str, str]
) -> dict[str, Any]:
    """Rewrite actor identifiers inside an untyped task-history payload.

    Operate on the raw mapping rather than validating it, so a passthrough
    surface keeps every upstream key it was given. Skip any row, any nested task,
    and any actor value whose shape is not the expected one: an unexpected
    upstream shape degrades that row to raw identifiers rather than failing the
    whole page.

    :param payload: The upstream page, rewritten in place.
    :param username_map: The active provider's identifier-to-username map.
    :return: The same mapping, for use as a call site's expression.
    """
    items = payload.get("items")
    if not isinstance(items, list):
        return payload
    for item in items:
        if not isinstance(item, dict):
            continue
        _resolve_payload_actor_key(item, "executed_by", username_map)
        task = item.get("task")
        if not isinstance(task, dict):
            continue
        for key in ("created_by", "last_updated_by"):
            _resolve_payload_actor_key(task, key, username_map)
    return payload
