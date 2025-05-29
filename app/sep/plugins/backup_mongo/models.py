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

class S3Provider(StrEnum):
    """Represents native s3 or plugins what use s3 protocol."""
    AWS = "aws"
    GCS = "gcs"


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
    debug = 'D'
    info = 'I'
    warn = 'W'
    error = 'E'
class BackupConfig(BaseCaseInsensitiveModel):
    """Represent the overall backup configuration.

    :param pitr_enabled: Enable or disable Oplog fetching.
    :type pitr_enabled: bool
    :param log_path: The path to the log file. The file is created if it doesn't exist. The default value is /dev/stderr
    :type log_path: RequiredStr | EmptyStrToNone
    :param log_level: The log severity level. Supported levels are (from low to high): D - Debug (default), I - Info, W - Warning, E - Error, F - Fatal.
    :type log_level: StrEnum
    :param log_json: Output log messages in JSON format. If unchecked, logs are written in the default text format.
    :type log_json: bool

    """
    pitr_enabled: bool
    s3_provider: S3Provider
    @classmethod
    @field_validator("pitr_enabled", "log_json")
    def empty_to_false(cls, *, v: bool) -> bool:
        """If pitr checkbox is unchecked, represent as false."""
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
