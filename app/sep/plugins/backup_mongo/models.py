"""Define models for the Backups plugin."""

from enum import Enum, StrEnum

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import EnumFieldMixin, RequiredStr


class BackupType(EnumFieldMixin, StrEnum):
    """Backup types."""

    pbm_logical = "pbm_logical"
    pbm_physical = "pbm_physical"
    pbm_snapshot = "pbm_snapshot"
    pbm_config = "pbm_config"


class StorageType(str, Enum):
    """Represents whe PBM should keep datafiles."""

    s3 = "s3"
    filesystem = "filesystem"
    azure = "azure"


class S3Provider(str, Enum):
    """Represents native s3 or plugins what use s3 protocol."""

    aws = "aws"
    minio = "minio"
    gcp = "gcp"


class CompressionAlgorithm(str, Enum):
    """Represents algorithm of choice whem compressing wirteTiger datafiles."""

    gzip = "gzip"
    snappy = "snappy"
    lz4 = "lz4"
    s2 = "s2"
    pgzip = "pgzip"
    zstd = "zstd"


class LogLevel(str, Enum):
    """Represents log verbosity of PBM service."""

    debug = "debug"
    info = "info"
    warn = "warn"
    error = "error"


class LogOutput(str, Enum):
    """Determines output of log."""

    stdout = "stdout"
    file = "file"
    syslog = "syslog"


class BackupConfig(BaseCaseInsensitiveModel):
    """Represent the overall backup configuration."""


class BackupCreate(BackupConfig):
    """Represent a Backup creation form with proper case-insensitive fields."""

    task_name: RequiredStr
    hostname: RequiredStr
    service_id: int
    backup_type: BackupType
