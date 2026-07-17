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

"""Define dependencies for the Alters plugin."""

import copy
import json
import logging
import shlex
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends
from pydantic import BaseModel, ValidationError

from app.core.exceptions import (
    HTTPBadRequestException,
    HTTPConflictException,
    HTTPUnprocessableEntityException,
)
from app.core.requests.remote_api import RemoteAPI
from app.core.utils.fields import EmptyStrToNone
from app.core.utils.path import payload_uri
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.alters.models import (
    AltersCreate,
    AltersTaskResponse,
    AltersTaskResponseCreate,
    OWNER,
)
from app.sep.apps.alters.schema import alters_schema
from app.sep.apps.alters.spec import build_alters_spec
from app.sep.apps.framework import (
    build_default_task_response,
    ConnectivityWarning,
    make_parent_resolver,
    make_task_dep,
)
from app.sep.apps.framework.api import CascadeCreatePlan
from app.sep.apps.framework.cascade import (
    build_derived_payload,
    build_predecessor_payload,
    cascade_delete_tasks,
    cascade_update_tasks,
    CascadeFailure,
    CascadeResult,
)
from app.sep.apps.framework.form_dsl import (
    derive_arg_parser_from_model,
    make_arg_parser,
)
from app.sep.apps.framework.schema import ChainedPredecessor
from app.sep.apps.framework.spec import (
    assemble_envelope,
    resolve_refs,
)
from app.sep.deps import (
    check_for_conflicted_running_tasks,
    DefaultContext,
    ExecutorHostsCtx,
    get_tasks_context,
    get_username_mapping,
    InventoryAPI,
    reject_if_protected,
    TaskAPI,
)
from app.tasks.models import (
    Task,
    TaskHistoryStatusEnum,
    TaskWrite,
)

logger = logging.getLogger(__name__)


class AltersLegacyForm(BaseModel):
    """Parse the deprecated Alters HTML form's flat, urlencoded body.

    The Jinja create/edit templates submit the historical split target fields
    (``schema_id`` / ``schema_name`` / ``table_id`` / ``table_name``) that
    predate the free-solo collapse, so the derived ``AltersCreate`` cannot bind
    them directly. This model parses that flat body; :func:`map_alters_legacy_form`
    folds it into ``AltersCreate`` for the shared task builder, keeping the legacy
    path byte-identical. Field validation is enforced by the mapped
    ``AltersCreate``, not here.

    :param task_name: The task name.
    :param hostname: The executor host.
    :param service_id: The source MySQL service id.
    :param schema_id: The schema inventory id, or empty.
    :param schema_name: The manually-entered schema name.
    :param table_id: The table inventory id, or empty.
    :param table_name: The manually-entered table name.
    :param pre_checks_mysql_config_file: The MySQL defaults file path.
    :param alter: The pt-osc alter clause.
    :param recursion_method: The pt-osc recursion method.
    :param dsn_table: The DSN table (recursion method ``dsn``).
    :param print_arg: The ``--print`` flag.
    :param progress: The ``--progress`` value.
    :param no_swap_tables: The ``--no-swap-tables`` flag.
    :param no_drop_old_table: The ``--no-drop-old-table`` flag.
    :param no_drop_new_table: The ``--no-drop-new-table`` flag.
    :param no_drop_triggers: The ``--no-drop-triggers`` flag.
    :param pause_file: The ``--pause-file`` path.
    :param new_table_name: The ``--new-table-name`` value.
    :param tries: The ``--tries`` value.
    :param set_vars: The ``--set-vars`` value.
    :param critical_load: The ``--critical-load`` value.
    :param max_load: The ``--max-load`` value.
    :param chunk_time: The ``--chunk-time`` value.
    :param max_lag: The ``--max-lag`` value.
    :param max_flow_ctl: The ``--max-flow-ctl`` value.
    :param extra_args: Additional pt-osc CLI arguments.
    :param continue_on_pre_check_failure: The continue-on-pre-check-failure toggle.
    :param alert_on_fail: Whether to alert on failure.
    """

    task_name: str
    hostname: str
    service_id: int
    schema_id: int | EmptyStrToNone = None
    schema_name: str = ""
    table_id: int | EmptyStrToNone = None
    table_name: str = ""
    pre_checks_mysql_config_file: str = "~/.my.cnf"
    alter: str = ""
    recursion_method: str = "processlist"
    dsn_table: str = ""
    print_arg: bool = False
    progress: str = ""
    no_swap_tables: bool = False
    no_drop_old_table: bool = False
    no_drop_new_table: bool = False
    no_drop_triggers: bool = False
    pause_file: str | None = None
    new_table_name: str | None = None
    tries: str | None = None
    set_vars: str | None = None
    critical_load: str | None = None
    max_load: str | None = None
    chunk_time: str | None = None
    max_lag: str | None = None
    max_flow_ctl: str | None = None
    extra_args: str | None = None
    continue_on_pre_check_failure: bool = False
    alert_on_fail: bool = False


def _collapse(ref_id: int | None, name: str) -> int | str | None:
    """Collapse a legacy id/name pair into the single free-solo value.

    :param ref_id: The inventory id, or ``None`` when not selected.
    :param name: The manually-entered name (``""`` when not entered).
    :return: The id when present, else the trimmed name, else ``None``.
    """
    if ref_id is not None:
        return ref_id
    return name.strip() or None


def map_alters_legacy_form(flat: AltersLegacyForm) -> AltersCreate:
    """Fold the flat legacy form into the collapsed ``AltersCreate``.

    Collapses the split ``schema_id`` / ``schema_name`` and ``table_id`` /
    ``table_name`` pairs into the single free-solo ``db_schema`` / ``db_table``
    fields and validates through ``AltersCreate`` so the legacy path enforces the
    same rules as the JSON path. A validation failure surfaces as a 422, matching
    the framework's body-validation behaviour.

    :param flat: The parsed legacy form body.
    :return: The validated collapsed create model.
    :raises HTTPUnprocessableEntityException: When the folded model is invalid.
    """
    data = {
        **flat.model_dump(
            exclude={"schema_id", "schema_name", "table_id", "table_name"}
        ),
        "db_schema": _collapse(flat.schema_id, flat.schema_name),
        "db_table": _collapse(flat.table_id, flat.table_name),
    }
    try:
        return AltersCreate.model_validate(data)
    except ValidationError as exc:
        raise HTTPUnprocessableEntityException(detail=exc.errors()) from exc


async def build_alters_task(
    body: AltersCreate,
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build the parent alters execute task from a JSON payload.

    Resolves the ``service_id`` / ``db_schema`` / ``db_table`` reference fields
    through the framework resolver: an inventory id is fetched to its entity name,
    while a free-typed name falls back to the raw form value. The resolved
    entities and executor host then drive
    :func:`~app.sep.apps.alters.spec.build_alters_spec` and ``assemble_envelope``.

    :param body: The alters create/write payload.
    :param inventory_api: The Inventory API client.
    :return: A fully constructed parent execute ``TaskWrite``.
    :raises HTTPBadRequestException: When no MySQL service is resolved.
    """
    resolved = await resolve_refs(body, inventory_api)
    if resolved.service is None:
        raise HTTPBadRequestException("A MySQL service selection is required.")
    return assemble_envelope(
        build_alters_spec(body, resolved),
        resolved,
        name=body.task_name,
        owner=OWNER,
        alert_on_fail=body.alert_on_fail,
    )


get_alters_task = make_task_dep(OWNER)

AltersTask = Annotated[Task, Depends(get_alters_task)]


def get_alters_task_info(task: dict[str, Any]) -> dict[str, Any]:
    """Extract relevant information from a task for the Alters plugin.

    Processes the task data to extract hostname and table information.

    :param task: The task data retrieved from the Tasks API.
    :type task: dict[str, Any]
    :return: A dictionary containing hostname and table information.
    :rtype: dict[str, Any]
    """
    data = task["data"]
    meta = data["meta"]

    return {
        "hostname": meta["target"],
        "table": f"{meta['_schema_name']}.{meta['_table_name']}",
        "parent": data.get("parent"),
    }


def extract_service_info(meta: dict[str, Any]) -> dict[str, Any]:
    """Extract service information from task configuration.

    :param meta: The task meta containing service information and args string.
    :type meta: dict[str, Any]
    :return: A dictionary containing service_host, service_port, schema_name, and table_name.
    :rtype: dict[str, Any]
    """
    service_host = meta.get("_service_host", "")
    service_port = meta.get("_service_port", 0)
    schema_name = meta.get("_schema_name", "")
    table_name = meta.get("_table_name", "")

    if not service_host or service_port == 0:
        args_string = meta.get("args", "")
        if args_string:
            args = shlex.split(args_string)

            for task_arg in args:
                if "=" in task_arg and not task_arg.startswith("--"):
                    for param in task_arg.split(","):
                        if "=" in param:
                            key, value = param.split("=", 1)
                            if key == "h" and not service_host:
                                service_host = value
                            elif key == "P" and service_port == 0:
                                service_port = int(value)
    if service_host == "":
        service_host = "localhost"
    return {
        "service_host": service_host,
        "service_port": service_port,
        "schema_name": schema_name,
        "table_name": table_name,
    }


def alters_executor_matches_service_host(
    meta: dict[str, Any],
    executor_hosts: Any,
) -> bool:
    """Return whether the task executor is the same host as the MySQL service.

    Same rule as the alters detail page (pre-checks confirm dialog): resolve
    ``target`` via Nomad ``/hosts/`` (node name → address) and compare to
    ``extract_service_info`` host (inventory and/or DSN in ``args``).

    :param meta: Task ``meta`` (``target``, ``_service_host``, ``args``, etc.).
    :type meta: dict[str, Any]
    :param executor_hosts: Host map from ``GET /hosts/`` (node name → address),
        or a non-dict fallback where ``target`` is used as the address.
    :type executor_hosts: Any
    :return: ``True`` if the resolved executor address equals the service host.
    :rtype: bool
    """
    service_host = extract_service_info(meta)["service_host"]
    executor_target = meta.get("target") or ""
    if isinstance(executor_hosts, dict):
        executor_address = executor_hosts.get(executor_target, executor_target)
    else:
        executor_address = executor_target
    return executor_address == service_host


_PARENT_ONLY_META_KEYS = ("command", "args", "_command_line")


async def build_pre_checks_task_payload(
    base_task: TaskWrite,
    *,
    task_api: TaskAPI,
) -> TaskWrite:
    """Build the imperative pre-checks ``TaskWrite`` from the parent execute task.

    Transforms the parent ``run-command`` payload into ``run-python``, fetches
    executor hosts, composes inline YAML ``config``, and sets script
    requirements. The caller is responsible for naming and ``parent`` linkage
    (Jinja routes set these directly; cascade uses
    :func:`build_predecessor_payload`).

    :param base_task: The parent execute (pt-osc) task; copied on the return
        value only (``base_task`` is not mutated).
    :type base_task: TaskWrite
    :param task_api: Tasks API client (for ``GET /hosts/``).
    :type task_api: TaskAPI
    :return: Pre-checks task payload ready for POST or PUT.
    :rtype: TaskWrite
    """
    pre_checks_task = base_task.model_copy(deep=True)
    pre_checks_task.data["task"] = "run-python"
    meta = pre_checks_task.data["meta"]
    for key in _PARENT_ONLY_META_KEYS:
        meta.pop(key, None)
    db_host = meta.get("_service_host", "")
    db_port = meta.get("_service_port")
    executor_hosts = await task_api.get("/hosts/")
    skip_fs_checks = not alters_executor_matches_service_host(
        base_task.data["meta"], executor_hosts
    )
    pre_checks_config_lines = [
        f"schema: {meta['_schema_name']}",
        f"table: {meta['_table_name']}",
        f"host: {db_host or '127.0.0.1'}",
    ]
    if db_port is not None:
        pre_checks_config_lines.append(f"port: {db_port}")
    if skip_fs_checks:
        pre_checks_config_lines.append("skip_filesystem_checks: true")
    mysql_cnf = meta.get("_pre_checks_mysql_config_file") or "~/.my.cnf"
    pre_checks_config_lines.append(f"mysql_config_file: {json.dumps(mysql_cnf)}")
    pre_checks_task.data["meta"]["config"] = "\n".join(pre_checks_config_lines)
    pre_checks_task.data["meta"]["requirements"] = (
        "packaging\nPyYAML\nPyMySQL[rsa,ed25519]"
    )
    pre_checks_task.data["payload"] = payload_uri(__file__, "pre_checks.py")
    return pre_checks_task


_ALTERS_DEFAULTS = {
    "alter": "",
    "recursion_method": "processlist",
    "dsn_table": "",
    "pause_file": "",
    "new_table_name": "",
    "print_arg": False,
    "progress": "",
    "no_swap_tables": False,
    "no_drop_old_table": False,
    "no_drop_new_table": False,
    "no_drop_triggers": False,
    "tries": "",
    "set_vars": "",
    "critical_load": "",
    "max_load": "",
    "chunk_time": "",
    "max_lag": "",
    "max_flow_ctl": "",
    "extra_args": "",
}


def _alters_recursion_handler(arg: str, form_values: dict[str, Any]) -> bool:
    """Split ``--recursion-method=dsn=…`` into ``recursion_method`` and ``dsn_table``.

    :param arg: The CLI token to inspect.
    :param form_values: The in-progress form-value dict, updated in place.
    :return: ``True`` when ``arg`` is the ``--recursion-method=`` token (handled),
        ``False`` otherwise.
    """
    if not arg.startswith("--recursion-method="):
        return False
    recursion_method = arg.split("=", 1)[1]
    if recursion_method.startswith("dsn="):
        form_values["recursion_method"] = "dsn"
        dsn_value = recursion_method.split("=", 1)[1]
        dsn_parts = [
            part for part in dsn_value.split(",") if not part.startswith(("h=", "P="))
        ]
        form_values["dsn_table"] = ",".join(dsn_parts) if dsn_parts else dsn_value
    else:
        form_values["recursion_method"] = recursion_method
    return True


_ALTERS_ARG_MAPPINGS, _ALTERS_FLAG_MAPPINGS = derive_arg_parser_from_model(
    AltersCreate,
    extra_arg_mappings={"--alter=": "alter", "--progress=": "progress"},
)

parse_alters_task_args = make_arg_parser(
    defaults=_ALTERS_DEFAULTS,
    arg_mappings=_ALTERS_ARG_MAPPINGS,
    flag_mappings=_ALTERS_FLAG_MAPPINGS,
    recursion_handler=_alters_recursion_handler,
    drop_shaped_positionals=True,
    collect_extra_args=True,
    reserved_flags=frozenset({"--execute", "--dry-run"}),
)


def alters_derived_task_names(parent_name: str) -> list[str]:
    """Return stored derived task names for a parent alters task.

    :param parent_name: The parent execute task name.
    :type parent_name: str
    :return: Derived task names derived from ``alters_schema.derived``.
    :rtype: list[str]
    """
    return [f"{parent_name}{spec.name_suffix}" for spec in alters_schema.derived or []]


def alters_predecessor_task_names(parent_name: str) -> list[str]:
    """Return stored predecessor task names for a parent alters task.

    :param parent_name: The parent execute task name.
    :type parent_name: str
    :return: Predecessor task names derived from ``alters_schema.predecessors``.
    :rtype: list[str]
    """
    return [
        f"{parent_name}{spec.name_suffix}" for spec in alters_schema.predecessors or []
    ]


def alters_satellite_task_names(parent_name: str) -> list[str]:
    """Return all satellite task names (derived + predecessors) for a parent.

    :param parent_name: The parent execute task name.
    :type parent_name: str
    :return: Derived and predecessor task names for cascade delete.
    :rtype: list[str]
    """
    return alters_derived_task_names(parent_name) + alters_predecessor_task_names(
        parent_name
    )


def resolve_predecessor_specs(
    body: AltersCreate,
) -> list[ChainedPredecessor]:
    """Resolve chained-predecessor specs for cascade wiring, one per schema entry.

    Applies the user-overridable ``continue_on_pre_check_failure`` toggle on
    the first schema predecessor only (the alters pre-checks task).

    :param body: The alters create/write payload.
    :return: Ordered specs aligned with ``alters_schema.predecessors``.
    :rtype: list[ChainedPredecessor]
    """
    schema_predecessors = list(alters_schema.predecessors or [])
    if not schema_predecessors:
        raise ValueError("alters_schema must declare at least one predecessor")
    resolved: list[ChainedPredecessor] = []
    for index, schema_spec in enumerate(schema_predecessors):
        if index == 0 and body.continue_on_pre_check_failure:
            resolved.append(
                ChainedPredecessor(
                    name_suffix=schema_spec.name_suffix,
                    on_failure="continue",
                    parent_link=schema_spec.parent_link,
                )
            )
        else:
            resolved.append(schema_spec)
    return resolved


async def cascade_create_alters_group(
    tasks_api: RemoteAPI,
    parent_task: TaskWrite,
    pre_checks_template: TaskWrite,
    body: AltersCreate,
) -> None:
    """POST parent + dry-run + pre-checks; roll back on any failure.

    Atomically creates the three-task group. Chain execution is not fired
    here; the user starts pre-checks from the detail action bar (see
    :func:`~app.sep.apps.framework.cascade.build_predecessor_chain_execute_body`).

    :param tasks_api: The Tasks API client.
    :type tasks_api: RemoteAPI
    :param parent_task: The parent execute task payload.
    :type parent_task: TaskWrite
    :param pre_checks_template: The imperative pre-checks payload from
        :func:`build_pre_checks_task_payload`.
    :type pre_checks_template: TaskWrite
    :param body: The alters create/write payload (for ``continue_on_pre_check_failure``
        when resolving the predecessor spec).
    :type body: AltersCreate
    :raises Exception: Re-raises the underlying Tasks API error after rollback
        when one of the three task POSTs fails.
    """
    parent_payload = parent_task.model_dump()
    derived_specs = alters_schema.derived or []
    predecessor_spec = resolve_predecessor_specs(body)[0]

    created_names: list[str] = []
    predecessor_payload: dict[str, Any]
    try:
        await tasks_api.post("/", json=parent_payload)
        created_names.append(parent_payload["name"])

        for derived_spec in derived_specs:
            child_payload = build_derived_payload(parent_payload, derived_spec)
            await tasks_api.post("/", json=child_payload)
            created_names.append(child_payload["name"])

        predecessor_payload = build_predecessor_payload(
            parent_payload,
            pre_checks_template.model_dump(),
            predecessor_spec,
        )
        await tasks_api.post("/", json=predecessor_payload)
        created_names.append(predecessor_payload["name"])
    except Exception:
        for task_name in reversed(created_names):
            try:
                await tasks_api.delete(f"/{task_name}")
            except Exception as rollback_exc:  # noqa: BLE001
                logger.warning(
                    "Rollback DELETE failed for %r during "
                    "cascade_create_alters_group rollback: %s",
                    task_name,
                    rollback_exc,
                )
        raise


async def build_alters_cascade_plan(
    body: AltersCreate,
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
) -> CascadeCreatePlan:
    """Build the cascade create plan for an alters task group.

    Assemble the parent execute task and its imperative pre-checks predecessor,
    then bind a cascade closure that POSTs the parent, its dry-run derived
    sibling, and the pre-checks predecessor. The parent is re-serialised inside
    :func:`cascade_create_alters_group` so it carries the form stamp
    :func:`~app.sep.apps.framework.api.derive_cascade_create_route` applies first.

    :param body: The alters create/write JSON request body.
    :param inventory_api: The Inventory API to resolve the alters target.
    :param tasks_api: The Tasks API, used to template the pre-checks predecessor.
    :return: The plan carrying the parent write, form, and cascade closure.
    """
    parent_task = await build_alters_task(body, inventory_api)
    pre_checks_template = await build_pre_checks_task_payload(
        parent_task, task_api=tasks_api
    )
    return CascadeCreatePlan(
        parent_write=parent_task,
        form=body,
        cascade=lambda api: cascade_create_alters_group(
            api, parent_task, pre_checks_template, body
        ),
    )


AltersCascadePlan = Annotated[CascadeCreatePlan, Depends(build_alters_cascade_plan)]


async def render_alters_create(
    task: Task, _tasks_api: TaskAPI
) -> AltersTaskResponseCreate:
    """Render the alters create response, matching the cascade builder contract.

    The uniform ``response_builder`` contract is ``async (task, tasks_api)``;
    alters resolves the username mapping instead of touching the Tasks API, so the
    client argument is unused here. The connectivity warning is attached by the
    route helper via ``model_copy`` after this call, so it is not set here.

    :param task: The refetched canonical parent alters task.
    :param _tasks_api: The Tasks API client (unused; part of the builder contract).
    :return: The rendered create response.
    """
    username_mapping = await get_username_mapping()
    return build_alters_api_task_response(
        task,
        status=None,
        response_model=AltersTaskResponseCreate,
        username_mapping=username_mapping,
    )


_ALTERS_GROUP_RENAME_MESSAGE = (
    "Cannot rename an alters task group. Delete and recreate the task "
    "instead; the pre-checks chain wired at create time stores task "
    "names verbatim."
)


def ensure_alters_update_addresses_parent(
    requested_name: str,
    parent_task: Task,
) -> None:
    """Reject updates whose URL names a satellite instead of the parent execute task.

    :param requested_name: The ``task_name`` path segment from the request URL.
    :type requested_name: str
    :param parent_task: The resolved parent alters task.
    :type parent_task: Task
    :raises HTTPBadRequestException: When ``requested_name`` is a satellite path.
    """
    if requested_name != parent_task.name:
        raise HTTPBadRequestException(
            f"Address the parent task ({parent_task.name!r}), "
            f"not the satellite {requested_name!r}."
        )


def ensure_alters_group_update_preserves_names(
    parent_existing_name: str,
    updated_parent_name: str,
) -> None:
    """Refuse parent renames on update; create-time chain stores names verbatim.

    :param parent_existing_name: The current parent task name (PUT URL path).
    :type parent_existing_name: str
    :param updated_parent_name: The parent name from the update payload.
    :type updated_parent_name: str
    :raises HTTPConflictException: When ``updated_parent_name`` differs from
        ``parent_existing_name``.
    """
    if updated_parent_name != parent_existing_name:
        raise HTTPConflictException(_ALTERS_GROUP_RENAME_MESSAGE)


async def cascade_update_alters_group(
    tasks_api: RemoteAPI,
    parent_existing_name: str,
    parent_task: TaskWrite,
    pre_checks_template: TaskWrite,
    body: AltersCreate,
) -> CascadeResult:
    """PUT the parent, dry-run sibling, and pre-checks predecessor.

    Does not re-fire ``POST /execute`` — chain wiring from create remains
    valid because task names are unchanged.

    :param tasks_api: The Tasks API client.
    :type tasks_api: RemoteAPI
    :param parent_existing_name: The current parent task name.
    :type parent_existing_name: str
    :param parent_task: The updated parent execute payload.
    :type parent_task: TaskWrite
    :param pre_checks_template: The updated imperative pre-checks payload.
    :type pre_checks_template: TaskWrite
    :param body: The alters create/write payload (for ``continue_on_pre_check_failure``).
    :return: A merged :class:`CascadeResult` across derived and predecessor legs.
    :rtype: CascadeResult
    :raises HTTPConflictException: When the update attempts to rename the parent.
    """
    ensure_alters_group_update_preserves_names(parent_existing_name, parent_task.name)
    parent_payload = parent_task.model_dump()
    derived_specs = alters_schema.derived or []
    derived_names = alters_derived_task_names(parent_existing_name)
    predecessor_names = alters_predecessor_task_names(parent_existing_name)
    predecessor_specs = resolve_predecessor_specs(body)
    if len(predecessor_names) != len(predecessor_specs):
        raise ValueError(
            f"predecessor name count {len(predecessor_names)} does not match "
            f"schema predecessor count {len(predecessor_specs)}"
        )

    derived_result = await cascade_update_tasks(
        tasks_api,
        parent_existing_name,
        parent_payload,
        derived_names,
        derived_specs,
    )
    predecessor_result = CascadeResult()
    pre_checks_payload = pre_checks_template.model_dump()
    for existing_name, spec in zip(predecessor_names, predecessor_specs, strict=True):
        built = build_predecessor_payload(
            parent_payload,
            pre_checks_payload,
            spec,
        )
        try:
            await tasks_api.put(f"/{existing_name}", json=built)
            predecessor_result.successes.append(built["name"])
        except Exception as exc:  # noqa: BLE001
            predecessor_result.failures.append(CascadeFailure(existing_name, exc))
    return CascadeResult(
        successes=[*derived_result.successes, *predecessor_result.successes],
        failures=[*derived_result.failures, *predecessor_result.failures],
    )


async def cascade_delete_alters_group(
    tasks_api: RemoteAPI,
    parent_name: str,
) -> CascadeResult:
    """DELETE derived and predecessor satellites, then the parent task.

    :param tasks_api: The Tasks API client.
    :type tasks_api: RemoteAPI
    :param parent_name: The parent execute task name.
    :type parent_name: str
    :return: A :class:`CascadeResult` recording per-leg outcomes.
    :rtype: CascadeResult
    """
    return await cascade_delete_tasks(
        tasks_api,
        parent_name,
        alters_satellite_task_names(parent_name),
    )


resolve_alters_parent_task = make_parent_resolver(get_alters_task)


async def get_unprotected_alters_task(
    task_name: str,
    tasks_api: TaskAPI,
) -> Task:
    """Return the parent alters task or raise 409 when it is protected.

    Resolves satellite path parameters to the parent execute task before
    applying the protected check so both the JSON API and Jinja form paths
    gate the same record.

    :param task_name: The requested task name (parent or satellite).
    :type task_name: str
    :param tasks_api: The Tasks API client.
    :type tasks_api: TaskAPI
    :raises HTTPConflictException: If the parent task is marked as protected.
    :return: The unprotected parent task.
    :rtype: Task
    """
    parent_task = await resolve_alters_parent_task(task_name, tasks_api)
    ensure_alters_update_addresses_parent(task_name, parent_task)
    return reject_if_protected(parent_task)


UnprotectedAltersTask = Annotated[Task, Depends(get_unprotected_alters_task)]


async def get_editable_alters_parent_task(
    task_name: str,
    tasks_api: TaskAPI,
) -> Task:
    """Return the parent alters task or raise when update is not allowed.

    Resolves satellite path parameters to the parent execute task, ensures the
    URL targets the parent, blocks running/pending executions, and rejects
    protected tasks — the same gates as :func:`get_unprotected_alters_task` plus
    :func:`check_for_conflicted_running_tasks`.

    :param task_name: The requested task name (parent or satellite).
    :type task_name: str
    :param tasks_api: The Tasks API client.
    :type tasks_api: TaskAPI
    :raises HTTPConflictException: If the parent is running/pending or protected.
    :return: The editable parent task.
    :rtype: Task
    """
    parent_task = await get_unprotected_alters_task(task_name, tasks_api)
    await check_for_conflicted_running_tasks(parent_task.name, tasks_api)
    return parent_task


EditableAltersParent = Annotated[Task, Depends(get_editable_alters_parent_task)]


async def get_deletable_alters_parent_task(
    task_name: str,
    tasks_api: TaskAPI,
) -> Task:
    """Return the parent alters task or raise when delete is not allowed.

    Resolves satellite path parameters to the parent execute task, then
    applies the same running-task and protected gates as
    :func:`get_unprotected_alters_task` plus
    :func:`check_for_conflicted_running_tasks`.

    :param task_name: The requested task name (parent or satellite).
    :type task_name: str
    :param tasks_api: The Tasks API client.
    :type tasks_api: TaskAPI
    :raises HTTPConflictException: If the parent is running/pending or protected.
    :return: The deletable parent task.
    :rtype: Task
    """
    parent_task = await resolve_alters_parent_task(task_name, tasks_api)
    await check_for_conflicted_running_tasks(parent_task.name, tasks_api)
    return reject_if_protected(parent_task, action="delete")


DeletableAltersParent = Annotated[Task, Depends(get_deletable_alters_parent_task)]


def _command_line_from_meta(meta: dict[str, Any]) -> str | None:
    """Return the full pt-osc invocation for detail display.

    New tasks store ``_command_line`` at creation time; older tasks are
    synthesized from ``command`` + ``args`` when the API response is built.

    :param meta: The task ``data.meta`` mapping.
    :type meta: dict[str, Any]
    :return: The rendered command line, or ``None`` when unavailable.
    :rtype: str | None
    """
    stored = meta.get("_command_line")
    if isinstance(stored, str) and stored.strip():
        return stored.strip()
    command = meta.get("command")
    args = meta.get("args")
    if (
        isinstance(command, str)
        and isinstance(args, str)
        and command.strip()
        and args.strip()
    ):
        return f"{command.strip()} {args.strip()}"
    if isinstance(args, str) and args.strip():
        return args.strip()
    if isinstance(command, str) and command.strip():
        return command.strip()
    return None


def build_alters_api_task_response(
    task: Task,
    status: TaskHistoryStatusEnum | None = None,
    *,
    last_executed_at: datetime | None = None,
    response_model: type[AltersTaskResponse] = AltersTaskResponse,
    connectivity_warning: ConnectivityWarning | None = None,
    username_mapping: dict[str, str] | None = None,
) -> AltersTaskResponse:
    """Build an alters task response object for the JSON API.

    The warning fields are only carried when ``response_model`` declares them:
    list/detail use the base :class:`~app.sep.apps.alters.models.AltersTaskResponse`
    (no warnings), create/update use the derived models with
    ``connectivity_warning``.

    :param task: The alters task retrieved from the Tasks API.
    :type task: Task
    :param status: The latest known execution status for the task.
    :type status: TaskHistoryStatusEnum | None
    :param last_executed_at: The task's most recent finish time (``max``
        ``finished_at``), or ``None`` until it has finished once.
    :param response_model: The per-verb response model to build; defaults to the
        list/detail base model.
    :param connectivity_warning: A warning to surface when a connectivity
        check failed during the task creation flow.
    :type connectivity_warning: ConnectivityWarning | None
    :param username_mapping: Optional mapping of user IDs to usernames.
    :type username_mapping: dict[str, str] | None
    :return: A validated alters task API response object.
    :rtype: AltersTaskResponse
    """
    mapping = username_mapping or {}
    data = copy.deepcopy(task.data)
    meta = data.get("meta") if isinstance(data, dict) else None
    if isinstance(meta, dict):
        command_line = _command_line_from_meta(meta)
        if command_line is not None:
            meta["_command_line"] = command_line
    warning_extras = {
        field: value
        for field, value in (("connectivity_warning", connectivity_warning),)
        if field in response_model.model_fields
    }
    return build_default_task_response(
        response_model,
        task,
        status,
        last_executed_at=last_executed_at,
        extras={
            "created_by": mapping.get(task.created_by, task.created_by),
            "last_updated_by": mapping.get(task.last_updated_by, task.last_updated_by),
            "data": data,
            "service_type": ServiceTypeEnum.MYSQL,
            **warning_extras,
        },
    )


def build_alters_api_list_response(
    task: Task,
    *,
    status: TaskHistoryStatusEnum | None = None,
    last_executed_at: datetime | None = None,
    context: dict[str, str] | None = None,
) -> AltersTaskResponse:
    """Build an alters list-row response for the derived list route.

    Adapts the framework's ``(task, *, status, last_executed_at, context)``
    list-builder contract to :func:`build_alters_api_task_response`, threading the
    once-awaited username map bound as ``context`` into its ``username_mapping``
    argument so the derived list rows carry the same command line, service type, and
    resolved usernames as the detail surface.

    :param task: The parent alters task retrieved from the Tasks API.
    :param status: The latest known execution status for the task.
    :param last_executed_at: The task's most recent finish time, if any.
    :param context: The username map bound by ``response_context_provider``.
    :return: A validated alters task API response for the list surface.
    """
    return build_alters_api_task_response(
        task,
        status,
        last_executed_at=last_executed_at,
        username_mapping=context,
    )


async def get_alters_index_context(
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    context: DefaultContext,
    executor_hosts_ctx: ExecutorHostsCtx,
) -> dict[str, Any]:
    """Assemble the context for the Alters plugin index view.

    Retrieves MySQL services and associated tasks, organizing them based on their
    execution status. Integrates this information into the default context for
    rendering in templates.

    :param inventory_api: The Inventory API client for fetching service and schema data.
    :type inventory_api: InventoryAPI
    :param tasks_api: The TaskAPI client for fetching task data.
    :type tasks_api: TaskAPI
    :param context: The default context to be updated with Alters-specific information.
    :type context: DefaultContext
    :param executor_hosts_ctx: The executor hosts context for the Alters tasks.
    :type executor_hosts_ctx: ExecutorHostsCtx
    :return: An updated context dictionary containing Alters-related data.
    :rtype: dict[str, Any]
    """
    return await get_tasks_context(
        inventory_api,
        tasks_api,
        get_alters_task_info,
        executor_hosts_ctx,
        context,
        OWNER,
        service_type=ServiceTypeEnum.MYSQL,
        alert_on_fail_default=True,
    )


AltersIndexContext = Annotated[dict[str, Any], Depends(get_alters_index_context)]
