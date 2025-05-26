"""Define models for the Backups plugin."""

from enum import StrEnum

from pydantic import field_validator

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import EnumFieldMixin, RequiredStr


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


class BackupConfig(BaseCaseInsensitiveModel):
    """Represent the overall backup configuration.

    :param pbm_config_payload: The PBM payload to parse from CLI.
    :type pbm_config_payload: RequiredStr | EmptyStrToNone
    """

    pitr_enabled: bool

    @field_validator("pitr_enabled")
    def empty_to_false(self, v: bool) -> bool:
        """If pitr checkbox in unchecked, represent as false."""
        if v is None:
            return False
        return v


class BackupCreate(BackupConfig):
    """Represent a Backup creation form with proper case-insensitive fields.

    :param task_name: The PBM yaml payload to parse from CLI.
    :type task_name: RequiredStr
    :param hostname: The PBM yaml payload to parse from CLI.
    :type hostname: RequiredStr
    :param service_id: Service for executing PBM.
    :type service_id: int
    :param backup_type: Type of backup activity on PBM.
    :type backup_type: BackupType
    """

    task_name: RequiredStr
    hostname: RequiredStr
    service_id: int
    backup_type: BackupType
