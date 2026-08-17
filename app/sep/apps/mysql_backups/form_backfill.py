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

"""Legacy ``data['_form']`` reconstruction for the MySQL Backups plugin."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

import yaml

from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework.form_backfill_guards import require_run_python_meta
from app.sep.apps.framework.form_backfill_inventory import resolve_service_from_meta
from app.sep.apps.framework.form_backfill_registry import FormBackfillEntry
from app.sep.apps.mysql_backups.deps import parse_backup_task_data
from app.sep.apps.mysql_backups.forms import BackupCreate, OWNER, UploadProvider
from app.sep.apps.mysql_backups.restore.form_backfill import (
    FORM_BACKFILL_ENTRY as RESTORE_FORM_BACKFILL_ENTRY,
)

if TYPE_CHECKING:
    from app.sep.apps.framework.form_backfill import FormBackfillContext
    from app.tasks.models import Task

__all__ = ["FORM_BACKFILL_ENTRIES", "reconstruct_mysql_backups_form"]

_MYSQL_BACKUPS_FORM_FIELDS = frozenset(BackupCreate.model_fields)
_UPLOAD_PROVIDER_BY_ALIAS = {provider.name: provider for provider in UploadProvider}
_EXPLICIT_FORM_KEYS = frozenset(
    {
        "task_name",
        "hostname",
        "service_id",
        "backup_type",
        "alias",
        "upload",
        "alert_on_fail",
    }
)
_PARSE_ONLY_KEYS = frozenset({"name", "host", "port"})


def _extract_upload_from_meta(meta: dict[str, Any]) -> list[str]:
    """Return normalized upload providers from ``SERVER_LIST[0].UPLOAD``."""
    providers: list[str] = []
    config_raw = meta.get("config")
    if isinstance(config_raw, str) and config_raw.strip():
        try:
            task_config = yaml.safe_load(config_raw)
        except yaml.YAMLError:
            task_config = None
        if isinstance(task_config, dict):
            server_list = task_config.get("SERVER_LIST")
            if isinstance(server_list, list) and server_list:
                first_server = server_list[0]
                if isinstance(first_server, dict):
                    upload_raw = first_server.get("UPLOAD") or first_server.get(
                        "upload"
                    )
                    if isinstance(upload_raw, list):
                        for provider in upload_raw:
                            if not isinstance(provider, str):
                                continue
                            member = _UPLOAD_PROVIDER_BY_ALIAS.get(
                                provider.strip().upper()
                            )
                            if member is not None:
                                providers.append(member.value)
    return providers


def reconstruct_mysql_backups_form(
    task: Task,
    ctx: FormBackfillContext,
) -> dict[str, Any] | None:
    """Rebuild a :class:`~app.sep.apps.mysql_backups.forms.BackupCreate` body from a legacy task.

    Wraps :func:`~app.sep.apps.mysql_backups.deps.parse_backup_task_data`, resolves
    ``service_id`` from inventory, reads ``upload`` from ``SERVER_LIST[0].UPLOAD``, and
    drops parse keys that are not on the create model (for example ``host`` / ``port`` /
    ``name``).

    :param task: The persisted mysql_backups task row.
    :param ctx: Shared backfill context carrying the inventory lookup table.
    :return: A create-model-shaped dict, or ``None`` when reconstruction fails.
    """
    meta = require_run_python_meta(task)
    if meta is None:
        return None

    try:
        parsed = parse_backup_task_data({"name": task.name, "data": task.data})
    except (KeyError, TypeError, yaml.YAMLError):
        return None

    hostname = parsed.get("hostname")
    backup_type = parsed.get("backup_type")
    if (
        not isinstance(hostname, str)
        or not hostname.strip()
        or not isinstance(backup_type, str)
        or not backup_type.strip()
    ):
        return None

    service_id = resolve_service_from_meta(
        ctx,
        meta,
        ServiceTypeEnum.MYSQL,
        host=parsed.get("host"),
        port=parsed.get("port"),
    )
    if service_id is None:
        return None

    form_fields = {
        key: value
        for key, value in parsed.items()
        if key in _MYSQL_BACKUPS_FORM_FIELDS
        and key not in _EXPLICIT_FORM_KEYS
        and key not in _PARSE_ONLY_KEYS
        and value is not None
    }

    return {
        "task_name": task.name,
        "hostname": hostname.strip(),
        "service_id": service_id,
        "backup_type": backup_type.strip(),
        "alias": parsed.get("alias"),
        "upload": _extract_upload_from_meta(meta),
        "alert_on_fail": task.alert_on_fail,
        **form_fields,
    }


FORM_BACKFILL_ENTRIES = [
    FormBackfillEntry(
        app_key="mysql_backups",
        owner=OWNER,
        create_model=BackupCreate,
        reconstructor=reconstruct_mysql_backups_form,
    ),
    RESTORE_FORM_BACKFILL_ENTRY,
]
