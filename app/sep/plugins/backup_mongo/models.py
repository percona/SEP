"""Define models for the Backups plugin."""

from enum import StrEnum
from typing import Optional

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import EmptyStrToNone, EnumFieldMixin, Field, RequiredStr


class BackupType(EnumFieldMixin, StrEnum):
    """Backup types."""

    PBM_LOGICAL = "pbm_logical"
    PBM_PHYSICAL = "pbm_physical"
    PBM_SNAPSHOT = "pbm_snapshot"
    PBM_CONFIG = "pbm_config"


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

    enabled: bool = False
    oplogSpanMin: int | None
    compression: RequiredStr


class BackupConfigStorageFilesystem(BaseCaseInsensitiveModel):
    """Represents a filesystem storage configuration."""

    path: RequiredStr | EmptyStrToNone = None
class BackupConfigStorageS3(BaseCaseInsensitiveModel):
    """Represents an S3 storage configuration."""

    region: RequiredStr | EmptyStrToNone = None
    bucket: RequiredStr | EmptyStrToNone = None
    prefix: RequiredStr | EmptyStrToNone = None
    endpointUrl: RequiredStr | EmptyStrToNone = None
class BackupConfigStorage(BaseCaseInsensitiveModel):
    """Represent Storage configuration."""

    type: StorageType
    s3: BackupConfigStorageS3 | None
    filesystem: BackupConfigStorageFilesystem | None
class BackupConfig(BaseCaseInsensitiveModel):
    """Represent the overall backup configuration.

    :param pbm_config_yaml_payload: The PBM yaml payload to parse from CLI.
    :type pbm_config_yaml_payload: RequiredStr | EmptyStrToNone
    """

    storage: BackupConfigStorage | EmptyStrToNone = None
    pitr: BackupConfigPITR | EmptyStrToNone = None
    pbm_config_yaml_payload: RequiredStr | EmptyStrToNone = Field(
        None, serialization_alias="pbm_config_yaml_payload"
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
