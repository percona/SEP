"""Define models for the Backups plugin."""

from enum import StrEnum
from typing import Literal

from pydantic import Field

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import EmptyStrToNone, EnumFieldMixin, RequiredStr


class BackupType(EnumFieldMixin, StrEnum):
    """Backup types."""

    LOGICAL = "L"
    PHYSICAL = "P"
    SNAPSHOT = "S"

class BackupConfigAll(BaseCaseInsensitiveModel):
    """Represent the general configuration for the backup task."""

    backup_dir: RequiredStr | EmptyStrToNone = None
    defaults_file: RequiredStr | EmptyStrToNone = None
    pbm_bin_cmd: (
        Literal["xtrabackup", "mariadb-backup", "innobackupex"] | EmptyStrToNone
    ) = None
    s3_bucket: RequiredStr | EmptyStrToNone = None
    s3_storage_class: RequiredStr | EmptyStrToNone = None
    skip_s3_safety_check: bool = False
    rsync_path: RequiredStr | EmptyStrToNone = None


class BackupCreate(BackupConfigAll):
    """Represent a Backup creation form with proper case-insensitive fields."""

    task_name: RequiredStr
    hostname: RequiredStr
    service_id: int
    backup_type: BackupType


class BackupConfigServer(BaseCaseInsensitiveModel):
    """Represent an individual server configuration.

    :param alias: A unique alias for the server.
    :type alias: RequiredStr
    :param backup_type: The type of the backup.
    :type backup_type: BackupType
    :param host: The hostname or address of the server.
    :type host: RequiredStr
    :param port: The port number used to connect to the host.
    :type port: int | None
    """

    alias: RequiredStr
    backup_type: str
    host: RequiredStr
    port: int | None


class BackupConfig(BaseCaseInsensitiveModel):
    """Represent the overall backup configuration.

    :param all_servers: General settings for the backup.
    :type all_servers: BackupConfigAll
    :param server_list: A list of backup configuration for each server.
    :type server_list: list[BackupConfigServer]
    """

    all_servers: BackupConfigAll
    server_list: list[BackupConfigServer]
