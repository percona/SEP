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

"""Legacy ``data['_form']`` reconstruction for the MySQL Restores plugin."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

import yaml

from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework.form_backfill_guards import require_run_python_meta
from app.sep.apps.framework.form_backfill_inventory import resolve_service_from_meta
from app.sep.apps.framework.form_backfill_registry import FormBackfillEntry
from app.sep.apps.mysql_backups.models import BackupType
from app.sep.apps.mysql_backups.restore.deps import parse_restore_task_data
from app.sep.apps.mysql_backups.restore.models import OWNER, RestoreCreate

if TYPE_CHECKING:
    from app.sep.apps.framework.form_backfill import FormBackfillContext
    from app.tasks.models import Task

__all__ = ["FORM_BACKFILL_ENTRY", "reconstruct_mysql_restores_form"]

_RESTORE_FORM_FIELDS = frozenset(RestoreCreate.model_fields)
_EXPLICIT_FORM_KEYS = frozenset(
    {
        "task_name",
        "hostname",
        "backup_type",
        "backup_source",
        "service_id",
        "schema_id",
        "alert_on_fail",
    }
)
_PARSE_ONLY_KEYS = frozenset(
    {
        "name",
        "host",
        "database",
        "dest_host",
        "dest_port",
    }
)


def _resolve_restore_service_id(
    parsed: dict[str, Any],
    meta: dict[str, Any],
    ctx: FormBackfillContext,
) -> str | None:
    """Return the restore form ``service_id``, or ``None`` when unresolved."""
    resolve_meta = meta
    if parsed.get("host"):
        resolve_meta = {**meta, "_service_name": None}
    service_id = resolve_service_from_meta(
        ctx,
        resolve_meta,
        ServiceTypeEnum.MYSQL,
        host=parsed.get("host"),
        port=parsed.get("port"),
    )
    if service_id is None:
        return None
    return str(service_id)


def _resolve_restore_schema_id(
    service_id: str | None,
    database: Any,
    ctx: FormBackfillContext,
) -> str | None:
    """Return the restore form ``schema_id`` when the database name resolves uniquely."""
    if (
        ctx.schema_lookup is None
        or service_id is None
        or not service_id.isdigit()
        or not isinstance(database, str)
        or not database.strip()
    ):
        return None

    schema_id = ctx.schema_lookup.resolve(
        service_id=int(service_id),
        schema_name=database,
    )
    if schema_id is None:
        return None
    return str(schema_id)


def reconstruct_mysql_restores_form(
    task: Task,
    ctx: FormBackfillContext,
) -> dict[str, Any] | None:
    """Rebuild a :class:`~app.sep.apps.mysql_backups.restore.models.RestoreCreate` body from a legacy task.

    Wraps :func:`~app.sep.apps.mysql_backups.restore.deps.parse_restore_task_data`,
    resolves ``service_id`` / ``schema_id`` from inventory when possible, and drops
    parse keys that are not on the create model (for example ``host`` / ``database`` /
    ``name``).

    :param task: The persisted mysql restores task row.
    :param ctx: Shared backfill context carrying the inventory lookup tables.
    :return: A create-model-shaped dict, or ``None`` when reconstruction fails.
    """
    meta = require_run_python_meta(task)
    if meta is None:
        return None

    try:
        parsed = parse_restore_task_data({"name": task.name, "data": task.data})
    except (KeyError, TypeError, yaml.YAMLError):
        return None

    hostname = parsed.get("hostname")
    backup_type = parsed.get("backup_type")
    backup_source = parsed.get("backup_source")
    if (
        not isinstance(hostname, str)
        or not hostname.strip()
        or not isinstance(backup_type, str)
        or not backup_type.strip()
        or not isinstance(backup_source, str)
        or not backup_source.strip()
    ):
        return None

    normalized_backup_type = backup_type.strip()
    service_id = _resolve_restore_service_id(parsed, meta, ctx)
    if normalized_backup_type == BackupType.MYDUMPER.value and service_id is None:
        return None

    schema_id = _resolve_restore_schema_id(
        service_id,
        parsed.get("database"),
        ctx,
    )

    form_fields = {
        key: value
        for key, value in parsed.items()
        if key in _RESTORE_FORM_FIELDS
        and key not in _EXPLICIT_FORM_KEYS
        and key not in _PARSE_ONLY_KEYS
        and value is not None
    }

    body: dict[str, Any] = {
        "task_name": task.name,
        "hostname": hostname.strip(),
        "backup_type": normalized_backup_type,
        "backup_source": backup_source.strip(),
        "alert_on_fail": task.alert_on_fail,
        **form_fields,
    }
    if service_id is not None:
        body["service_id"] = service_id
    if schema_id is not None:
        body["schema_id"] = schema_id
    return body


FORM_BACKFILL_ENTRY = FormBackfillEntry(
    app_key="mysql_backups/restore",
    owner=OWNER,
    create_model=RestoreCreate,
    reconstructor=reconstruct_mysql_restores_form,
)
