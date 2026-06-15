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

"""Decompose a task-app create payload into Resolve, Assemble, and Envelope.

The three-phase split keeps the per-app logic pure: :func:`resolve_refs` walks
the create model's reference markers and fetches the selected inventory entities
(the only step that touches the inventory API), the app's spec builder turns the
form plus resolved entities into a :class:`RunCommandSpec` / :class:`RunPythonSpec`
(a pure function), and :func:`assemble_envelope` maps a spec plus the resolved
service to a :class:`~app.tasks.models.TaskWrite` whose ``data`` dict is
byte-uniform with the canonical hand-written envelopes in
``checksums/deps.py`` (run-command) and ``backup_pg/deps.py`` (run-python).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast

from app.core.exceptions import HTTPBadRequestException
from app.inventory.constants import DEFAULT_MYSQL_PORT, DEFAULT_POSTGRESQL_PORT
from app.inventory.models import ServiceTypeEnum
from app.sep.connectivity import (
    CONNECTIVITY_META_HOST_KEY,
    CONNECTIVITY_META_PORT_KEY,
    CONNECTIVITY_META_SERVICE_TYPE_KEY,
)
from app.sep.deps import get_created_entity, InventoryAPI
from app.sep.inventory import CreatedEntity, CreatedService
from app.sep.models import SyncInventoryEntityTypeEnum
from app.sep.plugins.framework.form_dsl import (
    AppFormModel,
    find_ref_marker,
    SchemaRef,
    ServiceRef,
    TableRef,
)
from app.tasks.models import TaskBackendEnum, TaskOwner, TaskWrite

__all__ = [
    "ResolvedEntities",
    "RunCommandSpec",
    "RunPythonSpec",
    "assemble_envelope",
    "resolve_refs",
]

_REF_ENTITY_TYPES = {
    ServiceRef: SyncInventoryEntityTypeEnum.SERVICE,
    SchemaRef: SyncInventoryEntityTypeEnum.SCHEMA,
    TableRef: SyncInventoryEntityTypeEnum.TABLE,
}

_DEFAULT_PORTS = {
    ServiceTypeEnum.MYSQL: DEFAULT_MYSQL_PORT,
    ServiceTypeEnum.POSTGRESQL: DEFAULT_POSTGRESQL_PORT,
}


@dataclass(frozen=True, slots=True)
class RunCommandSpec:
    """Carry the spec-specific meta for a ``run-command`` task envelope.

    :param command: The executable name placed under ``meta.command``.
    :param args: The already-``shlex.join``'d argument string under ``meta.args``.
    :param extra_meta: Additional meta keys (for example ``_service_host`` /
        ``_service_port``) merged after ``_service_name`` and before the
        connectivity keys. Defaults to an empty mapping.
    """

    command: str
    args: str
    extra_meta: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RunPythonSpec:
    """Carry the spec-specific meta for a ``run-python`` task envelope.

    :param config: The serialized task config placed under ``meta.config``.
    :param requirements: The pip requirements string under ``meta.requirements``.
    :param payload: The ``file://`` payload URI placed at ``data.payload``.
    :param extra_meta: Additional meta keys merged after ``_service_name`` and
        before the connectivity keys. Defaults to an empty mapping.
    """

    config: str
    requirements: str
    payload: str
    extra_meta: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ResolvedEntities:
    """Hold the inventory entities resolved from a create form's reference fields.

    :param service: The entity resolved from the form's ``ServiceRef`` field, used
        for the envelope's connectivity meta and target; ``None`` when no service
        ref resolved (an empty or free-typed selection).
    :param entities: The resolved entity per reference-field name, ``None`` for an
        empty or free-typed (manual-name) selection. Excludes ``HostRef`` fields,
        which name an executor host rather than an inventory entity.
    """

    service: CreatedService | None
    entities: Mapping[str, CreatedEntity | None]


async def _resolve_ref(
    inventory_api: InventoryAPI,
    ref: ServiceRef | SchemaRef | TableRef,
    entity_type: SyncInventoryEntityTypeEnum,
    entity_id: int,
) -> CreatedEntity:
    """Fetch one referenced entity, enforcing a multi-type ``ServiceRef`` contract.

    A single-type ``ServiceRef`` reuses :func:`get_created_entity`'s built-in
    equality filter; a multi-type one fetches without a type filter and then
    asserts the resolved service's type is within the allowed tuple rather than
    silently trusting an out-of-contract id.

    :param inventory_api: The inventory API client.
    :param ref: The field's reference marker.
    :param entity_type: The inventory entity type the marker maps to.
    :param entity_id: The selected entity id from the form.
    :return: The resolved entity.
    :raises ValueError: When a single-type ``ServiceRef``'s service has the wrong
        type (raised inside :func:`get_created_entity`).
    :raises HTTPBadRequestException: When a multi-type ``ServiceRef``'s service has
        a type outside the allowed tuple.
    """
    if isinstance(ref, ServiceRef) and len(ref.service_types) == 1:
        return await get_created_entity(
            inventory_api, entity_type, entity_id, type=ref.service_types[0]
        )

    entity = await get_created_entity(inventory_api, entity_type, entity_id)
    if isinstance(ref, ServiceRef):
        service = cast(CreatedService, entity)
        if service.type not in ref.service_types:
            raise HTTPBadRequestException(
                f"service {entity_id} has type {service.type.value!r}, which is "
                f"outside the allowed types {[t.value for t in ref.service_types]}"
            )
    return entity


async def resolve_refs(
    form: AppFormModel, inventory_api: InventoryAPI
) -> ResolvedEntities:
    """Resolve a create form's ``ServiceRef`` / ``SchemaRef`` / ``TableRef`` fields.

    Walk the model's fields, fetch the inventory entity selected by each
    reference field, and collect them keyed by field name. An empty selection or
    a free-typed (``allow_custom``) value that arrives as a string resolves to
    ``None`` so the spec builder can fall back to the raw form value. ``HostRef``
    fields are skipped — they name an executor host, not an inventory entity.

    :param form: The validated create form instance.
    :param inventory_api: The inventory API client.
    :return: The resolved entities and the resolved service (if any).
    :raises ValueError: Propagated from :func:`get_created_entity` on a
        single-type ``ServiceRef`` type mismatch.
    :raises HTTPBadRequestException: When a multi-type ``ServiceRef`` resolves to a
        service outside its allowed types.
    """
    entities = {}
    service = None
    for name, field_info in type(form).model_fields.items():
        ref = find_ref_marker(list(field_info.metadata))
        if not isinstance(ref, ServiceRef | SchemaRef | TableRef):
            continue

        value = getattr(form, name, None)
        if isinstance(value, bool) or not isinstance(value, int):
            entities[name] = None
            continue

        entity = await _resolve_ref(
            inventory_api, ref, _REF_ENTITY_TYPES[type(ref)], value
        )
        entities[name] = entity
        if isinstance(ref, ServiceRef):
            service = cast(CreatedService, entity)
    return ResolvedEntities(service=service, entities=entities)


def assemble_envelope(
    spec: RunCommandSpec | RunPythonSpec,
    resolved: ResolvedEntities,
    *,
    name: str,
    owner: TaskOwner,
    alert_on_fail: bool = False,
) -> TaskWrite:
    """Assemble a ``TaskWrite`` from a spec and the resolved service.

    Map the uniform meta (``target``, ``_service_name``, and the connectivity
    keys) from the resolved service exactly as the canonical envelopes do —
    ``target`` and the connectivity host from the service node's address, the
    connectivity port from ``service.port`` falling back to the per-type default,
    and the connectivity service type from the service's type. The spec supplies
    the verb-specific keys (``command`` / ``args`` and any ``extra_meta`` for
    run-command; ``config`` / ``requirements`` / ``payload`` for run-python).

    :param spec: The verb-specific spec produced by the app's spec builder.
    :param resolved: The resolved inventory entities, whose service drives the
        connectivity meta and target.
    :param name: The task name.
    :param owner: The task owner.
    :param alert_on_fail: Whether to alert on task failure. Defaults to ``False``.
    :return: The assembled ``TaskWrite``, ready to POST to the Tasks API.
    :raises ValueError: When no service was resolved (the connectivity meta has no
        source).
    :raises TypeError: When ``spec`` is neither a ``RunCommandSpec`` nor a
        ``RunPythonSpec``.
    """
    service = resolved.service
    if service is None:
        raise ValueError(
            "assemble_envelope requires a resolved service to derive the "
            "connectivity meta; resolve_refs found no ServiceRef selection"
        )

    host = service.node.address
    connectivity = {
        CONNECTIVITY_META_HOST_KEY: host,
        CONNECTIVITY_META_PORT_KEY: service.port or _DEFAULT_PORTS.get(service.type),
        CONNECTIVITY_META_SERVICE_TYPE_KEY: service.type.value,
    }

    if isinstance(spec, RunCommandSpec):
        data = {
            "task": "run-command",
            "meta": {
                "command": spec.command,
                "args": spec.args,
                "target": host,
                "_service_name": service.name,
                **spec.extra_meta,
                **connectivity,
            },
        }
    elif isinstance(spec, RunPythonSpec):
        data = {
            "task": "run-python",
            "meta": {
                "config": spec.config,
                "target": host,
                "requirements": spec.requirements,
                "_service_name": service.name,
                **spec.extra_meta,
                **connectivity,
            },
            "payload": spec.payload,
        }
    else:
        raise TypeError(
            f"assemble_envelope: spec must be a RunCommandSpec or RunPythonSpec; "
            f"got {type(spec).__name__}"
        )

    return TaskWrite(
        name=name,
        owner=owner,
        backend=TaskBackendEnum.PROXY,
        data=data,
        alert_on_fail=alert_on_fail,
    )
