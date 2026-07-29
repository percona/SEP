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
``app.core``, ``pydantic``, ``sqlalchemy``, and ``sqlmodel``, never from the
plugin's heavy form-model module (``models.py``) or from ``app.inventory`` /
``app.tasks`` / the app framework. The sep Alembic ``env.py`` imports it to
register the table in the migration metadata, and pulling in those other
modules would bleed their tables into the sep autogenerate comparison and break
``make checkmigrations``. Keep it that way (mirrors ``app.sep.apps.atw.models``).
"""

from typing import Literal

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
