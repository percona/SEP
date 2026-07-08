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

"""Define dependencies for the Archives plugin.

The model-first JSON create / update / list / detail surfaces are derived by the
``TaskExecutionApp`` in ``app.py``. This module holds the parts that stay
hand-written: the legacy Jinja form path (a flat parse model mapped into the
one-of ``ArchivesCreate`` so the deprecated HTML form keeps working against the
shared spec builder), the list/detail response builder, the task-by-name
dependency, and the Jinja index context.
"""

import logging
from datetime import date
from typing import Annotated, Any

from fastapi import Depends, Form
from pydantic import Field, ValidationError

from app.core.exceptions import HTTPUnprocessableEntityException
from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import EmptyStrToNone, NonEmptyStr, TcpPort
from app.sep.apps.archives.alerts import (
    ALERT_DETAIL_BUILDER,
    parse_archiver_purge_config,
)
from app.sep.apps.archives.models import ArchivesCreate
from app.sep.apps.archives.spec import build_archives_spec
from app.sep.apps.framework import make_task_dep
from app.sep.apps.framework.spec import assemble_envelope, resolve_refs
from app.sep.deps import (
    DefaultContext,
    ExecutorHostsCtx,
    get_tasks_context,
    InventoryAPI,
    TaskAPI,
)
from app.tasks.models import Task, TaskOwner, TaskWrite

logger = logging.getLogger(__name__)


class ArchivesLegacyForm(BaseCaseInsensitiveModel):
    """Parse the deprecated Archives HTML form's flat, urlencoded body.

    The Jinja templates submit the historical flat field names (``source_db_id`` /
    ``source_db_name`` / …) that predate the one-of collapse, so the derived
    one-of ``ArchivesCreate`` cannot bind them directly. This model parses that
    flat body; :func:`_map_legacy_to_create` folds it into ``ArchivesCreate`` for
    the shared spec builder, keeping the legacy path byte-identical. Conditional
    validation is enforced by the mapped ``ArchivesCreate``, not here.

    :param alias: The task name (the ``ALIAS`` in the archiver config).
    :param hostname: The executor host.
    :param service_id: The source MySQL service id.
    :param source_db_id: The source schema inventory id, or empty.
    :param source_db_name: The manually-entered source schema name.
    :param source_table_id: The source table inventory id, or empty.
    :param source_table_name: The manually-entered source table name.
    :param source_query: A custom source query.
    :param where: The WHERE clause.
    :param dest_table_id: The destination table inventory id, or empty.
    :param dest_table_name: The manually-entered destination table name.
    :param dest_file: The destination file path.
    :param swap_drop: The archive type (0-2).
    :param swp_table_suffix: The swap-table date suffix.
    :param use_index: An index hint.
    :param extra_args: Additional pt-archiver CLI arguments.
    :param limit: The maximum rows per run.
    :param sleep: The sleep between chunk operations.
    :param disable_binlog: The disable-binlog flag (0/1).
    :param disable_bulk_insert: The disable-bulk-insert flag (0/1).
    :param delete_data: The delete-without-archiving flag (0/1).
    :param dest_service_id: The destination service inventory id, or empty.
    :param dest_host: The manual destination host.
    :param dest_port: The manual destination port.
    :param dest_db_id: The destination schema inventory id, or empty.
    :param dest_db_name: The manually-entered destination schema name.
    :param alert_on_fail: Whether to alert on failure.
    """

    alias: NonEmptyStr
    hostname: NonEmptyStr
    service_id: int
    source_db_id: int | EmptyStrToNone = None
    source_db_name: str = ""
    source_table_id: int | EmptyStrToNone = None
    source_table_name: str = ""
    source_query: NonEmptyStr | None = None
    where: NonEmptyStr | None = None
    dest_table_id: int | EmptyStrToNone = None
    dest_table_name: str = ""
    dest_file: NonEmptyStr | None = None
    swap_drop: int = Field(..., ge=0, le=2)
    swp_table_suffix: date | None = None
    use_index: NonEmptyStr | None = None
    extra_args: NonEmptyStr | None = None
    limit: int | EmptyStrToNone = None
    sleep: int | EmptyStrToNone = None
    disable_binlog: int | None = Field(None, ge=0, le=1)
    disable_bulk_insert: int | None = Field(None, ge=0, le=1)
    delete_data: int | None = Field(None, ge=0, le=1)
    dest_service_id: int | EmptyStrToNone = None
    dest_host: str | None = None
    dest_port: TcpPort | EmptyStrToNone = None
    dest_db_id: int | EmptyStrToNone = None
    dest_db_name: str = ""
    alert_on_fail: bool = False


def _int_flag_to_bool(value: int | None) -> bool | None:
    """Map a legacy integer flag (0/1/None) to the one-of model's tri-state bool.

    :param value: The legacy integer flag (``0`` / ``1`` / ``None``).
    :return: ``None`` when unset, else the boolean.
    """
    return None if value is None else bool(value)


def _collapse(ref_id: int | None, name: str) -> int | str | None:
    """Collapse a legacy id/name pair into the one-of's single free-solo value.

    :param ref_id: The inventory id, or ``None`` when not selected.
    :param name: The manually-entered name (``""`` when not entered).
    :return: The id when present, else the trimmed name, else ``None``.
    """
    if ref_id is not None:
        return ref_id
    return name.strip() or None


def _map_legacy_to_create(flat: ArchivesLegacyForm) -> ArchivesCreate:
    """Fold the flat legacy form into the one-of ``ArchivesCreate``.

    Builds the discriminated-union branches from the flat id/name pairs and
    validates through ``ArchivesCreate`` so the legacy path enforces the same
    conditional rules as the JSON path. A validation failure surfaces as a 422,
    matching the framework's body-validation behaviour.

    :param flat: The parsed legacy form body.
    :return: The validated one-of create model.
    :raises HTTPUnprocessableEntityException: When the folded model is invalid.
    """
    data: dict[str, Any] = {
        "task_name": flat.alias,
        "hostname": flat.hostname,
        "service_id": flat.service_id,
        "swap_drop": flat.swap_drop,
        "swp_table_suffix": flat.swp_table_suffix,
        "where": flat.where,
        "use_index": flat.use_index,
        "extra_args": flat.extra_args,
        "limit": flat.limit,
        "sleep": flat.sleep,
        "disable_binlog": _int_flag_to_bool(flat.disable_binlog),
        "disable_bulk_insert": _int_flag_to_bool(flat.disable_bulk_insert),
        "delete_data": _int_flag_to_bool(flat.delete_data),
        "alert_on_fail": flat.alert_on_fail,
    }
    if flat.source_query:
        data["source"] = {"mode": "query", "source_query": flat.source_query}
    else:
        data["source"] = {
            "mode": "table",
            "source_db": _collapse(flat.source_db_id, flat.source_db_name),
            "source_table": _collapse(flat.source_table_id, flat.source_table_name),
        }
    if flat.dest_file:
        data["destination"] = {"mode": "file", "dest_file": flat.dest_file}
    elif flat.dest_table_id is not None or flat.dest_table_name.strip():
        data["destination"] = {
            "mode": "table",
            "dest_db": _collapse(flat.dest_db_id, flat.dest_db_name),
            "dest_table": _collapse(flat.dest_table_id, flat.dest_table_name),
        }
    if flat.dest_service_id is not None:
        data["host"] = {"mode": "service", "dest_service": flat.dest_service_id}
    elif flat.dest_host and flat.dest_host.strip():
        data["host"] = {
            "mode": "manual",
            "dest_host": flat.dest_host,
            "dest_port": flat.dest_port,
        }
    try:
        return ArchivesCreate.model_validate(data)
    except ValidationError as exc:
        raise HTTPUnprocessableEntityException(detail=exc.errors()) from exc


async def build_archives_task_payload(
    form: Annotated[ArchivesLegacyForm, Form()],
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build the archive task payload from the legacy HTML form body (Jinja2 path).

    Folds the flat form into the one-of ``ArchivesCreate`` and feeds the shared
    pure :func:`~app.sep.apps.archives.spec.build_archives_spec` through the
    framework's ``assemble_envelope`` — the same pair the model-first JSON create
    route uses — so a form-created task's payload stays byte-identical.

    :param form: The parsed legacy form body.
    :param inventory_api: The Inventory API to resolve the reference fields.
    :return: A fully constructed ``TaskWrite`` object.
    """
    create = _map_legacy_to_create(form)
    resolved = await resolve_refs(create, inventory_api)
    return assemble_envelope(
        build_archives_spec(create, resolved),
        resolved,
        name=create.task_name,
        owner=TaskOwner.ARCHIVER,
        alert_on_fail=create.alert_on_fail,
        alert_detail_builder=ALERT_DETAIL_BUILDER,
    )


ArchivesGeneratedTask = Annotated[TaskWrite, Depends(build_archives_task_payload)]


get_archives_task = make_task_dep(TaskOwner.ARCHIVER)

ArchivesTask = Annotated[Task, Depends(get_archives_task)]


def get_archives_task_info(task: dict[str, Any]) -> dict[str, Any]:
    """Extract relevant information from a task for the Archives plugin.

    Processes the task data to extract hostname and tables information.

    :param task: The task data retrieved from the Tasks API.
    :return: A dictionary containing hostname and tables information.
    """
    data = task["data"]
    meta = data["meta"]
    # Shared parser (single source of truth for the PURGE_LIST field mapping);
    # the tasks-service failure-alert builder uses the same function.
    fields = parse_archiver_purge_config(meta["config"])

    result = {
        "hostname": meta["target"],
        "created_by": task.get("created_by"),
        "last_updated_by": task.get("last_updated_by"),
    }

    if fields:
        if fields.source:
            result["source_table"] = fields.source
        if fields.dest_table_display:
            result["dest_table"] = fields.dest_table_display
        if fields.source_query:
            result["source_query"] = fields.source_query
        if fields.dest_file:
            result["dest_file"] = fields.dest_file

    return result


async def get_archives_index_context(
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    context: DefaultContext,
    executor_hosts_ctx: ExecutorHostsCtx,
) -> dict[str, Any]:
    """Assemble the context for the Archives plugin index view.

    Retrieves MySQL services and associated tasks, organizing them based on their
    execution status. Integrates this information into the default context for
    rendering in templates.

    :param inventory_api: The Inventory API client for service and schema data.
    :param tasks_api: The TaskAPI client for fetching task data.
    :param context: The default context to update with Archives-specific data.
    :param executor_hosts_ctx: The executor hosts context for the Archives tasks.
    :return: An updated context dictionary containing Archives-related data.
    """
    return await get_tasks_context(
        inventory_api,
        tasks_api,
        get_archives_task_info,
        executor_hosts_ctx,
        context,
        TaskOwner.ARCHIVER,
        alert_on_fail_default=True,
    )


ArchivesIndexContext = Annotated[dict[str, Any], Depends(get_archives_index_context)]
