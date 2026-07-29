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

"""Define the MySQL backup catalog's persisted model and query response.

This module is intentionally **self-contained** — it imports only from
``app.core``, ``pydantic``, ``sqlalchemy``, ``sqlmodel``, and ``yaml`` (for the
shared config parser), never from the plugin's heavy form-model module
(``models.py``) or from ``app.inventory`` / ``app.tasks`` / the app framework.
The sep Alembic ``env.py`` imports it to register the table in the migration
metadata, and pulling in those other modules would bleed their tables into the
sep autogenerate comparison and break ``make checkmigrations``. Keep it that way
(mirrors ``app.sep.apps.atw.models``).
"""

from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger
from sqlmodel import Field as SQLField

from app.core.db.models import BaseSQLModel, DateTimeWithTimezone
from app.core.utils.fields import UTCDatetime


class MysqlBackupRun(BaseSQLModel, table=True):
    """Persist one completed MySQL backup run's produced output.

    Written by the run-result recorder on a successful mydumper or xtrabackup
    run — one row per run, keyed by :attr:`task_history_id`. The record is
    tool-agnostic: the xtrabackup incremental layout is captured as a different
    :attr:`location` string, not a different shape. Binlog runs and non-success
    terminals leave no row.

    :param task_history_id: The id of the ``TaskHistory`` this run belongs to;
        unique, so one run maps to exactly one record.
    :param service_name: The inventory service name the backup was taken from
        (the task's ``_service_name`` meta), used as the per-service query key.
    :param hostname: The backup target host (the task's ``target`` meta).
    :param backup_type: The backup tool the run used, ``"M"`` (mydumper) or
        ``"X"`` (xtrabackup).
    :param location: The resolved on-disk directory the run produced, stored
        exactly as the payload reported it.
    :param upload_destination: The upload destination when one was configured,
        else ``None``.
    :param size_bytes: The backup size in bytes, when the run reported it.
    :param started_at: When the run started.
    :param finished_at: When the run finished.
    """

    __tablename__ = "mysql_backup_run"

    task_history_id: int = SQLField(unique=True, index=True)
    service_name: str | None = SQLField(default=None, index=True)
    hostname: str | None = None
    backup_type: str
    location: str | None = None
    upload_destination: str | None = None
    size_bytes: int | None = SQLField(default=None, sa_type=BigInteger)
    started_at: UTCDatetime | None = SQLField(
        default=None, sa_type=DateTimeWithTimezone
    )
    finished_at: UTCDatetime | None = SQLField(
        default=None, sa_type=DateTimeWithTimezone
    )


class BackupRunResponse(BaseModel):
    """Expose one catalog record over the per-service query path.

    :param id: The record's primary key.
    :param service_name: The inventory service the backup was taken from.
    :param hostname: The backup target host.
    :param backup_type: The backup tool, ``"M"`` (mydumper) or ``"X"`` (xtrabackup).
    :param location: The resolved on-disk directory the run produced.
    :param upload_destination: The upload destination when one was configured.
    :param size_bytes: The backup size in bytes, when the run reported it.
    :param started_at: When the run started.
    :param finished_at: When the run finished.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    service_name: str | None
    hostname: str | None
    backup_type: Literal["M", "X"]
    location: str | None
    upload_destination: str | None
    size_bytes: int | None
    started_at: UTCDatetime | None
    finished_at: UTCDatetime | None


def extract_backup_type_marker(task_data: dict[str, Any] | None) -> str | None:
    """Return the ``BACKUP_TYPE`` marker from a task's YAML config, or ``None``.

    Reads the value defensively: a missing ``meta``, unparseable YAML, or an
    absent key all resolve to ``None`` rather than raising. Returns the raw
    single-letter marker (``"M"``/``"X"``/``"B"``); callers that need the typed
    ``BackupType`` coerce it themselves, keeping the plugin's heavy form-model
    import out of this self-contained module.

    :param task_data: The task's ``data`` dict (``meta`` carries the YAML config).
    :return: The raw backup-type marker, or ``None``.
    """
    meta = task_data.get("meta") if task_data else None
    raw_config = meta.get("config") if isinstance(meta, dict) else None
    if not raw_config:
        return None
    try:
        config = yaml.safe_load(raw_config)
    except yaml.YAMLError:
        return None
    if not isinstance(config, dict):
        return None
    server_list = config.get("SERVER_LIST")
    if not isinstance(server_list, list) or not server_list:
        return None
    first = server_list[0]
    if not isinstance(first, dict):
        return None
    raw_type = first.get("BACKUP_TYPE")
    return raw_type if isinstance(raw_type, str) else None
