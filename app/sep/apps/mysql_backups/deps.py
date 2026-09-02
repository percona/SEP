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
from fastapi import Depends, Query

from app.core.exceptions import HTTPNotFoundException
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework import build_default_task_response
from app.sep.apps.mysql_backups.forms import (
    BackupTaskResponse,
    ENCRYPTION_FORMAT_BY_PASSES,
    EncryptionFormat,
)
from app.sep.apps.mysql_backups.models import (
    BackupType,
    CatalogServiceKey,
    extract_backup_type_marker,
    UNKNOWN_SERVICE_SENTINEL,
)
from app.sep.apps.shared.backups.edit_form import parse_server_list_config
from app.sep.deps import InventoryAPI
from app.sep.inventory import CreatedService
from app.tasks.models import Task, TaskHistoryStatusEnum

logger = logging.getLogger(__name__)


def _infer_encryption_format(
    backup_type: str | None, all_servers: dict[str, Any]
) -> EncryptionFormat:
    """Return the encryption format a task stored before the selector was running.

    Derived from the fields that used to be the only signal, so a task keeps the
    encryption it already ran when its edit form reloads.

    An absent ``ENCRYPT`` reads as disabled. The payload treats the same absence as
    *enabled*, but that fail-safe guards a standalone run against hand-authored
    config, which never reaches this function: every config SEP itself writes names
    ``ENCRYPT`` explicitly, an invariant its own contract test pins.

    A key file left on a Mydumper or Binlog task is ignored: AES-256 is
    XtraBackup-only, so inferring it would produce a format that backup type
    rejects and a form that could never validate.

    :param backup_type: The stored ``BACKUP_TYPE``, if any.
    :param all_servers: The stored ``ALL_SERVERS`` config block.
    :return: The inferred format.
    """
    gpg = bool(all_servers.get("ENCRYPT") or all_servers.get("POST_RUN_ENCRYPT"))
    aes256 = backup_type == BackupType.XTRABACKUP and bool(
        all_servers.get("XTRABACKUP_AES256_KEYFILE")
    )
    return ENCRYPTION_FORMAT_BY_PASSES[aes256 * 2 + gpg]


def parse_backup_task_data(task: dict[str, Any]) -> dict[str, Any]:
    """Parse backup task data for editing.

    Extracts configuration from an existing backup task to populate the edit form.

    Delegates the shared ``SERVER_LIST`` parsing to
    :func:`~app.sep.apps.shared.backups.edit_form.parse_server_list_config`, layering on the
    mysql-specific alias, encryption recipient, and the mydumper / xtrabackup /
    binlog / upload-quiet keys. A task stored before ``ENCRYPTION_FORMAT`` existed
    has its format inferred by :func:`_infer_encryption_format`.

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
    if "ENCRYPTION_FORMAT" not in all_servers_config:
        extra_fields["encryption_format"] = _infer_encryption_format(
            server_config.get("BACKUP_TYPE"), all_servers_config
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

    Retired services resolve too: the catalog is a historical record, and a service
    the inventory stopped seeing upstream is exactly the one whose past runs are
    still wanted.

    :param service_id: The inventory id of the service to resolve.
    :param inventory_api: The Inventory API client used to resolve the service.
    :return: The resolved service.
    :raises HTTPNotFoundException: When the resolved service is not a MySQL service.
    """
    service_data = await inventory_api.get(
        f"/services/{service_id}", params={"include_retired": "true"}
    )
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
