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

"""Define the MySQL Backups plugin's self-contained catalog model and API response.

This module is intentionally **self-contained** — it imports only from
``app.core``, ``pydantic``, ``sqlalchemy``, ``sqlmodel``, and ``yaml`` (for the
shared config parser), never from ``app.inventory`` / ``app.tasks`` / the app
framework's form DSL. The sep Alembic discovery loads it at migration time to
register the table in the migration metadata, and pulling in those heavier
modules would bleed their tables into the sep autogenerate comparison and break
``make checkmigrations``.

The split mirrors ``app.sep.apps.atw``, in the direction that matters: there,
``atw.models`` is the self-contained module and the one inventory-dependent
piece (the category taxonomy) lives apart, in ``atw.categories``. Here, this
module plays the role of ``atw.models``, and the plugin's heavy form/DSL
surface (:class:`~app.sep.apps.mysql_backups.forms.BackupCreate` and friends)
plays the role of ``atw.categories`` — the piece split *out* because it, not
the table, needed the heavier imports.
"""

from enum import StrEnum
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import BigInteger, Column
from sqlalchemy import Enum as EnumField
from sqlmodel import Field as SQLField

from app.core.db.models import BaseSQLModel, DateTimeWithTimezone
from app.core.utils.fields import EnumFieldMixin, UTCDatetime


class BackupType(EnumFieldMixin, StrEnum):
    """Backup types."""

    MYDUMPER = "M"
    XTRABACKUP = "X"
    BINLOG = "B"


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
        Not a foreign key — the catalog is sep-owned and joins to inventory by
        name only, so two MySQL services sharing a name (``Service.name`` carries
        no uniqueness constraint) would have their rows merged under either id.

    :param hostname: The backup target host (the task's ``target`` meta).
    :param backup_type: The backup tool the run used, mydumper or xtrabackup.
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
    backup_type: BackupType = SQLField(
        sa_column=Column(
            EnumField(BackupType, native_enum=False, create_constraint=True),
            nullable=False,
        ),
    )
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
        Narrower than :class:`BackupType`: binlog runs are never catalogued, so
        ``"B"`` never appears here.
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

    @field_validator("backup_type", mode="before")
    @classmethod
    def _coerce_backup_type(cls, value: object) -> object:
        """Reduce a ``BackupType`` enum column value to its plain string value.

        The ORM's non-native enum column round-trips as a :class:`BackupType`
        member, not the plain ``str`` this ``Literal`` field expects — pydantic's
        literal validator matches on exact type, not ``StrEnum`` equality.

        :param value: The raw ``backup_type`` value from the ORM row.
        :return: ``value.value`` for a :class:`BackupType` member, else ``value``.
        """
        return value.value if isinstance(value, BackupType) else value


def extract_backup_type_marker(task_data: dict[str, Any] | None) -> str | None:
    """Return the ``BACKUP_TYPE`` marker from a task's YAML config, or ``None``.

    Reads the value defensively: a missing ``meta``, unparseable YAML, or an
    absent key all resolve to ``None`` rather than raising. Returns the raw
    single-letter marker (``"M"``/``"X"``/``"B"``); callers that need the typed
    :class:`BackupType` coerce it themselves (see ``deps.py``'s
    ``_extract_backup_type_from_task``).

    :param task_data: The task's ``data`` dict (``meta`` carries the YAML config).
    :return: The raw backup-type marker, or ``None``.
    """
    match task_data:
        case {"meta": {"config": str(raw_config)}} if raw_config:
            pass
        case _:
            return None

    try:
        config = yaml.safe_load(raw_config)
    except yaml.YAMLError:
        return None

    match config:
        case {"SERVER_LIST": [{"BACKUP_TYPE": str(backup_type)}, *_]}:
            return backup_type
        case _:
            return None
