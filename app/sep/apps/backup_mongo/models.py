# Copyright (C) 2026 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Define models for the Backups plugin."""

from enum import StrEnum
from typing import Annotated

import yaml
from pydantic import AfterValidator, AliasChoices, BaseModel, ConfigDict, Field

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import EmptyStrToNone, EnumFieldMixin, NonEmptyStr
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework import BaseTaskResponse
from app.sep.apps.framework.form_dsl import (
    Choices,
    FieldWidget,
    Forbidden,
    HostRef,
    ServiceRef,
    TaskFormModel,
    Ui,
)
from app.sep.apps.framework.rules import F
from app.sep.apps.labels import EXECUTION_HOST_LABEL
from app.tasks.models import TaskHistoryStatusEnum

OWNER = "BACKUP_MONGO"


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


def parse_backup_priority(priority_str: str) -> dict[str, float]:
    """Parse the Node Priority YAML into a node -> priority mapping.

    Shared by the request-model validator (create-time) and the spec builder so the
    parse rules cannot drift and a present priority is never silently dropped.

    :param priority_str: Raw YAML from the Node Priority field.
    :return: Mapping of node address to numeric priority.
    :raises ValueError: On invalid YAML, a non-mapping result, an empty mapping,
        or a non-numeric priority value.
    """
    try:
        parsed = yaml.safe_load(priority_str)
    except yaml.YAMLError as exc:
        raise ValueError(f"Node priority is not valid YAML: {exc}") from exc
    if not isinstance(parsed, dict):
        # Raise ValueError, not TypeError, so Pydantic surfaces a 422 instead of a 500.
        raise ValueError(  # noqa: TRY004
            "Node priority must be a YAML mapping of node address to priority number"
        )
    if not parsed:
        # A present-but-empty mapping would be dropped as falsy in the spec builder;
        # reject it so a present field always takes effect.
        raise ValueError("Node priority mapping is empty; provide at least one node")
    result = {}
    for node, value in parsed.items():
        # Reject booleans explicitly — they would otherwise coerce to 1.0 / 0.0.
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(  # noqa: TRY004
                f"Priority for {node!r} must be a number, got {value!r}"
            )
        result[str(node)] = float(value)
    return result


def _validate_priority_yaml(value: str) -> str:
    """Validate the Node Priority YAML, returning the raw string unchanged.

    :param value: The raw Node Priority YAML string.
    :return: The same string, once it is confirmed to be a valid priority mapping.
    :raises ValueError: If the YAML is not a valid node -> number mapping.
    """
    parse_backup_priority(value)
    return value


# A non-empty Node Priority YAML string, validated as a node -> number mapping.
BackupPriorityYaml = Annotated[NonEmptyStr, AfterValidator(_validate_priority_yaml)]


class BackupConfigPITR(BaseCaseInsensitiveModel):
    """Represent Point In Time Recovery configuration.

    :param enabled: PITR enabled.
    :type enabled: bool
    :param oplogSpanMin: The PBM ...
    :type oplogSpanMin: int
    :param compression: Compression ... PBM.
    :type compression: NonEmptyStr
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
        NonEmptyStr, Field(validation_alias=AliasChoices("compression", "COMPRESSION"))
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

    path: NonEmptyStr | EmptyStrToNone = Field(
        None, validation_alias=AliasChoices("path", "PATH")
    )


class BackupConfigStorageS3(BaseCaseInsensitiveModel):
    """Represents an S3 storage configuration."""

    model_config = ConfigDict(alias_generator=None)

    region: NonEmptyStr | EmptyStrToNone = Field(
        None, validation_alias=AliasChoices("region", "REGION")
    )
    bucket: NonEmptyStr | EmptyStrToNone = Field(
        None, validation_alias=AliasChoices("bucket", "BUCKET")
    )
    prefix: NonEmptyStr | EmptyStrToNone = Field(
        None, validation_alias=AliasChoices("prefix", "PREFIX")
    )
    endpoint_url: NonEmptyStr | EmptyStrToNone = Field(
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
    :type pbm_config_yaml_payload: NonEmptyStr | EmptyStrToNone
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
    pbm_config_yaml_payload: NonEmptyStr | EmptyStrToNone = Field(
        None,
        validation_alias=AliasChoices(
            "pbm_config_yaml_payload", "PBM_CONFIG_YAML_PAYLOAD"
        ),
        serialization_alias="pbm_config_yaml_payload",
    )
    credentials_path: NonEmptyStr | EmptyStrToNone = Field(
        None,
        validation_alias=AliasChoices("credentials_path", "CREDENTIALS_PATH"),
    )


class BackupCreate(BaseCaseInsensitiveModel):
    """Represent a Backup creation form with proper case-insensitive fields.

    :param task_name: The PBM yaml payload to parse from CLI.
    :type task_name: NonEmptyStr
    :param hostname: The PBM yaml payload to parse from CLI.
    :type hostname: NonEmptyStr
    :param service_id: Service for executing PBM.
    :type service_id: int
    :param backup_type: Type of backup activity on PBM.
    :type backup_type: BackupType
    :param alert_on_fail: If True, send an alert if the task fails. Defaults to False.
    :type alert_on_fail: bool
    """

    task_name: NonEmptyStr
    hostname: NonEmptyStr
    service_id: int
    backup_type: BackupType
    alert_on_fail: bool = False
    pitr_oplog_span_min: int | EmptyStrToNone = None
    pitr_enabled: bool = False
    pitr_compression: NonEmptyStr | EmptyStrToNone = None
    storage_type: NonEmptyStr | EmptyStrToNone = None
    storage_s3_region: NonEmptyStr | EmptyStrToNone = None
    storage_s3_bucket: NonEmptyStr | EmptyStrToNone = None
    storage_s3_prefix: NonEmptyStr | EmptyStrToNone = None
    storage_s3_endpoint_url: NonEmptyStr | EmptyStrToNone = None
    storage_filesystem_path: NonEmptyStr | EmptyStrToNone = None
    # Backup options
    backup_priority: BackupPriorityYaml | EmptyStrToNone = None
    backup_compression: CompressionAlgorithm | EmptyStrToNone = None
    backup_compression_level: int | EmptyStrToNone = None
    backup_timeouts_starting_status: int | EmptyStrToNone = None
    backup_oplog_span_min: float | EmptyStrToNone = None
    backup_num_parallel_collections: int | EmptyStrToNone = None
    # Path to MongoDB URI credentials file on the Nomad node (passed as task meta, used by payloads).
    credentials_path: NonEmptyStr | EmptyStrToNone = None


_NOT_S3_STORAGE = Forbidden(when=F("storage_type") != StorageType.S3.value)
_NOT_FILESYSTEM_STORAGE = Forbidden(
    when=F("storage_type") != StorageType.FILESYSTEM.value
)
_COMPRESSION_CHOICES = Choices(
    tuple((algorithm.value, algorithm.value) for algorithm in CompressionAlgorithm)
)


class BackupForm(TaskFormModel):
    """Define the model-first schema source for the MongoDB Backups ``GET /schema``.

    The single source the derived ``GET /schema`` form renders from, driven by the
    :class:`Ui` / reference / :class:`Choices` / :class:`Forbidden` markers. It is
    *not* the JSON request body — :class:`BackupTaskWrite` is — and is never validated
    as one; field-declaration order reproduces the schema's section and field order
    (Task, Storage, Point-in-Time Recovery, Backup Options). ``task_name`` and
    ``hostname`` are redeclared here (still ``NonEmptyStr``) so the form can carry a
    presentation default for the task name, cascade the executor host from
    ``service_id``, and order the Task section as service → host. The
    ``alert_on_fail`` capability control stays inherited from
    :class:`TaskFormModel` (``Hidden``, off-schema). The deriver emits no
    min-length constraint, and this form is never validated as a request body.
    """

    task_name: Annotated[
        NonEmptyStr,
        Ui(section="Task", order=0, default="mongodb-backup"),
    ]
    service_id: Annotated[
        int,
        ServiceRef(service_types=(ServiceTypeEnum.MONGODB,)),
        Ui(label="Database Service", section="Task", order=1),
    ]
    hostname: Annotated[
        NonEmptyStr,
        HostRef(),
        Ui(
            label=EXECUTION_HOST_LABEL,
            section="Task",
            depends_on="service_id",
            order=2,
        ),
    ]
    credentials_path: Annotated[
        str | None,
        Ui(
            section="Task",
            order=3,
            description="Optional path to MongoDB URI credentials on the Nomad node",
        ),
    ] = None
    storage_type: Annotated[
        str,
        Choices((("s3", "S3-compatible"), ("filesystem", "Filesystem"))),
        Ui(section="Storage"),
    ] = StorageType.S3.value
    storage_s3_region: Annotated[
        str | None, _NOT_S3_STORAGE, Ui(label="S3 Region", section="Storage")
    ] = None
    storage_s3_bucket: Annotated[
        str | None, _NOT_S3_STORAGE, Ui(label="S3 Bucket", section="Storage")
    ] = None
    storage_s3_prefix: Annotated[
        str | None, _NOT_S3_STORAGE, Ui(label="S3 Prefix", section="Storage")
    ] = None
    storage_s3_endpoint_url: Annotated[
        str | None, _NOT_S3_STORAGE, Ui(label="S3 Endpoint URL", section="Storage")
    ] = None
    storage_filesystem_path: Annotated[
        str, _NOT_FILESYSTEM_STORAGE, Ui(label="Filesystem Path", section="Storage")
    ]
    pitr_enabled: Annotated[bool, Ui(label="Enable PITR", section="PITR")] = False
    pitr_oplog_span_min: Annotated[
        int | None, Ui(label="Oplog Span (minutes)", section="PITR")
    ] = None
    pitr_compression: Annotated[
        str, _COMPRESSION_CHOICES, Ui(label="PITR Compression", section="PITR")
    ] = CompressionAlgorithm.GZIP.value
    backup_priority: Annotated[
        str | None,
        Ui(
            label="Node Priority (YAML)",
            section="BackupOptions",
            widget=FieldWidget.TEXTAREA,
            description=(
                "YAML mapping of mongod addresses to backup priority (highest wins). "
                "One entry per line, e.g.:\n"
                '"host1:27018": 2\n'
                '"host2:27018": 1'
            ),
        ),
    ] = None
    backup_compression: Annotated[
        str,
        _COMPRESSION_CHOICES,
        Ui(
            section="BackupOptions",
            description="Compression method for backup snapshots. Default: s2",
        ),
    ] = CompressionAlgorithm.S2.value
    backup_compression_level: Annotated[
        int | None, Ui(label="Compression Level", section="BackupOptions")
    ] = None
    backup_timeouts_starting_status: Annotated[
        int | None,
        Ui(label="Starting Status Timeout (seconds)", section="BackupOptions"),
    ] = None
    backup_oplog_span_min: Annotated[
        float | None, Ui(label="Backup Oplog Span (minutes)", section="BackupOptions")
    ] = None
    backup_num_parallel_collections: Annotated[
        int | None, Ui(label="Parallel Collections", section="BackupOptions")
    ] = None


class BackupTaskWrite(BaseModel):
    """Represent a JSON request body for creating a backup task group.

    Mirrors :class:`BackupCreate` except ``backup_type``, which is always
    ``pbm_config`` on create. POST creates the parent config task plus derived
    logical, physical, and status siblings.

    :param task_name: The name of the task to be created.
    :type task_name: NonEmptyStr
    :param hostname: The target hostname for the task execution.
    :type hostname: NonEmptyStr
    :param service_id: The Inventory ID of the MongoDB service to connect to.
    :type service_id: int
    :param alert_on_fail: If True, send an alert if the task fails.
    :type alert_on_fail: bool
    :param pitr_oplog_span_min: PITR oplog span in minutes.
    :type pitr_oplog_span_min: int | None
    :param pitr_enabled: Whether PITR is enabled.
    :type pitr_enabled: bool
    :param pitr_compression: PITR compression algorithm.
    :type pitr_compression: str | None
    :param storage_type: Storage backend type (``s3`` or ``filesystem``).
    :type storage_type: str | None
    :param storage_s3_region: S3 region when ``storage_type`` is ``s3``.
    :type storage_s3_region: str | None
    :param storage_s3_bucket: S3 bucket when ``storage_type`` is ``s3``.
    :type storage_s3_bucket: str | None
    :param storage_s3_prefix: S3 key prefix when ``storage_type`` is ``s3``.
    :type storage_s3_prefix: str | None
    :param storage_s3_endpoint_url: S3 endpoint URL when ``storage_type`` is ``s3``.
    :type storage_s3_endpoint_url: str | None
    :param storage_filesystem_path: Filesystem path when ``storage_type`` is
        ``filesystem``.
    :type storage_filesystem_path: str | None
    :param backup_priority: Node priority mapping as YAML.
    :type backup_priority: str | None
    :param backup_compression: Backup snapshot compression algorithm.
    :type backup_compression: CompressionAlgorithm | None
    :param backup_compression_level: Backup compression level.
    :type backup_compression_level: int | None
    :param backup_timeouts_starting_status: PBM starting-status timeout in seconds.
    :type backup_timeouts_starting_status: int | None
    :param backup_oplog_span_min: Logical backup oplog span in minutes.
    :type backup_oplog_span_min: float | None
    :param backup_num_parallel_collections: Parallel collections for logical backup.
    :type backup_num_parallel_collections: int | None
    :param credentials_path: Path to MongoDB URI credentials on the Nomad node.
    :type credentials_path: str | None
    """

    task_name: NonEmptyStr
    hostname: NonEmptyStr
    service_id: int
    alert_on_fail: bool = False
    pitr_oplog_span_min: int | None = None
    pitr_enabled: bool = False
    pitr_compression: str | None = None
    storage_type: str | None = None
    storage_s3_region: str | None = None
    storage_s3_bucket: str | None = None
    storage_s3_prefix: str | None = None
    storage_s3_endpoint_url: str | None = None
    storage_filesystem_path: str | None = None
    backup_priority: BackupPriorityYaml | EmptyStrToNone = None
    backup_compression: CompressionAlgorithm | None = None
    backup_compression_level: int | None = None
    backup_timeouts_starting_status: int | None = None
    backup_oplog_span_min: float | None = None
    backup_num_parallel_collections: int | None = None
    credentials_path: str | None = None


class BackupDerivedTaskSummary(BaseModel):
    """Represent one derived sibling in a backup task detail response.

    :param name: The name of the derived task.
    :type name: str
    :param backup_type: The PBM backup type for this derived task.
    :type backup_type: str
    :param status: The latest execution status of the derived task.
    :type status: TaskHistoryStatusEnum | None
    """

    name: str
    backup_type: str
    status: TaskHistoryStatusEnum | None = None


class BackupTaskBase(BaseTaskResponse):
    """Carry the backup_mongo-specific fields shared across its responses.

    :param hostname: The target hostname for the task execution.
    """

    hostname: str | None = None


class BackupTaskResponse(BackupTaskBase):
    """Represent a backup task API response.

    :param backup_type: The PBM backup type stored on the task.
    """

    backup_type: str


class BackupTaskDetailResponse(BackupTaskResponse):
    """Represent a backup task detail API response.

    :param derived_tasks: Latest status for each derived logical, physical, and
        status sibling.
    :type derived_tasks: list[BackupDerivedTaskSummary]
    :param latest_pbm_status: Tail of the latest PBM status task stdout, if
        available.
    :type latest_pbm_status: str | None
    """

    derived_tasks: list[BackupDerivedTaskSummary] = Field(default_factory=list)
    latest_pbm_status: str | None = None
