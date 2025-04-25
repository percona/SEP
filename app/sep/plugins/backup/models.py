"""Define models for the Backups plugin."""

from enum import auto, IntEnum, StrEnum
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

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


allowed_compressions = {
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

    @field_validator("compression_algorithm", mode="after")
    @classmethod
    def convert_compression_algorithm(
        cls, v: CompressionAlgorithm | None
    ) -> str | None:
        """Convert the compression algorithm to its corresponding value.

        :param v: The compression algorithm to potentially convert.
        :type v: CompressionAlgorithm or EmptyStrToNone
        :return: The converted compression algorithm value or the original value.
        :rtype: String | None
        """
        if isinstance(v, CompressionAlgorithm):
            return v.value
        return v


class BackupCreate(BackupConfigAll):
    """Represent a Backup creation form with proper case-insensitive fields."""

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
        :rtype: self
        :raises ValueError: If the compression_algorithm is not valid for the specified backup_type.
        """
        allowed_algorithms = allowed_compressions.get(self.backup_type)
        if (
            allowed_algorithms is not None
            and self.compression_algorithm is not None
            and self.compression_algorithm not in allowed_algorithms
        ):
            allowed_str = ", ".join(algo.name for algo in allowed_algorithms)
            raise ValueError(
                f"When backup_type is '{self.backup_type.name}', compression_algorithm must be one of: "
                f"{allowed_str}. Got: {self.compression_algorithm.name}"
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
