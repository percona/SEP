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

"""Define models for the Restore plugin."""

from datetime import datetime
from typing import Any, NamedTuple

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    FutureDatetime,
    model_validator,
)

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import EmptyStrToNone, NonEmptyStr
from app.sep.plugins.backup_mongo.models import BackupType
from app.tasks.models import (
    TaskBackendEnum,
    TaskHistoryStatusEnum,
    TaskOwner,
    TaskWrite,
)


class RestoreConfigRestore(BaseCaseInsensitiveModel):
    """Represent restore configuration options.

    This model uses camelCase serialization aliases to match PBM config format,
    but still accepts uppercase keys for case-insensitive input.

    :param batchSize: The number of documents to buffer.
    :type batchSize: int | None
    :param numInsertionWorkers: Specifies the number of insertion workers to run concurrently per collection.
    :type numInsertionWorkers: int | None
    :param numParallelCollections: The number of collections to process in parallel during a logical restore.
    :type numParallelCollections: int | None
    :param numDownloadWorkers: The number of workers that request data chunks from the storage during the restore.
    :type numDownloadWorkers: int | None
    :param maxDownloadBufferMb: The maximum size of the in-memory buffer that is used to download files from the S3 storage.
    :type maxDownloadBufferMb: int | None
    :param downloadChunkMb: The size of the data chunk in MB to download from the S3 storage.
    :type downloadChunkMb: int | None
    :param mongodLocation: The custom path to mongod binaries.
    :type mongodLocation: NonEmptyStr | EmptyStrToNone
    :param mongodLocationMap: The list of custom paths to mongod binaries on every node.
    :type mongodLocationMap: dict[str, str] | EmptyStrToNone
    """

    model_config = ConfigDict(alias_generator=None)

    batch_size: int | None = Field(
        default=500,
        validation_alias=AliasChoices("batchSize", "BATCHSIZE", "BATCH_SIZE"),
        serialization_alias="batchSize",
    )
    num_insertion_workers: int | None = Field(
        default=10,
        validation_alias=AliasChoices(
            "numInsertionWorkers", "NUMINSERTIONWORKERS", "NUM_INSERTION_WORKERS"
        ),
        serialization_alias="numInsertionWorkers",
    )
    num_parallel_collections: int | None = Field(
        None,
        validation_alias=AliasChoices(
            "numParallelCollections",
            "NUMPARALLELCOLLECTIONS",
            "NUM_PARALLEL_COLLECTIONS",
        ),
        serialization_alias="numParallelCollections",
    )
    num_download_workers: int | None = Field(
        None,
        validation_alias=AliasChoices(
            "numDownloadWorkers", "NUMDOWNLOADWORKERS", "NUM_DOWNLOAD_WORKERS"
        ),
        serialization_alias="numDownloadWorkers",
    )
    max_download_buffer_mb: int | None = Field(
        None,
        validation_alias=AliasChoices(
            "maxDownloadBufferMb", "MAXDOWNLOADBUFFERMB", "MAX_DOWNLOAD_BUFFER_MB"
        ),
        serialization_alias="maxDownloadBufferMb",
    )
    download_chunk_mb: int | None = Field(
        default=32,
        validation_alias=AliasChoices(
            "downloadChunkMb", "DOWNLOADCHUNKMB", "DOWNLOAD_CHUNK_MB"
        ),
        serialization_alias="downloadChunkMb",
    )
    mongod_location: NonEmptyStr | EmptyStrToNone = Field(
        None,
        validation_alias=AliasChoices(
            "mongodLocation", "MONGODLOCATION", "MONGOD_LOCATION"
        ),
        serialization_alias="mongodLocation",
    )
    mongod_location_map: dict[str, str] | EmptyStrToNone = Field(
        None,
        validation_alias=AliasChoices(
            "mongodLocationMap", "MONGODLOCATIONMAP", "MONGOD_LOCATION_MAP"
        ),
        serialization_alias="mongodLocationMap",
    )


class RestoreConfig(BaseCaseInsensitiveModel):
    """Define the complete configuration for a restore operation in PBM format.

    This model follows the PBM backup format with lowercase keys and camelCase values,
    similar to how PBM backup config is structured. Only contains PBM config sections.
    The backupSource and backupType are stored separately for restore operations.

    :param restore: Restore-specific configuration options (PBM config format).
    :type restore: RestoreConfigRestore | None
    :param backupSource: Source location of the backup (backup name or timestamp).
        This is not part of PBM config but needed for restore operations.
    :type backupSource: NonEmptyStr
    :param backupType: Type of backup to restore from.
        This is not part of PBM config but needed for restore operations.
    :type backupType: BackupType
    :param credentials_path: Path to MongoDB URI credentials file on the Nomad node
        (SEP-only, not part of PBM config; used by payloads).
    :type credentials_path: NonEmptyStr | EmptyStrToNone
    """

    model_config = ConfigDict(alias_generator=None)

    restore: RestoreConfigRestore | EmptyStrToNone = Field(
        None, validation_alias=AliasChoices("restore", "RESTORE")
    )
    backup_source: NonEmptyStr = Field(
        validation_alias=AliasChoices("backupSource", "BACKUP_SOURCE", "backup_source"),
        serialization_alias="backupSource",
    )
    backup_type: BackupType = Field(
        validation_alias=AliasChoices("backupType", "BACKUP_TYPE", "backup_type"),
        serialization_alias="backupType",
    )
    credentials_path: NonEmptyStr | EmptyStrToNone = Field(
        None,
        validation_alias=AliasChoices("credentials_path", "CREDENTIALS_PATH"),
    )


class RestoreCreate(BaseCaseInsensitiveModel):
    """Model for creating a restore task.

    :param hostname: The hostname of the machine to restore to.
    :type hostname: NonEmptyStr
    :param task_name: Name of the restore task.
    :type task_name: NonEmptyStr
    :param service_id: Service identifier for the restore task.
    :type service_id: NonEmptyStr | EmptyStrToNone = None
    :param backup_type: Type of backup to restore from.
    :type backup_type: BackupType
    :param backup_source: Source location of the backup (backup name or timestamp).
    :type backup_source: NonEmptyStr
    :param restore_batch_size: Number of documents to buffer.
    :type restore_batch_size: int | None
    :param restore_num_insertion_workers: Number of insertion workers to run concurrently per collection.
    :type restore_num_insertion_workers: int | None
    :param restore_num_parallel_collections: Number of collections to process in parallel during logical restore.
    :type restore_num_parallel_collections: int | None
    :param restore_num_download_workers: Number of workers that request data chunks from storage.
    :type restore_num_download_workers: int | None
    :param restore_max_download_buffer_mb: Maximum size of in-memory buffer for downloading files from S3.
    :type restore_max_download_buffer_mb: int | None
    :param restore_download_chunk_mb: Size of data chunk in MB to download from S3 storage.
    :type restore_download_chunk_mb: int | None
    :param restore_mongod_location: Custom path to mongod binaries.
    :type restore_mongod_location: NonEmptyStr | EmptyStrToNone
    :param restore_mongod_location_map: Custom paths to mongod binaries on every node (YAML string).
    :type restore_mongod_location_map: NonEmptyStr | EmptyStrToNone
    :param credentials_path: Optional path to MongoDB URI credentials file on the Nomad node.
    :type credentials_path: NonEmptyStr | EmptyStrToNone
    """

    hostname: NonEmptyStr
    task_name: NonEmptyStr
    service_id: NonEmptyStr | EmptyStrToNone = None
    backup_type: BackupType
    backup_source: NonEmptyStr
    restore_batch_size: int | EmptyStrToNone = None
    restore_num_insertion_workers: int | EmptyStrToNone = None
    restore_num_parallel_collections: int | EmptyStrToNone = None
    restore_num_download_workers: int | EmptyStrToNone = None
    restore_max_download_buffer_mb: int | EmptyStrToNone = None
    restore_download_chunk_mb: int | EmptyStrToNone = None
    restore_mongod_location: NonEmptyStr | EmptyStrToNone = None
    restore_mongod_location_map: NonEmptyStr | EmptyStrToNone = None
    credentials_path: NonEmptyStr | EmptyStrToNone = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_int_service_id(cls, data: Any) -> Any:
        """Coerce an int ``service_id`` (the JSON body shape) to str.

        The form path receives ``service_id`` as ``NonEmptyStr |
        EmptyStrToNone`` directly. The JSON path validates a
        :class:`RestoreTaskWrite` first, where ``service_id`` is
        ``int | None``, and then dumps it for re-validation here —
        without this coercion the ``int`` would fail the str-typed
        field. Form submissions arriving as strings are unaffected.

        :param data: The raw input passed to ``model_validate``.
        :type data: Any
        :return: The input with ``service_id`` stringified when it was
            an int, or ``data`` unchanged otherwise.
        :rtype: Any
        """
        if isinstance(data, dict):
            sid = data.get("service_id")
            if isinstance(sid, int):
                return {**data, "service_id": str(sid)}
        return data


class RestoreTaskWrite(BaseModel):
    """Represent a JSON request body for creating a restore task group.

    Mirrors :class:`RestoreCreate`. POST always creates a parent config task plus
    restore, pbm-list, and optional force-resync children.

    :param task_name: The name of the task to be created.
    :type task_name: NonEmptyStr
    :param hostname: The target hostname for the task execution.
    :type hostname: NonEmptyStr
    :param service_id: Optional Inventory ID of the MongoDB service.
    :type service_id: int | None
    :param backup_type: Type of backup to restore from (logical or physical).
    :type backup_type: BackupType
    :param backup_source: Backup name or timestamp to restore from.
    :type backup_source: NonEmptyStr
    :param restore_batch_size: Number of documents to buffer.
    :type restore_batch_size: int | None
    :param restore_num_insertion_workers: Insertion workers per collection.
    :type restore_num_insertion_workers: int | None
    :param restore_num_parallel_collections: Parallel collections for logical restore.
    :type restore_num_parallel_collections: int | None
    :param restore_num_download_workers: Download workers for physical restore.
    :type restore_num_download_workers: int | None
    :param restore_max_download_buffer_mb: Max S3 download buffer in MB.
    :type restore_max_download_buffer_mb: int | None
    :param restore_download_chunk_mb: S3 download chunk size in MB.
    :type restore_download_chunk_mb: int | None
    :param restore_mongod_location: Custom path to mongod binaries.
    :type restore_mongod_location: str | None
    :param restore_mongod_location_map: Per-node mongod paths as YAML.
    :type restore_mongod_location_map: str | None
    :param credentials_path: Path to MongoDB URI credentials on the Nomad node.
    :type credentials_path: str | None
    """

    task_name: NonEmptyStr
    hostname: NonEmptyStr
    service_id: int | None = None
    backup_type: BackupType
    backup_source: NonEmptyStr
    restore_batch_size: int | None = None
    restore_num_insertion_workers: int | None = None
    restore_num_parallel_collections: int | None = None
    restore_num_download_workers: int | None = None
    restore_max_download_buffer_mb: int | None = None
    restore_download_chunk_mb: int | None = None
    restore_mongod_location: str | None = None
    restore_mongod_location_map: str | None = None
    credentials_path: str | None = None


class RestoreTaskLegModel(BaseModel):
    """Represent an internal descriptor for one restore task leg.

    :param name: The task name for this leg.
    :type name: NonEmptyStr
    :param payload_name: The payload file name consumed by ``run-python``.
    :type payload_name: NonEmptyStr
    :param target: The target host where this task executes.
    :type target: NonEmptyStr
    :param config_yaml: YAML config content passed in task metadata.
    :type config_yaml: str
    :param requirements: Newline-separated Python requirements for this leg.
    :type requirements: str
    :param parent: Optional parent task name for child legs.
    :type parent: NonEmptyStr | None
    :param service_name: Optional PMM service name annotation.
    :type service_name: NonEmptyStr | None
    """

    name: NonEmptyStr
    payload_name: NonEmptyStr
    target: NonEmptyStr
    config_yaml: str
    requirements: str = ""
    parent: NonEmptyStr | None = None
    service_name: NonEmptyStr | None = None


class RestoreConfigPayloadModel(BaseModel):
    """Represent typed inputs for the restore-config leg payload.

    :param task_name: The parent restore task name.
    :type task_name: NonEmptyStr
    :param hostname: The target hostname for execution.
    :type hostname: NonEmptyStr
    :param backup_source: Backup name or timestamp to restore from.
    :type backup_source: NonEmptyStr
    :param backup_type: Backup type for restore execution.
    :type backup_type: BackupType
    :param restore: Optional restore-specific PBM options.
    :type restore: RestoreConfigRestore | None
    :param credentials_path: Optional path to MongoDB URI credentials.
    :type credentials_path: NonEmptyStr | EmptyStrToNone
    :param service_name: Optional PMM service name annotation.
    :type service_name: NonEmptyStr | None
    """

    task_name: NonEmptyStr
    hostname: NonEmptyStr
    backup_source: NonEmptyStr
    backup_type: BackupType
    restore: RestoreConfigRestore | None = None
    credentials_path: NonEmptyStr | EmptyStrToNone = None
    service_name: NonEmptyStr | None = None


class RestoreLegPayloadModel(BaseModel):
    """Represent typed inputs for the restore execution leg payload.

    :param task_name: The parent restore task name.
    :type task_name: NonEmptyStr
    :param hostname: The target hostname for execution.
    :type hostname: NonEmptyStr
    :param backup_source: Backup name or timestamp to restore from.
    :type backup_source: NonEmptyStr
    :param backup_type: Backup type for restore execution.
    :type backup_type: BackupType
    :param credentials_path: Optional path to MongoDB URI credentials.
    :type credentials_path: NonEmptyStr | EmptyStrToNone
    :param service_name: Optional PMM service name annotation.
    :type service_name: NonEmptyStr | None
    """

    task_name: NonEmptyStr
    hostname: NonEmptyStr
    backup_source: NonEmptyStr
    backup_type: BackupType
    credentials_path: NonEmptyStr | EmptyStrToNone = None
    service_name: NonEmptyStr | None = None


class PbmListPayloadModel(BaseModel):
    """Represent typed inputs for the pbm-list helper leg payload.

    :param task_name: The parent restore task name.
    :type task_name: NonEmptyStr
    :param hostname: The target hostname for execution.
    :type hostname: NonEmptyStr
    :param credentials_path: Optional path to MongoDB URI credentials.
    :type credentials_path: NonEmptyStr | EmptyStrToNone
    :param service_name: Optional PMM service name annotation.
    :type service_name: NonEmptyStr | None
    """

    task_name: NonEmptyStr
    hostname: NonEmptyStr
    credentials_path: NonEmptyStr | EmptyStrToNone = None
    service_name: NonEmptyStr | None = None


class PbmForceResyncPayloadModel(BaseModel):
    """Represent typed inputs for the pbm-force-resync helper leg payload.

    :param task_name: The parent restore task name.
    :type task_name: NonEmptyStr
    :param hostname: The target hostname for execution.
    :type hostname: NonEmptyStr
    :param credentials_path: Optional path to MongoDB URI credentials.
    :type credentials_path: NonEmptyStr | EmptyStrToNone
    :param service_name: Optional PMM service name annotation.
    :type service_name: NonEmptyStr | None
    """

    task_name: NonEmptyStr
    hostname: NonEmptyStr
    credentials_path: NonEmptyStr | EmptyStrToNone = None
    service_name: NonEmptyStr | None = None


class RestoreTaskGroupPayloads(NamedTuple):
    """Represent TaskWrite payloads for all restore task legs.

    :param config_task: Parent restore-config task payload.
    :type config_task: TaskWrite
    :param restore_task: Restore execution task payload.
    :type restore_task: TaskWrite
    :param pbm_list_task: pbm-list helper task payload.
    :type pbm_list_task: TaskWrite
    :param force_resync_task: Optional pbm-force-resync task payload.
    :type force_resync_task: TaskWrite | None
    """

    config_task: TaskWrite
    restore_task: TaskWrite
    pbm_list_task: TaskWrite
    force_resync_task: TaskWrite | None


class RestoreDerivedTaskSummary(BaseModel):
    """Represent one child task in a restore task group detail response.

    :param name: The name of the child task.
    :type name: str
    :param status: The latest execution status of the child task.
    :type status: TaskHistoryStatusEnum | None
    """

    name: str
    status: TaskHistoryStatusEnum | None = None


class RestoreTaskBase(BaseModel):
    """Define the common fields shared across restore task API responses.

    :param name: The name of the restore task.
    :type name: str
    :param owner: The entity or user that owns the task.
    :type owner: TaskOwner
    :param hostname: The target hostname for the task execution.
    :type hostname: str | None
    :param status: The current execution status of the task.
    :type status: TaskHistoryStatusEnum | None
    :param backup_type: The PBM backup type for this restore.
    :type backup_type: str
    :param backup_source: The backup name or timestamp to restore from.
    :type backup_source: str
    """

    name: str
    owner: TaskOwner
    hostname: str | None = None
    status: TaskHistoryStatusEnum | None = None
    backup_type: str
    backup_source: str


class RestoreTaskResponse(RestoreTaskBase):
    """Represent a restore task API response.

    :param id: The unique identifier for the restore task.
    :type id: int | None
    :param backend: The backend worker/engine executing the task.
    :type backend: TaskBackendEnum
    :param data: The raw configuration and parameters for the restore execution.
    :type data: dict[str, Any]
    :param protected: Whether the task is protected from deletion or modification.
    :type protected: bool
    :param alert_on_fail: If True, notifications are sent upon task failure.
    :type alert_on_fail: bool
    :param created_at: The timestamp when the task was first created.
    :type created_at: datetime | None
    :param updated_at: The timestamp of the last modification to the task.
    :type updated_at: datetime | None
    :param created_by: The user who initiated the task.
    :type created_by: str | None
    :param last_updated_by: The user who last modified the task record.
    :type last_updated_by: str | None
    """

    id: int | None = None
    backend: TaskBackendEnum
    data: dict[str, Any]
    protected: bool
    alert_on_fail: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: str | None = None
    last_updated_by: str | None = None


class RestoreTaskDetailResponse(RestoreTaskResponse):
    """Represent a restore task detail API response.

    :param derived_tasks: Latest status for each restore child task.
    :type derived_tasks: list[RestoreDerivedTaskSummary]
    """

    derived_tasks: list[RestoreDerivedTaskSummary] = Field(default_factory=list)


class RestoreExecuteWrite(BaseModel):
    """Represent a JSON request body for executing a restore task.

    :param eta: Optional future datetime to schedule execution.
    :type eta: FutureDatetime | None
    :param chain_task_names: Optional list of task names to chain after this one.
    :type chain_task_names: list[str] | None
    :param chain_on_failure: Whether to run chained tasks even on failure.
    :type chain_on_failure: bool | None
    """

    eta: FutureDatetime | None = None
    chain_task_names: list[str] | None = None
    chain_on_failure: bool | None = None


class RestoreExecutionResponse(BaseModel):
    """Represent the response from POST .../restores/{task_name}/execute.

    :param task_name: The name of the task that was executed.
    :type task_name: str
    :param task_id: The id of the task-history row created by the tasks API.
    :type task_id: int | None
    """

    task_name: str
    task_id: int | None = None
