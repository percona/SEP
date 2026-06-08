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

"""Define models for the Backups plugin."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import EmptyStrToNone, EnumFieldMixin, NonEmptyStr
from app.tasks.models import TaskBackendEnum, TaskHistoryStatusEnum, TaskOwner


class BackupType(EnumFieldMixin, StrEnum):
    """Backup types."""

    PGBACKREST = "P"


class PgBackRestBackupType(EnumFieldMixin, StrEnum):
    """PgBackRest backup types."""

    INCR = "incr"
    DIFF = "diff"


SafeStanza = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    ),
]
"""Define a safe pgBackRest stanza name."""


class BackupConfigAll(BaseCaseInsensitiveModel):
    """Represent the general configuration for the backup task."""

    logging_dir: NonEmptyStr | EmptyStrToNone = None
    backup_dir: NonEmptyStr | EmptyStrToNone = None
    pgbackrest_bin: NonEmptyStr | EmptyStrToNone = None
    pgbackrest_config_file: NonEmptyStr | EmptyStrToNone = None
    pgbackrest_backup_type: PgBackRestBackupType | EmptyStrToNone = None
    pgbackrest_datadir: NonEmptyStr | EmptyStrToNone = None
    pgbackrest_retention_full: int | EmptyStrToNone = None
    pgbackrest_retention_archive: int | EmptyStrToNone = None
    pgbackrest_incremental_cycle: int | str | EmptyStrToNone = None


class BackupConfigServer(BaseCaseInsensitiveModel):
    """Represent an individual server configuration.

    :param alias: A unique alias for the server.
    :type alias: NonEmptyStr
    :param backup_type: The type of the backup.
    :type backup_type: BackupType
    :param host: The hostname or address of the server.
    :type host: NonEmptyStr
    :param port: The port number used to connect to the host.
    :type port: int | None
    :param upload: A unique list of upload providers to use for the backup, if any.
    :type upload: UniqueList[UploadProvider] | None
    :param dir_encrypt_config: Specific configuration for the backup encryption.
    :type dir_encrypt_config: DirEncryptConfig | None
    """

    alias: NonEmptyStr
    backup_type: str
    host: NonEmptyStr


class BackupCreate(BackupConfigAll):
    """Represent a Backup creation form with proper case-insensitive fields."""

    task_name: NonEmptyStr
    hostname: NonEmptyStr
    service_id: int
    backup_type: BackupType
    stanza: SafeStanza
    alert_on_fail: bool = False


class BackupConfig(BaseCaseInsensitiveModel):
    """Represent the overall backup configuration.

    :param all_servers: General settings for the backup.
    :type all_servers: BackupConfigAll
    :param server_list: A list of backup configuration for each server.
    :type server_list: list[BackupConfigServer]
    """

    all_servers: BackupConfigAll
    server_list: list[BackupConfigServer]


class BackupTaskWrite(BaseModel):
    """Represent a JSON request body for creating a pgBackRest backup task.

    Mirrors :class:`BackupCreate` minus ``backup_type``, which the API handler
    always sets to :attr:`BackupType.PGBACKREST` on create.

    :param task_name: The name of the task to be created.
    :type task_name: NonEmptyStr
    :param hostname: The target Nomad executor host.
    :type hostname: NonEmptyStr
    :param service_id: The Inventory ID of the PostgreSQL service.
    :type service_id: int
    :param stanza: The pgBackRest stanza name as configured in pgbackrest.conf on
        the host. Must match an existing stanza — this value is passed verbatim
        as ``--stanza`` to every ``pgbackrest`` invocation.
    :type stanza: SafeStanza
    :param alert_on_fail: If True, fire a PMM alert on task failure.
    :type alert_on_fail: bool
    :param logging_dir: Optional directory used by the payload for logs.
    :type logging_dir: str | None
    :param backup_dir: Required pgBackRest backup directory.
    :type backup_dir: NonEmptyStr
    :param pgbackrest_bin: Absolute path to the ``pgbackrest`` binary.
    :type pgbackrest_bin: str | None
    :param pgbackrest_config_file: Path to ``pgbackrest.conf`` on the host.
    :type pgbackrest_config_file: str | None
    :param pgbackrest_backup_type: ``incr`` or ``diff``.
    :type pgbackrest_backup_type: PgBackRestBackupType | None
    :param pgbackrest_datadir: Postgres data directory.
    :type pgbackrest_datadir: str | None
    :param pgbackrest_retention_full: Number of full backups to retain.
    :type pgbackrest_retention_full: int | None
    :param pgbackrest_retention_archive: Number of WAL archives to retain.
    :type pgbackrest_retention_archive: int | None
    :param pgbackrest_incremental_cycle: Cadence value for the INCR/FULL cycle.
    :type pgbackrest_incremental_cycle: int | str | None
    """

    model_config = ConfigDict(extra="forbid")

    task_name: NonEmptyStr
    hostname: NonEmptyStr
    service_id: int
    stanza: SafeStanza
    alert_on_fail: bool = False
    logging_dir: str | None = None
    backup_dir: NonEmptyStr
    pgbackrest_bin: str | None = None
    pgbackrest_config_file: str | None = None
    pgbackrest_backup_type: PgBackRestBackupType | None = None
    pgbackrest_datadir: str | None = None
    pgbackrest_retention_full: int | None = None
    pgbackrest_retention_archive: int | None = None
    pgbackrest_incremental_cycle: int | str | None = None


class BackupTaskBase(BaseModel):
    """Define common fields shared across backup_pg JSON API responses.

    :param name: The task name.
    :type name: str
    :param owner: The task owner enum value.
    :type owner: TaskOwner
    :param hostname: The Nomad executor target the task runs on.
    :type hostname: str | None
    :param status: The latest execution status of the task, if known.
    :type status: TaskHistoryStatusEnum | None
    """

    name: str
    owner: TaskOwner
    hostname: str | None = None
    status: TaskHistoryStatusEnum | None = None


class BackupTaskResponse(BackupTaskBase):
    """Represent a pgBackRest backup task API response.

    :param id: The task identifier from the Tasks service, if assigned.
    :type id: int | None
    :param backend: The backend executing the task.
    :type backend: TaskBackendEnum
    :param backup_type: The ``backup_type`` discriminator stored on the task.
    :type backup_type: str
    :param data: The raw task ``data`` payload.
    :type data: dict[str, Any]
    :param protected: Whether the task is protected from deletion.
    :type protected: bool
    :param alert_on_fail: Whether PMM alerts fire when the task fails.
    :type alert_on_fail: bool
    :param created_at: Creation timestamp.
    :type created_at: datetime | None
    :param updated_at: Last-modification timestamp.
    :type updated_at: datetime | None
    :param created_by: User that created the task.
    :type created_by: str | None
    :param last_updated_by: User that last modified the task record.
    :type last_updated_by: str | None
    """

    id: int | None = None
    backend: TaskBackendEnum
    backup_type: str
    data: dict[str, Any]
    protected: bool
    alert_on_fail: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: str | None = None
    last_updated_by: str | None = None


class BackupTaskDetailResponse(BackupTaskResponse):
    """Represent a single pgBackRest backup task detail response.

    Adds the executor host and port resolved from the task's YAML config so
    the FE detail view can render them alongside the parity Overview block;
    list rows omit these to keep the table response compact.

    :param host: The PostgreSQL host the task connects to.
    :type host: str | None
    :param port: The PostgreSQL port the task connects to.
    :type port: int | None
    """

    host: str | None = None
    port: int | None = None


class BackupExecuteWrite(BaseModel):
    """Represent a JSON request body for executing a backup task.

    :param eta: Optional datetime to schedule execution. Values in the past
        are dropped by the execute route and the task runs immediately.
    :type eta: datetime | None
    :param chain_task_names: Optional list of task names to chain after.
    :type chain_task_names: list[str] | None
    :param chain_on_failure: Whether to run chained tasks even on failure.
    :type chain_on_failure: bool | None
    """

    eta: datetime | None = None
    chain_task_names: list[str] | None = None
    chain_on_failure: bool | None = None


class BackupExecutionResponse(BaseModel):
    """Represent the response from the execute API endpoint.

    :param task_name: The name of the task that was executed.
    :type task_name: str
    :param task_id: The id of the task-history row created by the tasks API.
    :type task_id: int | None
    """

    task_name: str
    task_id: int | None = None
