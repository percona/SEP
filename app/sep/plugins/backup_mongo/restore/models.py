"""Define models for the Restore plugin."""

from pydantic import AliasChoices, ConfigDict, Field

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import EmptyStrToNone, RequiredStr
from app.sep.plugins.backup_mongo.models import BackupType


class RestoreConfigRestore(BaseCaseInsensitiveModel):
    """Represent restore configuration options.

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
    :type mongodLocation: RequiredStr | EmptyStrToNone
    :param mongodLocationMap: The list of custom paths to mongod binaries on every node.
    :type mongodLocationMap: dict[str, str] | EmptyStrToNone
    """

    model_config = ConfigDict(alias_generator=None)

    batch_size: int | None = Field(
        default=500,
        validation_alias=AliasChoices("batchSize", "BATCHSIZE"),
        serialization_alias="batchSize",
    )
    num_insertion_workers: int | None = Field(
        default=10,
        validation_alias=AliasChoices("numInsertionWorkers", "NUMINSERTIONWORKERS"),
        serialization_alias="numInsertionWorkers",
    )
    num_parallel_collections: int | None = Field(
        None,
        validation_alias=AliasChoices(
            "numParallelCollections", "NUMPARALLELCOLLECTIONS"
        ),
        serialization_alias="numParallelCollections",
    )
    num_download_workers: int | None = Field(
        None,
        validation_alias=AliasChoices("numDownloadWorkers", "NUMDOWNLOADWORKERS"),
        serialization_alias="numDownloadWorkers",
    )
    max_download_buffer_mb: int | None = Field(
        None,
        validation_alias=AliasChoices("maxDownloadBufferMb", "MAXDOWNLOADBUFFERMB"),
        serialization_alias="maxDownloadBufferMb",
    )
    download_chunk_mb: int | None = Field(
        default=32,
        validation_alias=AliasChoices("downloadChunkMb", "DOWNLOADCHUNKMB"),
        serialization_alias="downloadChunkMb",
    )
    mongod_location: RequiredStr | EmptyStrToNone = Field(
        None,
        validation_alias=AliasChoices("mongodLocation", "MONGODLOCATION"),
        serialization_alias="mongodLocation",
    )
    mongod_location_map: dict[str, str] | EmptyStrToNone = Field(
        None,
        validation_alias=AliasChoices("mongodLocationMap", "MONGODLOCATIONMAP"),
        serialization_alias="mongodLocationMap",
    )


class RestoreConfigAll(BaseCaseInsensitiveModel):
    """Global config values for restore operations.

    This model contains settings that apply to all servers in a restore operation,
    including logging and SSH options.

    :param logging_dir: Directory path for storing restore operation logs.
    :type logging_dir: RequiredStr | EmptyStrToNone
    :param ssh_user: SSH username for remote operations (default: "percona").
    :type ssh_user: RequiredStr | EmptyStrToNone
    :param ssh_port: SSH port for remote operations (default: 22).
    :type ssh_port: int | EmptyStrToNone
    :param ssh_key: SSH key name for authentication (not full path).
    :type ssh_key: RequiredStr | EmptyStrToNone
    """

    logging_dir: RequiredStr | EmptyStrToNone = None

    # SSH Options
    ssh_user: RequiredStr | EmptyStrToNone = Field(default="percona")
    ssh_port: int | EmptyStrToNone = Field(default=22)
    ssh_key: RequiredStr | EmptyStrToNone = None  # only key name, not full path


class BaseRestoreConfigServer(BaseCaseInsensitiveModel):
    """Restore job configuration for a specific PBM restore job.

    This model contains server-specific settings for a restore operation, including
    backup source, destination, and restore options.

    :param backup_type: Type of backup to restore from.
    :type backup_type: BackupType
    :param backup_source: Source location of the backup (backup name or timestamp).
    :type backup_source: RequiredStr
    :param pre_script: Script to execute before restore.
    :type pre_script: RequiredStr | EmptyStrToNone
    :param post_script: Script to execute after restore.
    :type post_script: RequiredStr | EmptyStrToNone
    """

    backup_type: BackupType
    backup_source: RequiredStr
    pre_script: RequiredStr | EmptyStrToNone = None
    post_script: RequiredStr | EmptyStrToNone = None


class RestoreConfigServer(BaseRestoreConfigServer):
    """Server-specific restore configuration.

    Extends BaseRestoreConfigServer with additional required fields for alias, destination host, and port.

    :param alias: Unique identifier for the restore job.
    :type alias: RequiredStr
    :param dest_host: Destination host for the restore.
    :type dest_host: RequiredStr | EmptyStrToNone
    :param dest_port: Destination port for the restore.
    :type dest_port: int
    """

    alias: RequiredStr
    dest_host: RequiredStr | EmptyStrToNone = None
    dest_port: int | EmptyStrToNone = None


class RestoreConfig(BaseCaseInsensitiveModel):
    """Define the complete configuration for a restore operation.

    This model combines global settings applicable to all servers with a list of
    server-specific configurations and restore options for a complete restore operation setup.

    :param all_servers: Global configuration settings for all servers.
    :type all_servers: RestoreConfigAll
    :param restore: Restore-specific configuration options.
    :type restore: RestoreConfigRestore | None
    :param server_list: List of server-specific restore configurations.
    :type server_list: list[RestoreConfigServer]
    """

    all_servers: RestoreConfigAll
    restore: RestoreConfigRestore | None = None
    server_list: list[RestoreConfigServer]


class RestoreCreate(RestoreConfigAll, BaseRestoreConfigServer):
    """Model for creating a restore task.

    Inherits from RestoreConfigAll and BaseRestoreConfigServer, adding task and service identifiers.

    :param hostname: The hostname of the machine to restore to.
    :type hostname: RequiredStr
    :param task_name: Name of the restore task.
    :type task_name: RequiredStr
    :param service_id: Service identifier for the restore task.
    :type service_id: RequiredStr | EmptyStrToNone = None
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
    :type restore_mongod_location: RequiredStr | EmptyStrToNone
    :param restore_mongod_location_map: Custom paths to mongod binaries on every node (YAML string).
    :type restore_mongod_location_map: RequiredStr | EmptyStrToNone
    """

    hostname: RequiredStr
    task_name: RequiredStr
    service_id: RequiredStr | EmptyStrToNone = None

    # Restore options
    restore_batch_size: int | None = None
    restore_num_insertion_workers: int | None = None
    restore_num_parallel_collections: int | None = None
    restore_num_download_workers: int | None = None
    restore_max_download_buffer_mb: int | None = None
    restore_download_chunk_mb: int | None = None
    restore_mongod_location: RequiredStr | EmptyStrToNone = None
    restore_mongod_location_map: RequiredStr | EmptyStrToNone = None
