"""Define models for the Backups plugin."""

from enum import auto, IntEnum, StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import EmptyStrToNone, EnumFieldMixin, RequiredStr


class SwapDropEnum(IntEnum):
    """Enum for defining types of swap actions for table data handling."""

    PURGE_ONLY = 0
    SWAP_DROP = 1
    SWAP_ARCHIVE_DROP = 2


class BackupType(EnumFieldMixin, StrEnum):
    """Backup types."""

    MYDUMPER = "M"
    XTRABACKUP = "X"


class UploadProvider(EnumFieldMixin, StrEnum):
    """Upload providers."""

    RSYNC = auto()
    S3 = auto()


class DirEncryptConfig(BaseModel):
    """Represent the encryption configuration for the backup task.

    :param encryption_recipient: The recipient of the encryption key.
    :type encryption_recipient: RequiredStr | None
    """

    encryption_recipient: RequiredStr | None = Field(
        None, serialization_alias="encryption recipient"
    )


class BackupConfigAll(BaseCaseInsensitiveModel):
    """Represent the general configuration for the backup task."""

    hardlink: bool = True
    compress: bool = True
    check_disk_space: bool = True
    encrypt: bool | EmptyStrToNone = None
    encrypt_using_tmpdir: bool | EmptyStrToNone = None
    only_if_running_slave: bool = False
    only_if_read_only: bool = False
    logging_dir: str | EmptyStrToNone = None
    backup_dir: str | EmptyStrToNone = None
    defaults_file: str | EmptyStrToNone = None
    mydumper_daily_purge: int | EmptyStrToNone = None
    mydumper_weekly_purge: int | EmptyStrToNone = None
    mydumper_schemas: bool | EmptyStrToNone = None
    mydumper_dump_triggers: bool | EmptyStrToNone = None
    mydumper_desync_pxc: bool | EmptyStrToNone = None
    mydumper_less_locking: bool | EmptyStrToNone = None
    mydumper_use_numa: bool | EmptyStrToNone = None
    mydumper_extra_args: str | EmptyStrToNone = None
    use_ftwrl_guardian: bool | EmptyStrToNone = None
    xtrabackup_copies: int | EmptyStrToNone = None
    xtrabackup_kill_queries: bool | EmptyStrToNone = None
    xtrabackup_kill_queries_timeout: int | EmptyStrToNone = None
    xtrabackup_kill_query_type: Literal["select", "all"] | EmptyStrToNone = None
    xtrabackup_verify: bool | EmptyStrToNone = None
    xtrabackup_prepare: bool | EmptyStrToNone = None
    xtrabackup_prepare_memory: str | EmptyStrToNone = None
    xtrabackup_desync_pxc: bool | EmptyStrToNone = None
    xtrabackup_rsync: bool | EmptyStrToNone = None
    xtrabackup_slave_info: bool | EmptyStrToNone = None
    xtrabackup_defaults_file: str | EmptyStrToNone = None
    xtrabackup_extra_args: str | EmptyStrToNone = None
    xtrabackup_incremental_method: (
        Literal["less_space", "fast_restore"] | EmptyStrToNone
    ) = None
    xtrabackup_incremental_cycle: Literal["daily", "weekly"] | EmptyStrToNone = None
    xtrabackup_local_ssh_destination: str | EmptyStrToNone = None
    xtrabackup_aes256_keyfile: str | EmptyStrToNone = None
    xtrabackup_stop_slave: bool | EmptyStrToNone = None
    xtrabackup_lock_ddl: bool | EmptyStrToNone = None
    xtrabackup_bin_cmd: (
        Literal["xtrabackup", "mariadb-backup", "innobackupex"] | EmptyStrToNone
    ) = None
    s3_bucket: str | EmptyStrToNone = None
    s3_storage_class: str | EmptyStrToNone = None
    skip_s3_safety_check: bool | EmptyStrToNone = None
    rsync_path: str | EmptyStrToNone = None


class BackupCreate(BackupConfigAll):
    """Represent a Backup creation form with proper case-insensitive fields."""

    task_name: RequiredStr
    hostname: RequiredStr
    service_id: int
    backup_type: BackupType
    encryption_recipient: RequiredStr | EmptyStrToNone = None


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
    :param upload: A unique list of upload providers to use for the backup, if any.
    :type upload: UniqueList[UploadProvider] | None
    :param dir_encrypt_config: Specific configuration for the backup encryption.
    :type dir_encrypt_config: DirEncryptConfig | None
    """

    alias: RequiredStr
    backup_type: str
    host: RequiredStr
    port: int | None
    upload: list[str] | None = None
    dir_encrypt_config: DirEncryptConfig | None = None


class BackupConfig(BaseCaseInsensitiveModel):
    """Represent the overall backup configuration.

    :param all_servers: General settings for the backup.
    :type all_servers: BackupConfigAll
    :param server_list: A list of backup configuration for each server.
    :type server_list: list[BackupConfigServer]
    """

    all_servers: BackupConfigAll
    server_list: list[BackupConfigServer]
