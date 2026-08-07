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

"""Define dependencies for the Backups plugin."""

import logging
from datetime import datetime
from typing import Annotated, Any

import yaml
from fastapi import Depends, Form, Query

from app.core.exceptions import HTTPNotFoundException
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework import build_default_task_response, make_task_dep
from app.sep.apps.framework.spec import (
    assemble_envelope,
    resolve_refs,
)
from app.sep.apps.mysql_backups.forms import BackupCreate, BackupTaskResponse, OWNER
from app.sep.apps.mysql_backups.models import (
    BackupType,
    CatalogServiceKey,
    extract_backup_type_marker,
)
from app.sep.apps.mysql_backups.recorder import RUN_RESULT_RECORDER
from app.sep.apps.mysql_backups.restore.deps import UNKNOWN_SERVICE_SENTINEL
from app.sep.apps.mysql_backups.spec import build_backup_spec
from app.sep.apps.shared.backups.edit_form import parse_server_list_config
from app.sep.deps import (
    DefaultContext,
    ExecutorHostsCtx,
    get_tasks_context,
    InventoryAPI,
    TaskAPI,
)
from app.sep.inventory import CreatedService
from app.tasks.models import Task, TaskHistoryStatusEnum, TaskWrite

logger = logging.getLogger(__name__)


async def build_backup_task_payload(
    form: Annotated[BackupCreate, Form()],
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build the backup task payload from a form-urlencoded body.

    The legacy Jinja form path's payload dependency. Resolves the form's
    reference fields and feeds the shared pure
    :func:`~app.sep.apps.mysql_backups.spec.build_backup_spec` through the
    framework's ``assemble_envelope``, the same pair the model-first JSON create
    route uses — so a form-created task's Nomad payload stays byte-identical to a
    JSON-created one.

    :param form: The form data for the Backups creation.
    :type form: BackupCreate
    :param inventory_api: The Inventory API to resolve the service reference.
    :type inventory_api: InventoryAPI
    :return: A fully constructed ``TaskWrite`` object.
    :rtype: TaskWrite
    """
    resolved = await resolve_refs(form, inventory_api)
    return assemble_envelope(
        build_backup_spec(form, resolved),
        resolved,
        name=form.task_name,
        owner=OWNER,
        alert_on_fail=form.alert_on_fail,
        run_result_recorder=RUN_RESULT_RECORDER,
    )


def parse_backup_task_data(task: dict[str, Any]) -> dict[str, Any]:
    """Parse backup task data for editing.

    Extracts configuration from an existing backup task to populate the edit form.

    Delegates the shared ``SERVER_LIST`` parsing to
    :func:`~app.sep.apps.shared.backups.edit_form.parse_server_list_config`, layering on the
    mysql-specific alias, encryption recipient, and the mydumper / xtrabackup /
    binlog / upload-quiet keys.

    :param task: The task data retrieved from the Tasks API.
    :return: A dictionary containing parsed backup configuration.
    """
    task_config = yaml.safe_load(task["data"]["meta"]["config"])
    server_config = task_config["SERVER_LIST"][0]
    all_servers_config = task_config.get("ALL_SERVERS", {})

    extra_fields = {
        "port": server_config.get("PORT"),
        "alias": server_config.get("ALIAS"),
    }
    if "dir_encrypt_config" in server_config:
        extra_fields["encryption_recipient"] = server_config["dir_encrypt_config"].get(
            "encryption_recipient"
        )
    extra_fields["binlog_alternative_host"] = all_servers_config.get(
        "BINLOG_ALTERNATIVE_HOST"
    )
    extra_fields["mydumper_verbose"] = all_servers_config.get("MYDUMPER_VERBOSE")
    extra_fields["xtrabackup_quiet"] = all_servers_config.get("XTRABACKUP_QUIET")
    extra_fields["upload_quiet"] = all_servers_config.get("UPLOAD_QUIET")

    return parse_server_list_config(
        task, server_config, all_servers_config, extra_fields
    )


BackupGeneratedTask = Annotated[TaskWrite, Depends(build_backup_task_payload)]


async def resolve_mysql_service(
    service_id: int, inventory_api: InventoryAPI
) -> CreatedService:
    """Resolve an inventory service by id for the backup-catalog query route.

    Lets the Inventory API's ``404`` propagate unchanged: an unknown ``service_id``
    is a real client error, not an empty catalog. The catalog query distinguishes
    the two — this raises for a service that does not exist, while a service that
    exists but has no recorded runs yields an empty list. A resolvable service of
    the wrong type is treated the same as an unknown one: the catalog holds only
    MySQL runs and falls back to matching on ``service_name`` for rows carrying no
    id, so serving a non-MySQL service would let it leak the runs of a MySQL
    service that happens to share its name.

    :param service_id: The inventory id of the service to resolve.
    :param inventory_api: The Inventory API client used to resolve the service.
    :return: The resolved service.
    :raises HTTPNotFoundException: When the resolved service is not a MySQL service.
    """
    service_data = await inventory_api.get(f"/services/{service_id}")
    service = CreatedService.model_validate(service_data)
    if service.type is not ServiceTypeEnum.MYSQL:
        raise HTTPNotFoundException(detail="Service not found")
    return service


ResolvedMysqlService = Annotated[CreatedService, Depends(resolve_mysql_service)]


async def resolve_optional_catalog_service_key(
    inventory_api: InventoryAPI,
    service_id: str | None = Query(
        None,
        description=(
            "Cascade parent from the restore form. Inventory numeric ids are "
            "resolved to a MySQL service, keying the catalog query on its id; "
            "custom names query the catalog by name directly. Omitted, blank, "
            "sentinel, or unknown values yield an empty list so free-text entry "
            "is never blocked by a failed options fetch."
        ),
    ),
) -> CatalogServiceKey | None:
    """Resolve the cascade parent to the catalog query keys, or ``None``.

    Numeric ids go through :func:`resolve_mysql_service` (MySQL-typed only) and
    yield both keys, so a rename between recording and querying cannot detach the
    rows; unknown ids degrade to ``None``. Non-numeric values yield the raw value
    as the name and no id, so a free-typed restore destination can still list
    catalog rows by that name — deliberately unguarded by Inventory type checks,
    matching the restore form's ``ServiceRef(allow_custom=True)`` escape hatch.
    Omitted, blank, and sentinel parents also yield ``None``.

    The numeric test is ``str.isdecimal``, not ``str.isdigit``: the latter also
    accepts digits ``int`` cannot parse (superscripts such as ``"²"``), which would
    take the numeric branch and degrade to ``None`` rather than reaching the name
    branch the free-text escape hatch exists to serve. A decimal string ``int``
    still cannot parse — one longer than ``sys.get_int_max_str_digits()`` — has no
    usable name reading either, so it degrades to ``None``. The parse is guarded on
    its own so that a ``pydantic.ValidationError`` from resolving the service, being
    a ``ValueError`` subclass, is not swallowed as an unparsable id.

    :param inventory_api: The Inventory API client used to resolve numeric ids.
    :param service_id: The cascade parent's submitted value, or ``None`` when
        omitted.
    :return: The keys to query the catalog with, or ``None`` when the parent is
        unusable.
    :raises HTTPException: When the Inventory lookup fails with a status other
        than 404.
    """
    if service_id is None:
        return None
    trimmed = service_id.strip()
    if not trimmed or trimmed == UNKNOWN_SERVICE_SENTINEL:
        return None
    if not trimmed.isdecimal():
        return CatalogServiceKey(service_name=trimmed, service_id=None)
    try:
        parsed = int(trimmed)
    except ValueError:
        return None
    try:
        service = await resolve_mysql_service(parsed, inventory_api)
    except HTTPNotFoundException:
        return None
    return CatalogServiceKey(service_name=service.name, service_id=service.id)


OptionalCatalogServiceKey = Annotated[
    CatalogServiceKey | None, Depends(resolve_optional_catalog_service_key)
]


get_backups_task = make_task_dep(OWNER)

BackupsTask = Annotated[Task, Depends(get_backups_task)]


def _extract_backup_type_from_task(task: Task) -> BackupType | None:
    """Read ``BACKUP_TYPE`` out of the task's YAML config as a typed value, if present.

    Shares the defensive raw-marker parse with the run-result recorder via
    :func:`~app.sep.apps.mysql_backups.models.extract_backup_type_marker`,
    layering only the coercion to the typed :class:`BackupType` on top.

    :param task: The task whose ``data`` carries the YAML config.
    :return: The typed backup type, or ``None`` when absent or unrecognised.
    """
    marker = extract_backup_type_marker(task.data)
    try:
        return BackupType(marker)
    except ValueError:
        return None


def build_mysql_backups_api_task_response(
    task: Task,
    status: TaskHistoryStatusEnum | None = None,
    *,
    last_executed_at: datetime | None = None,
    context: dict[str, str] | None = None,
) -> BackupTaskResponse:
    """Build a ``BackupTaskResponse`` for the JSON API.

    :param task: The backups task retrieved from the Tasks API.
    :type task: Task
    :param status: The latest known execution status for the task.
    :type status: TaskHistoryStatusEnum | None
    :param last_executed_at: The task's most recent finish time (``max``
        ``finished_at``), or ``None`` until it has finished once.
    :param context: The username map bound by ``response_context_provider``,
        used to remap ``created_by`` / ``last_updated_by`` user-ids to
        usernames; falls back to the raw id when the map lacks an entry.
    :type context: dict[str, str] | None
    :return: A validated backup task API response object.
    """
    mapping = context or {}
    hostname = None
    if task.data:
        meta = task.data.get("meta") or {}
        hostname = meta.get("target")
    return build_default_task_response(
        BackupTaskResponse,
        task,
        status,
        last_executed_at=last_executed_at,
        extras={
            "backup_type": _extract_backup_type_from_task(task),
            "hostname": hostname,
            "service_type": ServiceTypeEnum.MYSQL,
            "created_by": mapping.get(task.created_by, task.created_by),
            "last_updated_by": mapping.get(task.last_updated_by, task.last_updated_by),
        },
    )


def get_backups_task_info(task: dict[str, Any]) -> dict[str, Any]:
    """Extract relevant information from a task for the Backups plugin.

    Processes the task data to extract hostname and tables information.

    :param task: The task data retrieved from the Tasks API.
    :type task: dict[str, Any]
    :return: A dictionary containing hostname and tables information.
    :rtype: dict[str, Any]
    """
    data = task["data"]
    meta = data["meta"]
    task_config = yaml.safe_load(meta["config"])
    backup_server = task_config["SERVER_LIST"][0]

    return {
        "hostname": meta["target"],
        "host": backup_server.get("HOST"),
        "port": backup_server.get("PORT"),
        "upload": ", ".join(backup_server.get("UPLOAD")),
        "backup_type": BackupType(backup_server.get("BACKUP_TYPE")).name,
        "created_by": task.get("created_by"),
        "last_updated_by": task.get("last_updated_by"),
    }


async def get_backups_index_context(
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    context: DefaultContext,
    executor_hosts_ctx: ExecutorHostsCtx,
) -> dict[str, Any]:
    """Assemble the context for the Backups plugin index view.

    Retrieves MySQL services and associated tasks, organizing them based on their
    execution status. Integrates this information into the default context for
    rendering in templates.

    :param inventory_api: The Inventory API client for fetching service and schema data.
    :type inventory_api: InventoryAPI
    :param tasks_api: The TaskAPI client for fetching task data.
    :type tasks_api: TaskAPI
    :param context: The default context to be updated with Backups-specific information.
    :type context: DefaultContext
    :param executor_hosts_ctx: The executor hosts context for the Backups tasks.
    :type executor_hosts_ctx: ExecutorHostsCtx
    :return: An updated context dictionary containing Backups-related data.
    :rtype: dict[str, Any]
    """
    return await get_tasks_context(
        inventory_api,
        tasks_api,
        get_backups_task_info,
        executor_hosts_ctx,
        context,
        OWNER,
        service_type=ServiceTypeEnum.MYSQL,
        alert_on_fail_default=True,
    )


BackupsIndexContext = Annotated[dict[str, Any], Depends(get_backups_index_context)]
