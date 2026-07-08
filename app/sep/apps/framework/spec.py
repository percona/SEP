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
``checksums/deps.py`` (run-command) and ``backup_pg/spec.py`` (run-python).
"""

import shlex
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, cast, Protocol

from app.core.exceptions import HTTPBadRequestException
from app.core.utils.cli_args import (
    arg_template_identifiers,
    is_value_arg_template,
    render_value_arg,
)
from app.inventory.constants import DEFAULT_MYSQL_PORT, DEFAULT_POSTGRESQL_PORT
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework.form_dsl import (
    AppFormModel,
    ArgFormat,
    find_ref_marker,
    HostRef,
    SchemaRef,
    ServiceRef,
    TableRef,
)
from app.sep.connectivity import (
    CONNECTIVITY_META_HOST_KEY,
    CONNECTIVITY_META_PORT_KEY,
    CONNECTIVITY_META_SERVICE_TYPE_KEY,
)
from app.sep.deps import get_created_entity, InventoryAPI
from app.sep.inventory import CreatedEntity, CreatedService
from app.sep.models import SyncInventoryEntityTypeEnum
from app.tasks.models import TaskBackendEnum, TaskOwner, TaskWrite

__all__ = [
    "RESERVED_FORM_KEY",
    "RUN_PYTHON_TASK",
    "EnvelopeSpec",
    "ResolvedEntities",
    "RunCommandSpec",
    "RunPythonSpec",
    "assemble_envelope",
    "build_command_args",
    "build_run_python_task",
    "parse_server_list_config",
    "resolve_refs",
    "stamp_form_input",
    "validate_arg_formats",
]

RESERVED_FORM_KEY = "_form"
_RUN_COMMAND_TASK = "run-command"
RUN_PYTHON_TASK = "run-python"

_REF_ENTITY_TYPES = {
    ServiceRef: SyncInventoryEntityTypeEnum.SERVICE,
    SchemaRef: SyncInventoryEntityTypeEnum.SCHEMA,
    TableRef: SyncInventoryEntityTypeEnum.TABLE,
}

_DEFAULT_PORTS = {
    ServiceTypeEnum.MYSQL: DEFAULT_MYSQL_PORT,
    ServiceTypeEnum.POSTGRESQL: DEFAULT_POSTGRESQL_PORT,
}


class EnvelopeSpec(Protocol):
    """Define the envelope contract implemented by task-verb specs."""

    def to_envelope_data(
        self, *, host: str, service_name: str, connectivity: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Return this spec as a Tasks API ``data`` envelope.

        :param host: The executor target host.
        :param service_name: The selected inventory service name.
        :param connectivity: The shared connectivity metadata keys.
        :return: The verb-specific ``TaskWrite.data`` payload.
        """


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

    def to_envelope_data(
        self, *, host: str, service_name: str, connectivity: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Return this run-command spec as a Tasks API ``data`` envelope.

        :param host: The executor target host.
        :param service_name: The selected inventory service name.
        :param connectivity: The shared connectivity metadata keys.
        :return: The run-command ``TaskWrite.data`` payload.
        """
        return {
            "task": _RUN_COMMAND_TASK,
            "meta": {
                "command": self.command,
                "args": self.args,
                "target": host,
                "_service_name": service_name,
                **self.extra_meta,
                **connectivity,
            },
        }


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

    def to_envelope_data(
        self, *, host: str, service_name: str, connectivity: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Return this run-python spec as a Tasks API ``data`` envelope.

        :param host: The executor target host.
        :param service_name: The selected inventory service name.
        :param connectivity: The shared connectivity metadata keys.
        :return: The run-python ``TaskWrite.data`` payload.
        """
        return {
            "task": RUN_PYTHON_TASK,
            "meta": {
                "config": self.config,
                "target": host,
                "requirements": self.requirements,
                "_service_name": service_name,
                **self.extra_meta,
                **connectivity,
            },
            "payload": self.payload,
        }


@dataclass(frozen=True, slots=True)
class ResolvedEntities:
    """Hold the inventory entities resolved from a create form's reference fields.

    :param service: The entity resolved from the form's ``ServiceRef`` field, used
        for the envelope's connectivity meta and as the executor-target fallback;
        ``None`` when no service ref resolved (an empty or free-typed selection).
    :param entities: The resolved entity per reference-field name, ``None`` for an
        empty or free-typed (manual-name) selection. Excludes ``HostRef`` fields,
        which name an executor host rather than an inventory entity.
    :param executor_host: The host captured from the form's ``HostRef`` field (the
        executor target), or ``None`` when the model declares no ``HostRef``.
    """

    service: CreatedService | None
    entities: Mapping[str, CreatedEntity | None]
    executor_host: str | None = None


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


def _iter_ref_fields(
    form: AppFormModel,
) -> Iterator[tuple[str, ServiceRef | SchemaRef | TableRef | HostRef, Any]]:
    """Yield ``(key, ref, value)`` for each reference field on ``form``.

    Walk the model's top-level fields, and for each discriminated-union (one-of)
    field recurse into the **active** branch instance, keying its reference leaves
    by the dotted ``f"{field}.{leaf}"`` name the schema derivation emits. The
    discriminator field carries no reference marker and is skipped; inactive
    branches are never visited, so a ref declared on a non-selected branch
    resolves to nothing.

    :param form: The validated create form instance.
    :yield: Each ``(qualified field name, marker, submitted value)`` tuple.
    """
    for name, field_info in type(form).model_fields.items():
        if field_info.discriminator is not None:
            branch = getattr(form, name, None)
            if branch is None:
                continue
            for leaf_name, leaf_info in type(branch).model_fields.items():
                ref = find_ref_marker(list(leaf_info.metadata))
                if ref is not None:
                    yield f"{name}.{leaf_name}", ref, getattr(branch, leaf_name, None)
            continue
        ref = find_ref_marker(list(field_info.metadata))
        if ref is not None:
            yield name, ref, getattr(form, name, None)


def _select_primary_service(
    candidates: list[tuple[ServiceRef, CreatedService | None]],
) -> CreatedService | None:
    """Select the primary (connectivity) service from the resolved service refs.

    A ``check_connectivity``-marked ref wins outright (the construction guard
    permits at most one). Otherwise fall back to the last ref that resolved to a
    real entity, preserving the pre-marker last-wins behaviour for the
    single-service apps that declare no marker.

    :param candidates: The ``(marker, resolved entity)`` pairs for every resolved
        ``ServiceRef`` field, in declaration order.
    :return: The primary service, or ``None`` when none resolved.
    """
    primary = None
    for ref, entity in candidates:
        if ref.check_connectivity:
            return entity
        if entity is not None:
            primary = entity
    return primary


async def resolve_refs(
    form: AppFormModel, inventory_api: InventoryAPI
) -> ResolvedEntities:
    """Resolve a create form's ``ServiceRef`` / ``SchemaRef`` / ``TableRef`` fields.

    Walk the model's fields — and the active branch of any discriminated-union
    (one-of) field — fetch the inventory entity selected by each reference field,
    and collect them keyed by field name (nested refs keyed by the dotted
    ``f"{field}.{leaf}"`` name). An empty selection or a free-typed
    (``allow_custom``) value that arrives as a string resolves to ``None`` so the
    spec builder can fall back to the raw form value. A ``HostRef`` field's
    submitted value (free-typed or selected) is captured as the executor host
    without an inventory call, coerced to ``str``; a model declaring more than one
    ``HostRef`` is rejected. The connectivity / primary service is the
    ``check_connectivity``-marked ``ServiceRef`` when present, else the sole
    resolved ``ServiceRef``.

    :param form: The validated create form instance.
    :param inventory_api: The inventory API client.
    :return: The resolved entities, the primary service (if any), and the
        captured executor host (``None`` when no ``HostRef`` is declared).
    :raises ValueError: When the model declares more than one ``HostRef`` field, when
        a ``HostRef`` field submits a multi-value (list/set) selection that cannot
        resolve to the single executor host, or propagated from
        :func:`get_created_entity` on a single-type ``ServiceRef`` type mismatch.
    :raises HTTPBadRequestException: When a multi-type ``ServiceRef`` resolves to a
        service outside its allowed types.
    """
    entities = {}
    executor_host = None
    host_field = None
    service_candidates = []
    for key, ref, value in _iter_ref_fields(form):
        if isinstance(ref, HostRef):
            if host_field is not None:
                raise ValueError(
                    "resolve_refs found more than one HostRef field "
                    f"({host_field!r} and {key!r}); a model names at most one "
                    "executor host"
                )
            if ref.multiple:
                raise ValueError(
                    f"resolve_refs received a multi-value HostRef selection for field "
                    f"{key!r}; a task envelope targets a single executor host and "
                    "cannot resolve one from a list — declare a single-value HostRef "
                    "for the executor target, or consume the multi-host list in a "
                    "custom payload_builder"
                )
            host_field = key
            executor_host = None if value is None else str(value)
            continue

        if isinstance(value, bool) or not isinstance(value, int):
            entity = None
        else:
            entity = await _resolve_ref(
                inventory_api, ref, _REF_ENTITY_TYPES[type(ref)], value
            )
        entities[key] = entity
        if isinstance(ref, ServiceRef):
            service_candidates.append((ref, cast("CreatedService | None", entity)))

    return ResolvedEntities(
        service=_select_primary_service(service_candidates),
        entities=entities,
        executor_host=executor_host,
    )


def assemble_envelope(
    spec: EnvelopeSpec,
    resolved: ResolvedEntities,
    *,
    name: str,
    owner: TaskOwner,
    alert_on_fail: bool = False,
    alert_detail_builder: str | None = None,
) -> TaskWrite:
    """Assemble a ``TaskWrite`` from a spec and the resolved entities.

    Map the uniform meta (``target``, ``_service_name``, and the connectivity
    keys) as the canonical envelopes do — ``target`` from the resolved executor
    host falling back to the service node's address, the connectivity host always
    from the service node's address, the connectivity port from ``service.port``
    falling back to the per-type default, and the connectivity service type from
    the service's type. The spec supplies the verb-specific keys (``command`` /
    ``args`` and any ``extra_meta`` for run-command; ``config`` / ``requirements``
    / ``payload`` for run-python).

    :param spec: The verb-specific envelope contract produced by the app's spec
        builder.
    :param resolved: The resolved inventory entities; the service drives the
        connectivity meta and the executor host drives ``target`` (falling back to
        the service address when no ``HostRef`` resolved).
    :param name: The task name.
    :param owner: The task owner.
    :param alert_on_fail: Whether to alert on task failure. Defaults to ``False``.
    :param alert_detail_builder: The ``"module:function"`` path of a plugin
        callable that enriches this task's failure alert, stamped onto the
        ``TaskWrite``. Defaults to ``None`` (no per-owner enrichment).
    :return: The assembled ``TaskWrite``, ready to POST to the Tasks API.
    :raises ValueError: When no service was resolved (the connectivity meta has no
        source), or when the resolved service declares no port and no default port
        is registered for its type.
    """
    service = resolved.service
    if service is None:
        raise ValueError(
            "assemble_envelope requires a resolved service to derive the "
            "connectivity meta; resolve_refs found no ServiceRef selection"
        )

    host = service.node.address
    target_host = resolved.executor_host or host
    port = service.port or _DEFAULT_PORTS.get(service.type)
    if port is None:
        raise ValueError(
            "assemble_envelope cannot resolve a connectivity port for service type "
            f"{service.type.value!r}: it declares no port and no default is "
            "registered for its type"
        )
    connectivity = {
        CONNECTIVITY_META_HOST_KEY: host,
        CONNECTIVITY_META_PORT_KEY: port,
        CONNECTIVITY_META_SERVICE_TYPE_KEY: service.type.value,
    }

    data = spec.to_envelope_data(
        host=target_host, service_name=service.name, connectivity=connectivity
    )

    return TaskWrite(
        name=name,
        owner=owner,
        backend=TaskBackendEnum.PROXY,
        data=data,
        alert_on_fail=alert_on_fail,
        alert_detail_builder=alert_detail_builder,
    )


def build_run_python_task(
    *,
    name: str,
    owner: TaskOwner,
    target: str,
    config: str,
    requirements: str,
    payload: str,
    service_name: str | None = None,
    extra_data: Mapping[str, Any] | None = None,
    alert_on_fail: bool = False,
) -> TaskWrite:
    """Assemble a connectivity-optional ``run-python`` ``TaskWrite``.

    The no-connectivity sibling of :func:`assemble_envelope`: emit the same
    ``run-python`` envelope shape without the connectivity meta keys, stamping
    ``_service_name`` only when ``service_name`` is not ``None`` and merging
    ``extra_data`` at the ``data`` top level for caller-specific data keys. Used by
    the task apps whose
    tasks resolve no ``ServiceRef`` and so cannot go through
    :func:`assemble_envelope`, which requires a service for its connectivity meta.

    :param name: The task name.
    :param owner: The task owner.
    :param target: The executor target host placed under ``meta.target``.
    :param config: The serialized task config placed under ``meta.config``.
    :param requirements: The pip requirements string under ``meta.requirements``.
    :param payload: The ``file://`` payload URI placed at ``data.payload``.
    :param service_name: The resolved inventory service name, stamped as
        ``meta._service_name`` only when not ``None``. Defaults to ``None``.
    :param extra_data: Extra top-level ``data`` keys merged after ``payload``.
        Defaults to ``None``.
    :param alert_on_fail: Whether to alert on task failure. Defaults to ``False``.
    :return: The assembled ``TaskWrite``, ready to POST to the Tasks API.
    :raises ValueError: When an ``extra_data`` key collides with a reserved
        top-level envelope key — ``task`` / ``meta`` / ``payload`` (the envelope
        structure) or ``_form`` (reserved for :func:`stamp_form_input`) — which
        would silently overwrite the envelope or later break the form stamp.
    """
    meta = {
        "config": config,
        "target": target,
        "requirements": requirements,
    }
    if service_name is not None:
        meta["_service_name"] = service_name
    data = {
        "task": RUN_PYTHON_TASK,
        "meta": meta,
        "payload": payload,
    }
    reserved_keys = {*data, RESERVED_FORM_KEY}
    for key, value in (extra_data or {}).items():
        if key in reserved_keys:
            raise ValueError(
                f"extra_data key {key!r} collides with a reserved top-level "
                "envelope key; callers may only add new top-level data keys"
            )
        data[key] = value
    return TaskWrite(
        name=name,
        owner=owner,
        backend=TaskBackendEnum.PROXY,
        data=data,
        alert_on_fail=alert_on_fail,
    )


def parse_server_list_config(
    task: Mapping[str, Any],
    server_config: Mapping[str, Any],
    all_servers_config: Mapping[str, Any],
    extra_fields: Mapping[str, Any],
) -> dict[str, Any]:
    """Rebuild a backup edit-form dict from a parsed ``SERVER_LIST`` config.

    The reverse of the create path: where :func:`assemble_envelope` writes the
    ``SERVER_LIST`` / ``ALL_SERVERS`` envelope, this reads the first server entry
    and the shared ``ALL_SERVERS`` block back into the flat dict a backup app's
    Jinja edit form is populated from. It owns the parts identical across the
    backup apps -- the common base fields, the S3/GSUTIL/RSYNC upload-target
    extraction keyed off ``server_config["UPLOAD"]``, and the catch-all loop that
    lowercases every remaining ``ALL_SERVERS`` key not already present.

    The caller has already parsed the YAML config -- it needs ``server_config``
    and ``all_servers_config`` to compute its own ``extra_fields`` -- so both are
    passed in rather than re-parsed here. ``extra_fields`` (the app-specific keys
    such as ``port``, ``alias``, or the encryption recipient) is merged before the
    catch-all loop so those explicit values win over any lowered ``ALL_SERVERS``
    fallback.

    :param task: The task data retrieved from the Tasks API; supplies ``name`` and
        the ``target`` hostname.
    :param server_config: The first ``SERVER_LIST`` entry.
    :param all_servers_config: The ``ALL_SERVERS`` block (empty dict when absent).
    :param extra_fields: App-specific result keys, merged ahead of the catch-all
        loop so they take precedence over lowered ``ALL_SERVERS`` fallbacks.
    :return: The flat dict used to repopulate the backup edit form.
    """
    result = {
        "name": task["name"],
        "hostname": task["data"]["meta"]["target"],
        "backup_type": server_config["BACKUP_TYPE"],
        "service_id": None,
        "host": server_config["HOST"],
        **extra_fields,
    }

    upload_providers = {
        provider.upper()
        for provider in server_config.get("UPLOAD", [])
        if isinstance(provider, str)
    }
    if "S3" in upload_providers:
        result["s3_bucket"] = all_servers_config.get("S3_BUCKET")
        result["s3_storage_class"] = all_servers_config.get("S3_STORAGE_CLASS")
        result["skip_s3_safety_check"] = all_servers_config.get(
            "SKIP_S3_SAFETY_CHECK", False
        )
    if "GSUTIL" in upload_providers:
        result["gs_bucket"] = all_servers_config.get("GS_BUCKET")
    if "RSYNC" in upload_providers:
        result["rsync_path"] = all_servers_config.get("RSYNC_PATH")

    for key, value in all_servers_config.items():
        if key.lower() not in result:
            result[key.lower()] = value

    return result


def stamp_form_input(write: TaskWrite, form: AppFormModel) -> None:
    """Persist the validated create-form body under ``write.data[RESERVED_FORM_KEY]``.

    Persist the create form verbatim so a derived ``PUT`` can prefill an edit form
    from it. The JSON-mode dump keeps enums and datetimes as round-trippable JSON
    scalars, since the stamped body is re-submitted through the derived ``PUT`` and
    must re-validate against the app's ``create_model``.

    :param write: The assembled task envelope whose ``data`` carries the stamp.
    :param form: The validated create-form instance to persist.
    :raises ValueError: When ``write.data`` already carries the reserved key,
        which means a spec builder populated it; stamping would silently
        overwrite that app-provided data.
    """
    if RESERVED_FORM_KEY in write.data:
        raise ValueError(
            f"task envelope data already carries the reserved key "
            f"{RESERVED_FORM_KEY!r}; a spec builder must not populate it"
        )
    write.data[RESERVED_FORM_KEY] = form.model_dump(mode="json")


def _find_arg_format(name: str, metadata: list[Any]) -> ArgFormat | None:
    """Return the field's single :class:`ArgFormat` marker, or ``None``.

    :param name: The field name, used in the error message.
    :param metadata: The field's ``FieldInfo.metadata`` list.
    :return: The ``ArgFormat`` marker, or ``None`` when the field declares none.
    :raises ValueError: When the field declares more than one ``ArgFormat`` marker.
    """
    found = [item for item in metadata if isinstance(item, ArgFormat)]
    if len(found) > 1:
        raise ValueError(
            f"field {name!r} declares {len(found)} ArgFormat markers; at most one "
            "is allowed per field"
        )
    return found[0] if found else None


def _resolve_arg_template(name: str, annotation: Any, marker: ArgFormat) -> str:
    """Return the field's explicit ``ArgFormat`` template, or derive it from the name.

    A templateless marker (``template is None``) derives the conventional shape from
    the field name and type: a non-``bool`` field becomes the value arg
    ``--<kebab-field-name>=${value}`` and a ``bool`` field becomes the flag
    ``--<kebab-field-name>``. A field declares an explicit template only when its CLI
    spelling diverges from its name.

    :param name: The field name, kebab-cased for the derived template.
    :param annotation: The field's resolved type, selecting the value-vs-flag shape.
    :param marker: The field's ``ArgFormat`` marker.
    :return: The explicit template, or the derived default when none was given.
    """
    if marker.template is not None:
        return marker.template
    flag = "--" + name.replace("_", "-")
    return flag if annotation is bool else f"{flag}=${{value}}"


def build_command_args(form: AppFormModel) -> list[str]:
    """Assemble the run-command argument list from the form's ``ArgFormat`` markers.

    Walk the form's fields in declaration order and emit all value args before all
    flag args, each group in field-declaration order. A value arg (template
    containing ``${value}``) is emitted only when its field value is truthy, with
    the value stringified, ``shlex.quote``'d, and substituted into the template; a
    flag arg (template without ``${value}``) is emitted verbatim only when its
    field value is ``True``. The ``shlex.quote`` → ``safe_substitute`` →
    ``shlex.split`` round-trip keeps a whitespace-bearing value a single token. A
    templateless ``ArgFormat`` derives ``--<kebab-field-name>=${value}`` for a
    non-``bool`` field and ``--<kebab-field-name>`` for a ``bool`` field.

    :param form: The validated create form whose fields carry the ``ArgFormat``
        markers.
    :return: The ordered argument list (value args then flag args), ready to follow
        any per-app prefix and be ``shlex.join``'d into ``meta.args``.
    """
    value_args = []
    flag_args = []
    for name, field_info in type(form).model_fields.items():
        marker = _find_arg_format(name, field_info.metadata)
        if marker is None:
            continue
        value = getattr(form, name)
        resolved = _resolve_arg_template(name, field_info.annotation, marker)
        if is_value_arg_template(resolved):
            if value:
                value_args.extend(render_value_arg(resolved, value))
            continue
        if value is True:
            flag_args.extend(shlex.split(resolved))
    return value_args + flag_args


def validate_arg_formats(model: type[AppFormModel]) -> None:
    """Reject an ``ArgFormat`` template :func:`build_command_args` would silently drop.

    Check each field's :class:`ArgFormat` marker against the value-vs-flag contract
    the assembler enforces: a template may carry only the ``${value}`` placeholder,
    and a flag template (no placeholder) must sit on a ``bool`` field. A typo'd
    placeholder or a flag template on a non-``bool`` field would otherwise fall
    through to the flag branch and be emitted only when the value is ``True`` —
    dropping the argument with no error — so this surfaces the misconfiguration at
    app construction instead of silently at task-creation time. A templateless
    marker derives its template from the field name and type, so it is always
    well-formed; only an explicit template can violate the contract.

    :param model: The create model whose fields' ``ArgFormat`` markers are validated.
    :raises ValueError: When a template carries a placeholder other than ``value``,
        or when a flag template is declared on a non-``bool`` field.
    """
    for name, field_info in model.model_fields.items():
        marker = _find_arg_format(name, field_info.metadata)
        if marker is None:
            continue
        template = _resolve_arg_template(name, field_info.annotation, marker)
        identifiers = arg_template_identifiers(template)
        unsupported = identifiers - {"value"}
        if unsupported:
            raise ValueError(
                f"field {name!r} ArgFormat template {template!r} uses "
                f"unsupported placeholder(s) {sorted(unsupported)}; a value arg uses "
                f"exactly ${{value}} and a flag uses none"
            )
        if not identifiers and field_info.annotation is not bool:
            raise ValueError(
                f"field {name!r} ArgFormat template {template!r} declares no "
                "value placeholder, so it is a flag emitted only when the field is "
                "True; a flag arg requires a bool field"
            )
