"""Define models for the Backups plugin."""

from enum import StrEnum
from urllib.parse import urlparse

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
    MINIO = "minio"


class S3RegionForm(BaseCaseInsensitiveModel):
    """Represents the Region of s3 compatible service."""

    provider: S3Provider
    region: str

    @classmethod
    @field_validator("region")
    def validate_region(cls, value: str, values: dict) -> str:
        """Check if s3 region is a valid one."""
        provider = values.get("provider")
        if provider == "aws":
            # Define prefixes and exact matches for AWS regions
            aws_region_prefixes = ("us-", "eu-", "ap-", "sa-")
            aws_region_exact_matches = (
                "ca-central-1",
                "me-south-1",
                "af-south-1",
            )

        # Check if the value starts with any of the prefixes OR is an exact match
        if not (
            value.startswith(aws_region_prefixes) or value in aws_region_exact_matches
        ):
            raise ValueError(f"Invalid AWS region: '{value}'.")

        if provider == "gcs":
            # Define prefixes for Google Cloud Storage regions
            gcs_region_prefixes = (
                "us-",
                "europe-",
                "asia-",
                "australia-",
                "southamerica-",
            )

        # Check if the value starts with any of the GCS prefixes
        if not value.startswith(gcs_region_prefixes):
            raise ValueError(f"Invalid GCS region: '{value}'.")
        if provider == "minio" and not value:
            raise ValueError("MinIO region cannot be empty.")
        return value


class S3BucketForm(BaseCaseInsensitiveModel):
    """Represents a valid bucket name."""

    bucket: str

    @classmethod
    @field_validator("bucket")
    def validate_bucket_name(cls, value: str) -> str:
        """Validate an AWS S3 bucket name based on AWS rules.

        Rules (simplified):
        - 3 to 63 characters long.
        - Can contain lowercase letters, numbers, periods (.), and hyphens (-).
        - Must start and end with a letter or a number.
        - Cannot be formatted as an IP address (e.g., 192.168.5.4).
        """
        max_bucket_name_length = 63

        if not (len(value) <= max_bucket_name_length):
            raise ValueError("Bucket name must be between 3 and 63 characters long.")
        return value


class S3PrefixForm(BaseCaseInsensitiveModel):
    """Represents a valid prefix name."""

    prefix: str

    @classmethod
    @field_validator("prefix")
    def validate_prefix(cls, value: str) -> str:
        """Validate an S3 prefix, disallowing spaces."""
        max_len = 1024
        if " " in value:
            raise ValueError("Prefix cannot contain spaces.")

        if "\\" in value:
            raise ValueError("Prefix cannot contain backslashes.")

        # Optional: Add a length limit if needed
        if len(value) > max_len:  # Arbitrary limit
            raise ValueError("Prefix is too long.")

        return value


class EndpointUrlForm(BaseCaseInsensitiveModel):
    """Represents a validEndpoint."""

    endpoint_url: str

    @classmethod
    @field_validator("endpoint_url")
    def validate_endpoint_url(cls, value: str) -> str:
        """Validate an endpoint URL. Allows None or a valid URL format."""
        if value is None:
            return None

        result = urlparse(value)
        if not all([result.scheme, result.netloc]):
            raise ValueError("Invalid URL format.")
        return value


class UploadPartSizeForm(BaseCaseInsensitiveModel):
    """Represents aws uploadPartSize."""

    upload_part_size: int

    @classmethod
    @field_validator("upload_part_size")
    def validate_upload_part_size(cls, value: int) -> int:
        """Validate the upload part size for S3 multipart uploads.

        Rules (based on AWS):
        - Minimum part size is 5 MB (5 * 1024 * 1024 bytes), except for the last part.
        - There's no fixed maximum part size, but it's often limited by memory and practical considerations.
        - For this validation, we'll enforce a reasonable maximum.
        """
        if value is None:
            return None

        min_part_size = 5 * 1024 * 1024  # 5 MB
        max_part_size = 5 * 1024 * 1024 * 1024  # 5 GB (arbitrary practical max)

        if not isinstance(value, int):
            raise TypeError("Upload part size must be an integer.")

        if value < min_part_size:
            raise ValueError(
                f"Upload part size must be at least {min_part_size} bytes (5 MB)."
            )

        if value > max_part_size:
            raise ValueError(
                f"Upload part size cannot exceed {max_part_size} bytes (5 GB)."
            )

        return value


class MaxUploadPartsForm(BaseCaseInsensitiveModel):
    """Represents aws MaxUploadPartsForm."""

    max_upload_parts: int

    @classmethod
    @field_validator("max_upload_parts")
    def validate_max_upload_parts(cls, value: int) -> int:
        """Validate the maximum number of parts for an S3 multipart upload.

        Rule (based on AWS):
        - Maximum number of parts is 10,000.
        """
        if value is None:
            return None

        max_parts = 10000

        if not isinstance(value, int):
            raise TypeError("Maximum upload parts must be an integer.")

        if value <= 0:
            raise TypeError("Maximum upload parts must be a positive integer.")

        if value > max_parts:
            raise ValueError(f"Maximum upload parts cannot exceed {max_parts}.")

        return value


class NumMaxRetriesForm(BaseCaseInsensitiveModel):
    """Represents aws NumMaxRetries."""

    num_max_retries: int = None

    @classmethod
    @field_validator("num_max_retries")
    def validate_num_max_retries(cls, value: int) -> int:
        """Validate the maximum number of retries.

        Should be a non-negative integer.
        """
        if value is None:
            return None

        if not isinstance(value, int):
            raise TypeError("Maximum retries must be an integer.")

        if value < 0:
            raise TypeError("Maximum retries cannot be negative.")

        return value


class MinRetryDelayForm(BaseCaseInsensitiveModel):
    """Represents aws MinRetryDelay."""

    min_retry_delay: int = None

    @classmethod
    @field_validator("min_retry_delay")
    def validate_min_retry_delay(cls, value: int) -> int:
        """Validate the minimum retry delay in seconds.

        Should be a non-negative integer.
        """
        if value is None:
            return None

        if not isinstance(value, int):
            raise TypeError("Minimum retry delay must be an integer.")

        if value < 0:
            raise TypeError("Minimum retry delay cannot be negative.")

        return value


class MaxRetryDelayForm(BaseCaseInsensitiveModel):
    """Represents aws MaxRetryDelay."""

    max_retry_delay: int

    @classmethod
    @field_validator("max_retry_delay")
    def validate_max_retry_delay(cls, value: int) -> int:
        """Validate the maximum retry delay in seconds.

        Should be a non-negative integer.
        """
        if value is None:
            return None

        if not isinstance(value, int):
            raise TypeError("Maximum retry delay must be an integer.")

        if value < 0:
            raise ValueError("Maximum retry delay cannot be negative.")

        return value


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

    debug = "D"
    info = "I"
    warn = "W"
    error = "E"


class BackupConfig(BaseCaseInsensitiveModel):
    """Represent the overall backup configuration.

    :param pitr_enabled: Enable or disable Oplog fetching.
    :type pitr_enabled: bool
    """

    pitr_enabled: bool
    provider: str = S3Provider
    region: str = S3RegionForm
    bucket: str = S3BucketForm
    prefix: str = S3PrefixForm
    endpoint_url: str = EndpointUrlForm
    upload_part_size: int = UploadPartSizeForm
    max_upload_parts: int = MaxUploadPartsForm
    num_max_retries: int = NumMaxRetriesForm
    max_retry_delay: int = MaxRetryDelayForm
    min_retry_delay: int = MinRetryDelayForm

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
