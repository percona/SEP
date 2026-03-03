# Copyright 2026 Percona LLC
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

from enum import StrEnum

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import EmptyStrToNone, EnumFieldMixin, NonEmptyStr


class BackupType(EnumFieldMixin, StrEnum):
    """Backup types."""

    PGBACKREST = "P"


class PgBackRestBackupType(EnumFieldMixin, StrEnum):
    """PgBackRest backup types."""

    INCR = "incr"
    DIFF = "diff"


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
