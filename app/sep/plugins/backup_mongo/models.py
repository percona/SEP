"""Define models for the Backups plugin."""

from enum import StrEnum
from typing import Annotated

from pydantic import AliasChoices, ConfigDict, Field

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import EmptyStrToNone, EnumFieldMixin, RequiredStr


class BackupType(EnumFieldMixin, StrEnum):
    """Backup types."""

    PBM_LOGICAL = "pbm_logical"
    PBM_PHYSICAL = "pbm_physical"
    PBM_SNAPSHOT = "pbm_snapshot"
    PBM_CONFIG = "pbm_config"
    PBM_STATUS = "pbm_status"


class StorageType(StrEnum):
    """Represents whe PBM should keep datafiles."""

    S3 = "s3"
    FILESYSTEM = "filesystem"
    AZUER = "azure"


class S3Provider(StrEnum):
    """Represents native s3 or plugins what use s3 protocol."""

    AWS = "aws"
    MINIO = "minio"
    GCP = "gcp"


class CompressionAlgorithm(StrEnum):
    """Represents algorithm of choice whem compressing wirteTiger datafiles."""

    GZIP = "gzip"
    SNAPPY = "snappy"
    LZ4 = "lz4"
    S2 = "s2"
    PGZIP = "pgzip"
    ZSTD = "zstd"


class LogLevel(StrEnum):
    """Represents log verbosity of PBM service."""

    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class LogOutput(StrEnum):
    """Determines output of log."""

    STDOUT = "stdout"
    FILE = "file"
    SYSLOG = "syslog"


class BackupConfigPITR(BaseCaseInsensitiveModel):
    """Represent Point In Time Recovery configuration.

    :param enabled: PITR enabled.
    :type enabled: bool
    :param oplogSpanMin: The PBM ...
    :type oplogSpanMin: int
    :param compression: Compression ... PBM.
    :type compression: RequiredStr
    """

    model_config = ConfigDict(alias_generator=None)

    enabled: bool = Field(
        default=False, validation_alias=AliasChoices("enabled", "ENABLED")
    )
    oplog_span_min: int | None = Field(
        None,
        validation_alias=AliasChoices("oplogSpanMin", "OPLOGSPANMIN"),
        serialization_alias="oplogSpanMin",
    )
    compression: Annotated[
        RequiredStr, Field(validation_alias=AliasChoices("compression", "COMPRESSION"))
    ]


class BackupConfigBackupTimeouts(BaseCaseInsensitiveModel):
    """Represent backup timeout configuration.

    :param startingStatus: Wait time (in seconds) for PBM to start backups.
    :type startingStatus: int | None
    """

    model_config = ConfigDict(alias_generator=None)

    starting_status: int | None = Field(
        None,
        validation_alias=AliasChoices("startingStatus", "STARTINGSTATUS"),
        serialization_alias="startingStatus",
    )


class BackupConfigBackup(BaseCaseInsensitiveModel):
    """Represent backup configuration options.

    :param priority: Dictionary mapping mongod node addresses to their priority for making backups.
        The node with the highest priority is elected for making a backup.
    :type priority: dict[str, float] | EmptyStrToNone
    :param compression: Compression method for backup snapshots.
    :type compression: CompressionAlgorithm | EmptyStrToNone
    :param compressionLevel: Compression level (depends on compression method).
    :type compressionLevel: int | EmptyStrToNone
    :param timeouts: Backup timeout configuration.
    :type timeouts: BackupConfigBackupTimeouts | EmptyStrToNone
    :param oplogSpanMin: Duration (in minutes) of oplog slices saved with logical backup.
    :type oplogSpanMin: float | EmptyStrToNone
    :param numParallelCollections: Number of parallel collections to process during logical backup.
    :type numParallelCollections: int | EmptyStrToNone
    """

    model_config = ConfigDict(alias_generator=None)

    priority: dict[str, float] | EmptyStrToNone = Field(
        None, validation_alias=AliasChoices("priority", "PRIORITY")
    )
    compression: CompressionAlgorithm | EmptyStrToNone = Field(
        None, validation_alias=AliasChoices("compression", "COMPRESSION")
    )
    compression_level: int | EmptyStrToNone = Field(
        None,
        validation_alias=AliasChoices("compressionLevel", "COMPRESSIONLEVEL"),
        serialization_alias="compressionLevel",
    )
    timeouts: BackupConfigBackupTimeouts | EmptyStrToNone = Field(
        None, validation_alias=AliasChoices("timeouts", "TIMEOUTS")
    )
    oplog_span_min: float | EmptyStrToNone = Field(
        None,
        validation_alias=AliasChoices("oplogSpanMin", "OPLOGSPANMIN"),
        serialization_alias="oplogSpanMin",
    )
    num_parallel_collections: int | EmptyStrToNone = Field(
        None,
        validation_alias=AliasChoices(
            "numParallelCollections", "NUMPARALLELCOLLECTIONS"
        ),
        serialization_alias="numParallelCollections",
    )


class BackupConfigStorageFilesystem(BaseCaseInsensitiveModel):
    """Represents a filesystem storage configuration."""

    model_config = ConfigDict(alias_generator=None)

    path: RequiredStr | EmptyStrToNone = Field(
        None, validation_alias=AliasChoices("path", "PATH")
    )


class BackupConfigStorageS3(BaseCaseInsensitiveModel):
    """Represents an S3 storage configuration."""

    model_config = ConfigDict(alias_generator=None)

    region: RequiredStr | EmptyStrToNone = Field(
        None, validation_alias=AliasChoices("region", "REGION")
    )
    bucket: RequiredStr | EmptyStrToNone = Field(
        None, validation_alias=AliasChoices("bucket", "BUCKET")
    )
    prefix: RequiredStr | EmptyStrToNone = Field(
        None, validation_alias=AliasChoices("prefix", "PREFIX")
    )
    endpoint_url: RequiredStr | EmptyStrToNone = Field(
        None,
        validation_alias=AliasChoices("endpointUrl", "ENDPOINTURL"),
        serialization_alias="endpointUrl",
    )


class BackupConfigStorage(BaseCaseInsensitiveModel):
    """Represent Storage configuration."""

    model_config = ConfigDict(alias_generator=None)

    type: StorageType = Field(..., validation_alias=AliasChoices("type", "TYPE"))
    s3: BackupConfigStorageS3 | EmptyStrToNone = Field(
        None, validation_alias=AliasChoices("s3", "S3")
    )
    filesystem: BackupConfigStorageFilesystem | EmptyStrToNone = Field(
        None, validation_alias=AliasChoices("filesystem", "FILESYSTEM")
    )


class BackupConfig(BaseCaseInsensitiveModel):
    """Represent the overall backup configuration.

    :param pbm_config_yaml_payload: The PBM yaml payload to parse from CLI.
    :type pbm_config_yaml_payload: RequiredStr | EmptyStrToNone
    """

    model_config = ConfigDict(alias_generator=None)

    storage: BackupConfigStorage | EmptyStrToNone = Field(
        None, validation_alias=AliasChoices("storage", "STORAGE")
    )
    pitr: BackupConfigPITR | EmptyStrToNone = Field(
        None, validation_alias=AliasChoices("pitr", "PITR")
    )
    backup: BackupConfigBackup | EmptyStrToNone = Field(
        None, validation_alias=AliasChoices("backup", "BACKUP")
    )
    pbm_config_yaml_payload: RequiredStr | EmptyStrToNone = Field(
        None,
        validation_alias=AliasChoices(
            "pbm_config_yaml_payload", "PBM_CONFIG_YAML_PAYLOAD"
        ),
        serialization_alias="pbm_config_yaml_payload",
    )


class BackupCreate(BaseCaseInsensitiveModel):
    """Represent a Backup creation form with proper case-insensitive fields.

    :param task_name: The PBM yaml payload to parse from CLI.
    :type task_name: RequiredStr
    :param hostname: The PBM yaml payload to parse from CLI.
    :type hostname: RequiredStr
    :param service_id: Service for executing PBM.
    :type service_id: int
    :param backup_type: Type of backup activity on PBM.
    :type backup_type: BackupType
    :param alert_on_fail: If True, send an alert if the task fails. Defaults to False.
    :type alert_on_fail: bool
    """

    task_name: RequiredStr
    hostname: RequiredStr
    service_id: int
    backup_type: BackupType
    alert_on_fail: bool = False
    pitr_oplog_span_min: int | EmptyStrToNone = None
    pitr_enabled: bool = False
    pitr_compression: RequiredStr | EmptyStrToNone = None
    storage_type: RequiredStr | EmptyStrToNone = None
    storage_s3_region: RequiredStr | EmptyStrToNone = None
    storage_s3_bucket: RequiredStr | EmptyStrToNone = None
    storage_s3_prefix: RequiredStr | EmptyStrToNone = None
    storage_s3_endpoint_url: RequiredStr | EmptyStrToNone = None
    storage_filesystem_path: RequiredStr | EmptyStrToNone = None
    # Backup options
    backup_priority: RequiredStr | EmptyStrToNone = None
    backup_compression: CompressionAlgorithm | EmptyStrToNone = None
    backup_compression_level: int | EmptyStrToNone = None
    backup_timeouts_starting_status: int | EmptyStrToNone = None
    backup_oplog_span_min: float | EmptyStrToNone = None
    backup_num_parallel_collections: int | EmptyStrToNone = None
