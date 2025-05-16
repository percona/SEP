"""Define models for the Backups plugin."""

from enum import auto, IntEnum, StrEnum
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

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
    BINLOG = "B"


class CompressionAlgorithm(EnumFieldMixin, StrEnum):
    """Enumeration for Compression Algorithms."""

    ZSTD = "zstd"
    LZ4 = "lz4"
    GZIP = "gzip"


ALLOWED_COMPRESSIONS = {
    BackupType.MYDUMPER: [CompressionAlgorithm.GZIP, CompressionAlgorithm.ZSTD],
    BackupType.XTRABACKUP: [CompressionAlgorithm.ZSTD, CompressionAlgorithm.LZ4],
    BackupType.BINLOG: [CompressionAlgorithm.GZIP],
}


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

    hardlink: bool = False
    compress: bool = False
    check_disk_space: bool = False
    encrypt: bool = False
    encrypt_using_tmpdir: bool = False
    only_if_running_replica: bool = False
    only_if_read_only: bool = False
    logging_dir: RequiredStr | EmptyStrToNone = None
    backup_dir: RequiredStr | EmptyStrToNone = None
    defaults_file: RequiredStr | EmptyStrToNone = None
    compression_algorithm: CompressionAlgorithm | EmptyStrToNone = None
    mydumper_daily_purge: int | EmptyStrToNone = None
    mydumper_weekly_purge: int | EmptyStrToNone = None
    mydumper_dump_triggers: bool = False
    mydumper_desync_pxc: bool = False
    mydumper_less_locking: bool = False
    mydumper_use_numa: bool = False
    mydumper_extra_args: str | EmptyStrToNone = None
    use_ftwrl_guardian: bool = False
    xtrabackup_copies: int | EmptyStrToNone = None
    xtrabackup_kill_queries: bool = False
    xtrabackup_kill_queries_timeout: int | EmptyStrToNone = None
    xtrabackup_kill_query_type: Literal["select", "all"] | EmptyStrToNone = None
    xtrabackup_verify: bool = False
    xtrabackup_prepare: bool = False
    xtrabackup_prepare_memory: RequiredStr | EmptyStrToNone = None
    xtrabackup_desync_pxc: bool = False
    xtrabackup_rsync: bool = False
    xtrabackup_replica_info: bool = False
    xtrabackup_defaults_file: RequiredStr | EmptyStrToNone = None
    xtrabackup_extra_args: RequiredStr | EmptyStrToNone = None
    xtrabackup_incremental_method: (
        Literal["less_space", "fast_restore"] | EmptyStrToNone
    ) = None
    xtrabackup_incremental_cycle: Literal["daily", "weekly"] | EmptyStrToNone = None
    xtrabackup_local_ssh_destination: RequiredStr | EmptyStrToNone = None
    xtrabackup_aes256_keyfile: RequiredStr | EmptyStrToNone = None
    xtrabackup_stop_replica: bool = False
    xtrabackup_lock_ddl: bool = False
    xtrabackup_bin_cmd: (
        Literal["xtrabackup", "mariadb-backup", "innobackupex"] | EmptyStrToNone
    ) = None
    binlog_prefix: RequiredStr | EmptyStrToNone = None
    binlog_purge_days: int | EmptyStrToNone = None
    binlog_extra_args: RequiredStr | EmptyStrToNone = None
    binlog_compress_cmd: RequiredStr | EmptyStrToNone = None
    binlog_cmd: RequiredStr | EmptyStrToNone = None
    binlog_run_all: bool = True
    s3_bucket: RequiredStr | EmptyStrToNone = None
    s3_storage_class: RequiredStr | EmptyStrToNone = None
    skip_s3_safety_check: bool = False
    rsync_path: RequiredStr | EmptyStrToNone = None


class BackupCreate(BackupConfigAll):
    """Represent a Backup creation form with proper case-insensitive fields.

    :param hardlink: Whether to use hardlinks for full backups to save space.
    :type hardlink: bool
    :param compress: Whether to enable compression for backup data.
    :type compress: bool
    :param check_disk_space: Whether to check disk space before starting the backup.
    :type check_disk_space: bool
    :param encrypt: Whether to enable encryption for backup data.
    :type encrypt: bool
    :param encrypt_using_tmpdir: Whether to use a temporary directory for encryption operations.
    :type encrypt_using_tmpdir: bool
    :param only_if_running_replica: Only perform backup if the server is a replica.
    :type only_if_running_replica: bool
    :param only_if_read_only: Only perform backup if the server is in read-only mode.
    :type only_if_read_only: bool
    :param logging_dir: Directory where logs are stored.
    :type logging_dir: RequiredStr | EmptyStrToNone
    :param backup_dir: Directory where backups are stored.
    :type backup_dir: RequiredStr | EmptyStrToNone
    :param defaults_file: Path to the MySQL defaults file.
    :type defaults_file: RequiredStr | EmptyStrToNone
    :param compression_algorithm: Compression algorithm to use.
    :type compression_algorithm: CompressionAlgorithm | EmptyStrToNone
    :param mydumper_daily_purge: Number of days to keep daily mydumper backups.
    :type mydumper_daily_purge: int | EmptyStrToNone
    :param mydumper_weekly_purge: Number of weeks to keep weekly mydumper backups.
    :type mydumper_weekly_purge: int | EmptyStrToNone
    :param mydumper_dump_triggers: Whether to include database triggers with mydumper.
    :type mydumper_dump_triggers: bool
    :param mydumper_desync_pxc: Whether to desynchronize PXC node before mydumper backup.
    :type mydumper_desync_pxc: bool
    :param mydumper_less_locking: Whether to use less locking during mydumper backup.
    :type mydumper_less_locking: bool
    :param mydumper_use_numa: Whether to enable NUMA support during mydumper backup.
    :type mydumper_use_numa: bool
    :param mydumper_extra_args: Additional command-line arguments for mydumper.
    :type mydumper_extra_args: str | EmptyStrToNone
    :param use_ftwrl_guardian: Whether to use FTWRL guardian to manage locks during backup.
    :type use_ftwrl_guardian: bool
    :param xtrabackup_copies: Number of backup copies for xtrabackup.
    :type xtrabackup_copies: int | EmptyStrToNone
    :param xtrabackup_kill_queries: Whether to terminate long-running queries.
    :type xtrabackup_kill_queries: bool
    :param xtrabackup_kill_queries_timeout: Maximum time (in seconds) to wait before terminating queries.
    :type xtrabackup_kill_queries_timeout: int | EmptyStrToNone
    :param xtrabackup_kill_query_type: Type of queries to avoid backup interruptions (select or all).
    :type xtrabackup_kill_query_type: Literal["select", "all"] | EmptyStrToNone
    :param xtrabackup_verify: Whether to verify backup after creation.
    :type xtrabackup_verify: bool
    :param xtrabackup_prepare: Whether to prepare the backup for restore.
    :type xtrabackup_prepare: bool
    :param xtrabackup_prepare_memory: Amount of memory allocated during prepare phase.
    :type xtrabackup_prepare_memory: RequiredStr | EmptyStrToNone
    :param xtrabackup_desync_pxc: Whether to desynchronize PXC node during xtrabackup.
    :type xtrabackup_desync_pxc: bool
    :param xtrabackup_rsync: Whether to use rsync for file copying in xtrabackup.
    :type xtrabackup_rsync: bool
    :param xtrabackup_replica_info: Whether to include replica info in xtrabackup.
    :type xtrabackup_replica_info: bool
    :param xtrabackup_defaults_file: Path to the defaults file for xtrabackup.
    :type xtrabackup_defaults_file: RequiredStr | EmptyStrToNone
    :param xtrabackup_extra_args: Additional command-line arguments passed to xtrabackup.
    :type xtrabackup_extra_args: RequiredStr | EmptyStrToNone
    :param xtrabackup_incremental_method: Method used for incremental backup.
    :type xtrabackup_incremental_method: Literal["less_space", "fast_restore"] | EmptyStrToNone
    :param xtrabackup_incremental_cycle: Frequency of incremental backups.
    :type xtrabackup_incremental_cycle: Literal["daily", "weekly"] | EmptyStrToNone
    :param xtrabackup_local_ssh_destination: SSH destination for storing backups remotely.
    :type xtrabackup_local_ssh_destination: RequiredStr | EmptyStrToNone
    :param xtrabackup_aes256_keyfile: Path to AES-256 encryption key file.
    :type xtrabackup_aes256_keyfile: RequiredStr | EmptyStrToNone
    :param xtrabackup_stop_replica: Whether to stop the replica before xtrabackup.
    :type xtrabackup_stop_replica: bool
    :param xtrabackup_lock_ddl: Whether to lock DDL operations during backup.
    :type xtrabackup_lock_ddl: bool
    :param xtrabackup_bin_cmd: Backup tool to use.
    :type xtrabackup_bin_cmd: Literal["xtrabackup", "mariadb-backup", "innobackupex"] | EmptyStrToNone
    :param binlog_prefix: Prefix used in binlog backup naming.
    :type binlog_prefix: RequiredStr | EmptyStrToNone
    :param binlog_purge_days: Number of days to retain binlogs before purging.
    :type binlog_purge_days: int | EmptyStrToNone
    :param binlog_extra_args: Extra arguments for binlog backup command.
    :type binlog_extra_args: RequiredStr | EmptyStrToNone
    :param binlog_compress_cmd: Command used to compress binlog backups.
    :type binlog_compress_cmd: RequiredStr | EmptyStrToNone
    :param binlog_cmd: Command used to create binlog backups.
    :type binlog_cmd: RequiredStr | EmptyStrToNone
    :param binlog_run_all: Whether to run all binlog backup types.
    :type binlog_run_all: bool
    :param s3_bucket: S3 bucket where backups will be stored.
    :type s3_bucket: RequiredStr | EmptyStrToNone
    :param s3_storage_class: S3 storage class (e.g., STANDARD, GLACIER).
    :type s3_storage_class: RequiredStr | EmptyStrToNone
    :param skip_s3_safety_check: Whether to disable safety checks before uploading to S3.
    :type skip_s3_safety_check: bool
    :param rsync_path: Remote destination path for Rsync transfers.
    :type rsync_path: RequiredStr | EmptyStrToNone
    :param task_name: The name of the backup task.
    :type task_name: RequiredStr
    :param hostname: The hostname of the machine to back up.
    :type hostname: RequiredStr
    :param service_id: The identifier of the related service.
    :type service_id: int
    :param backup_type: The type of backup to perform.
    :type backup_type: BackupType
    :param encryption_recipient: The recipient used for encryption.
    :type encryption_recipient: RequiredStr | EmptyStrToNone
    :param binlog_alternative_host: Optional alternative host for binlog operations.
    :type binlog_alternative_host: RequiredStr | EmptyStrToNone
    """

    task_name: RequiredStr
    hostname: RequiredStr
    service_id: int
    backup_type: BackupType
    encryption_recipient: RequiredStr | EmptyStrToNone = None
    binlog_alternative_host: RequiredStr | EmptyStrToNone = None

    @model_validator(mode="after")
    def validate_compression_algorithm(self) -> Self:
        """Validate that the compression_algorithm is compatible with the selected backup_type.

        :return: The validated instance
        :rtype: Self
        :raises ValueError: If the compression_algorithm is not valid for the specified backup_type.
        """
        allowed_algorithms = ALLOWED_COMPRESSIONS.get(self.backup_type, [])
        if (
            self.compression_algorithm is not None
            and self.compression_algorithm not in allowed_algorithms
        ):
            raise ValueError(
                f"Invalid compression algorithm {self.compression_algorithm!r} for "
                f"{self.backup_type.name} backup. Options are {allowed_algorithms}"
            )

        return self


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
