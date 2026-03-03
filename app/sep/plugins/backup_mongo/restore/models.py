# Copyright 2026 Percona LLC
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

from pydantic import AliasChoices, ConfigDict, Field

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import EmptyStrToNone, NonEmptyStr
from app.sep.plugins.backup_mongo.models import BackupType


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
