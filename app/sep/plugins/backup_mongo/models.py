"""Define models for the Backups plugin."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel,Field

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import EmptyStrToNone, EnumFieldMixin, RequiredStr
from typing import Optional, List
from enum import Enum


class BackupType(EnumFieldMixin, StrEnum):
    """Backup types."""
    LOGICAL = "logical"
    PHYSICAL = "physical"
    SNAPSHOT = "snapshot"
    CONFIG = "config"

class StorageType(str, Enum):
    s3 = "s3"
    filesystem = "filesystem"
    azure = "azure"

class S3Provider(str, Enum):
    aws = "aws"
    minio = "minio"
    gcp = "gcp"

class CompressionAlgorithm(str, Enum):
    gzip = "gzip"
    snappy = "snappy"
    lz4 = "lz4"
    s2 = "s2"
    pgzip = "pgzip"
    zstd = "zstd"

class LogLevel(str, Enum):
    debug = "debug"
    info = "info"
    warn = "warn"
    error = "error"

class LogOutput(str, Enum):
    stdout = "stdout"
    file = "file"
    syslog = "syslog"

class S3Options(BaseModel):
    s3_provider: Optional[S3Provider] = Field(None, description="S3 Provider")
    s3_region: Optional[str] = Field(None, description="Region")
    s3_bucket: Optional[str] = Field(None, description="Bucket Name")
    s3_prefix: Optional[str] = Field(None, description="Prefix (Optional)")
    s3_endpoint_url: Optional[str] = Field(None, description="Endpoint URL (Optional)")
    s3_endpoint_url_map: Optional[str] = Field(None, description="Endpoint URL Map (Optional)")
    s3_force_path_style: Optional[bool] = Field(False, description="Force Path Style")
    s3_access_key_id: Optional[str] = Field(None, description="Access Key ID")
    s3_secret_access_key: Optional[str] = Field(None, description="Secret Access Key")
    s3_session_token: Optional[str] = Field(None, description="Session Token (Optional)")
    s3_upload_part_size: Optional[int] = Field(None, description="Upload Part Size (Bytes, Optional)")
    s3_max_upload_parts: Optional[int] = Field(None, description="Max Upload Parts (Optional)")
    s3_storage_class: Optional[str] = Field(None, description="Storage Class (Optional)")
    s3_debug_log_levels: Optional[str] = Field(None, description="Debug Log Levels (Optional)")
    s3_insecure_skip_tls_verify: Optional[bool] = Field(False, description="Insecure Skip TLS Verify")

class FilesystemOptions(BaseModel):
    filesystem_path: Optional[str] = Field(None, description="Filesystem Path")

class AzureOptions(BaseModel):
    azure_account: Optional[str] = Field(None, description="Account Name")
    azure_container: Optional[str] = Field(None, description="Container Name")
    azure_endpoint_url: Optional[str] = Field(None, description="Endpoint URL (Optional)")
    azure_prefix: Optional[str] = Field(None, description="Prefix (Optional)")
    azure_account_key: Optional[str] = Field(None, description="Account Key")

class StorageConfiguration(BaseModel):
    storage_type: StorageType = Field(..., description="Storage Type")
    s3_options: Optional[S3Options] = None
    filesystem_options: Optional[FilesystemOptions] = None
    azure_options: Optional[AzureOptions] = None
    sse_algorithm: Optional[str] = Field(None, description="Server-Side Encryption Algorithm")
    sse_kms_key_id: Optional[str] = Field(None, description="KMS Key ID (If SSE-KMS)")
    sse_customer_algorithm: Optional[str] = Field(None, description="SSE Customer Algorithm (If SSE-C)")
    sse_customer_key: Optional[str] = Field(None, description="SSE Customer Key (If SSE-C)")
    retryer_num_max_retries: Optional[int] = Field(None, description="Max Retries")
    retryer_min_retry_delay: Optional[str] = Field(None, description="Min Retry Delay")
    retryer_max_retry_delay: Optional[str] = Field(None, description="Max Retry Delay")

class PITRConfiguration(BaseModel):
    pitr_enabled: Optional[bool] = Field(False, description="Enable PITR")
    pitr_oplog_span_min: Optional[int] = Field(None, description="Oplog Span (Minutes)")
    pitr_compression: Optional[CompressionAlgorithm] = Field(None, description="Compression")

class BackupOptions(BaseModel):
    backup_priority: Optional[str] = Field(None, description="Node Priority for Backup (Comma-separated, Optional)")
    backup_compression: Optional[CompressionAlgorithm] = Field(None, description="Backup Compression")
    backup_compression_level: Optional[int] = Field(None, description="Backup Compression Level (Optional)")
    backup_timeouts_starting_status: Optional[int] = Field(None, description="Starting Status Timeout (Seconds)")
    backup_num_parallel_collections: Optional[int] = Field(None, description="Parallel Collections for Logical Backup")

class RestoreOptions(BaseModel):
    restore_batch_size: Optional[int] = Field(None, description="Restore Batch Size")

class LogFileOptions(BaseModel):
    log_file_path: Optional[str] = Field(None, description="Log File Path (If Output is file)")
    log_file_rotate_size: Optional[str] = Field(None, description="Log File Rotate Size")
    log_file_rotate_count: Optional[int] = Field(None, description="Log File Rotate Count")

class LoggingOptions(BaseModel):
    log_level: Optional[LogLevel] = Field(None, description="Log Level")
    log_output: Optional[LogOutput] = Field(None, description="Log Output")
    log_file_options: Optional[LogFileOptions] = None

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
    """Represent the overall backup configuration."""
    pitr_configuration: Optional[PITRConfiguration] = None
    backup_options: Optional[BackupOptions] = None
    restore_options: Optional[RestoreOptions] = None
    logging_options: Optional[LoggingOptions] = None
    storage_configuration: Optional[StorageConfiguration] = None
    
class BackupCreate(BackupConfig):
    """Represent a Backup creation form with proper case-insensitive fields."""
    task_name: RequiredStr
    hostname: RequiredStr
    service_id: int
    backup_type: BackupType
