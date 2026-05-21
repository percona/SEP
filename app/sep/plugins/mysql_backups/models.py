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

from datetime import datetime
from enum import auto, IntEnum, StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, field_validator, FutureDatetime, model_validator

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import EmptyStrToNone, EnumFieldMixin, NonEmptyStr
from app.sep.plugins.framework.rules import (
    apply_conditional_rules,
    ConditionalRulesModel,
)
from app.sep.plugins.mysql_backups.schema import mysql_backups_schema
from app.tasks.models import TaskBackendEnum, TaskHistoryStatusEnum, TaskOwner


class SwapDropEnum(IntEnum):
    """Enum for defining types of swap actions for table data handling."""

    PURGE_ONLY = 0
    SWAP_DROP = 1
    SWAP_ARCHIVE_DROP = 2


class BackupType(EnumFieldMixin, StrEnum):
    """Backup types."""

    MYDUMPER = "M"
    XTRABACKUP = "X"
    BINLOG = "B"


class CompressionAlgorithm(EnumFieldMixin, StrEnum):
    """Enumeration for Compression Algorithms."""

    ZSTD = "zstd"
    LZ4 = "lz4"
    GZIP = "gzip"
    QUICKLZ = "quicklz"


ALLOWED_COMPRESSIONS = {
    BackupType.MYDUMPER: [CompressionAlgorithm.GZIP, CompressionAlgorithm.ZSTD],
    BackupType.XTRABACKUP: [
        CompressionAlgorithm.ZSTD,
        CompressionAlgorithm.LZ4,
        CompressionAlgorithm.QUICKLZ,
    ],
    BackupType.BINLOG: [CompressionAlgorithm.GZIP],
}


class UploadProvider(EnumFieldMixin, StrEnum):
    """Upload providers."""

    RSYNC = auto()
    S3 = auto()
    GSUTIL = auto()


class DirEncryptConfig(BaseModel):
    """Represent the encryption configuration for the backup task.

    :param encryption_recipient: The recipient of the encryption key.
    :type encryption_recipient: NonEmptyStr | None
    """

    encryption_recipient: NonEmptyStr | None = Field(
        None, serialization_alias="encryption recipient"
    )


class BackupConfigAll(BaseCaseInsensitiveModel):
    """Represent the general configuration for the backup task."""

    hardlink: bool = False
    compress: bool = False
    check_disk_space: bool = False
    encrypt: bool = False
    encrypt_using_tmpdir: bool = False
    post_run_encrypt: bool = False
    only_if_running_replica: bool = False
    only_if_read_only: bool = False
    logging_dir: NonEmptyStr | EmptyStrToNone = None
    backup_dir: NonEmptyStr | EmptyStrToNone = None
    defaults_file: NonEmptyStr | EmptyStrToNone = None
    compression_algorithm: CompressionAlgorithm | EmptyStrToNone = None
    mydumper_daily_purge: int | EmptyStrToNone = None
    mydumper_weekly_purge: int | EmptyStrToNone = None
    mydumper_dump_triggers: bool = False
    mydumper_desync_pxc: bool = False
    mydumper_use_numa: bool = False
    mydumper_extra_args: str | EmptyStrToNone = None
    use_ftwrl_guardian: bool = False
    xtrabackup_copies: int | EmptyStrToNone = None
    xtrabackup_kill_queries: bool = False
    xtrabackup_kill_queries_timeout: int | EmptyStrToNone = None
    xtrabackup_kill_query_type: Literal["select", "all"] | EmptyStrToNone = None
    xtrabackup_verify: bool = False
    xtrabackup_prepare: bool = False
    xtrabackup_prepare_memory: NonEmptyStr | EmptyStrToNone = None
    xtrabackup_desync_pxc: bool = False
    xtrabackup_rsync: bool = False
    xtrabackup_replica_info: bool = False
    xtrabackup_defaults_file: NonEmptyStr | EmptyStrToNone = None
    xtrabackup_extra_args: NonEmptyStr | EmptyStrToNone = None
    xtrabackup_incremental_method: (
        Literal["less_space", "fast_restore"] | EmptyStrToNone
    ) = None
    xtrabackup_incremental_cycle: (
        Literal["daily", "weekly", "2", "3", "4", "5", "6", "7"] | EmptyStrToNone
    ) = None
    xtrabackup_local_ssh_destination: NonEmptyStr | EmptyStrToNone = None
    xtrabackup_aes256_keyfile: NonEmptyStr | EmptyStrToNone = None
    xtrabackup_stop_replica: bool = False
    xtrabackup_lock_ddl: bool = False
    xtrabackup_bin_cmd: (
        Literal["xtrabackup", "mariadb-backup", "innobackupex"] | EmptyStrToNone
    ) = None
    binlog_prefix: NonEmptyStr | EmptyStrToNone = None
    binlog_purge_days: int | EmptyStrToNone = None
    binlog_extra_args: NonEmptyStr | EmptyStrToNone = None
    binlog_compress_cmd: NonEmptyStr | EmptyStrToNone = None
    binlog_cmd: NonEmptyStr | EmptyStrToNone = None
    binlog_run_all: bool = True
    s3_bucket: NonEmptyStr | EmptyStrToNone = None
    s3_storage_class: NonEmptyStr | EmptyStrToNone = None
    skip_s3_safety_check: bool = False
    awscli_s3_upload_extra_args: NonEmptyStr | EmptyStrToNone = None
    gs_bucket: NonEmptyStr | EmptyStrToNone = None
    rsync_path: NonEmptyStr | EmptyStrToNone = None


_MODE_BOOL_FIELDS: dict[BackupType, tuple[str, ...]] = {
    BackupType.MYDUMPER: (
        "mydumper_dump_triggers",
        "mydumper_desync_pxc",
        "mydumper_use_numa",
    ),
    BackupType.XTRABACKUP: (
        "xtrabackup_kill_queries",
        "xtrabackup_verify",
        "xtrabackup_prepare",
        "xtrabackup_desync_pxc",
        "xtrabackup_rsync",
        "xtrabackup_replica_info",
        "xtrabackup_stop_replica",
        "xtrabackup_lock_ddl",
    ),
    # ``binlog_run_all`` defaults to True and the legacy form always sends
    # it; gate-firing on it would break the existing form path. Leave the
    # B entry empty until the form is migrated off the legacy default.
    BackupType.BINLOG: (),
}


@apply_conditional_rules(mysql_backups_schema)
class BackupCreate(BackupConfigAll, ConditionalRulesModel):
    """Represent a Backup creation form with proper case-insensitive fields.

    :param hardlink: Whether to use hardlinks for full backups to save space.
    :type hardlink: bool
    :param compress: Whether to enable compression for backup data.
    :type compress: bool
    :param check_disk_space: Whether to check disk space before starting the backup.
    :type check_disk_space: bool
    :param encrypt: Whether to enable encryption for backup data.
    :type encrypt: bool
    :param encrypt_using_tmpdir: Whether to use a temporary directory for encryption operations.
    :type encrypt_using_tmpdir: bool
    :param post_run_encrypt: Whether to encrypt backup right after completion.
    :type post_run_encrypt: bool
    :param only_if_running_replica: Only perform backup if the server is a replica.
    :type only_if_running_replica: bool
    :param only_if_read_only: Only perform backup if the server is in read-only mode.
    :type only_if_read_only: bool
    :param logging_dir: Directory where logs are stored.
    :type logging_dir: NonEmptyStr | EmptyStrToNone
    :param backup_dir: Directory where backups are stored.
    :type backup_dir: NonEmptyStr | EmptyStrToNone
    :param defaults_file: Path to the MySQL defaults file.
    :type defaults_file: NonEmptyStr | EmptyStrToNone
    :param compression_algorithm: Compression algorithm to use.
    :type compression_algorithm: CompressionAlgorithm | EmptyStrToNone
    :param mydumper_daily_purge: Number of days to keep daily mydumper backups.
    :type mydumper_daily_purge: int | EmptyStrToNone
    :param mydumper_weekly_purge: Number of weeks to keep weekly mydumper backups.
    :type mydumper_weekly_purge: int | EmptyStrToNone
    :param mydumper_dump_triggers: Whether to include database triggers with mydumper.
    :type mydumper_dump_triggers: bool
    :param mydumper_desync_pxc: Whether to desynchronize PXC node before mydumper backup.
    :type mydumper_desync_pxc: bool
    :param mydumper_use_numa: Whether to enable NUMA support during mydumper backup.
    :type mydumper_use_numa: bool
    :param mydumper_extra_args: Additional command-line arguments for mydumper.
    :type mydumper_extra_args: str | EmptyStrToNone
    :param use_ftwrl_guardian: Whether to use FTWRL guardian to manage locks during backup.
    :type use_ftwrl_guardian: bool
    :param xtrabackup_copies: Number of backup copies for xtrabackup.
    :type xtrabackup_copies: int | EmptyStrToNone
    :param xtrabackup_kill_queries: Whether to terminate long-running queries.
    :type xtrabackup_kill_queries: bool
    :param xtrabackup_kill_queries_timeout: Maximum time (in seconds) to wait before terminating queries.
    :type xtrabackup_kill_queries_timeout: int | EmptyStrToNone
    :param xtrabackup_kill_query_type: Type of queries to avoid backup interruptions (select or all).
    :type xtrabackup_kill_query_type: Literal["select", "all"] | EmptyStrToNone
    :param xtrabackup_verify: Whether to verify backup after creation.
    :type xtrabackup_verify: bool
    :param xtrabackup_prepare: Whether to prepare the backup for restore.
    :type xtrabackup_prepare: bool
    :param xtrabackup_prepare_memory: Amount of memory allocated during prepare phase.
    :type xtrabackup_prepare_memory: NonEmptyStr | EmptyStrToNone
    :param xtrabackup_desync_pxc: Whether to desynchronize PXC node during xtrabackup.
    :type xtrabackup_desync_pxc: bool
    :param xtrabackup_rsync: Whether to use rsync for file copying in xtrabackup.
    :type xtrabackup_rsync: bool
    :param xtrabackup_replica_info: Whether to include replica info in xtrabackup.
    :type xtrabackup_replica_info: bool
    :param xtrabackup_defaults_file: Path to the defaults file for xtrabackup.
    :type xtrabackup_defaults_file: NonEmptyStr | EmptyStrToNone
    :param xtrabackup_extra_args: Additional command-line arguments passed to xtrabackup.
    :type xtrabackup_extra_args: NonEmptyStr | EmptyStrToNone
    :param xtrabackup_incremental_method: Method used for incremental backup.
    :type xtrabackup_incremental_method: Literal["less_space", "fast_restore"] | EmptyStrToNone
    :param xtrabackup_incremental_cycle: Frequency of incremental backups.
    :type xtrabackup_incremental_cycle: Literal["daily", "weekly", "2", "3", "4", "5", "6", "7"] | EmptyStrToNone
    :param xtrabackup_local_ssh_destination: SSH destination for storing backups remotely.
    :type xtrabackup_local_ssh_destination: NonEmptyStr | EmptyStrToNone
    :param xtrabackup_aes256_keyfile: Path to AES-256 encryption key file.
    :type xtrabackup_aes256_keyfile: NonEmptyStr | EmptyStrToNone
    :param xtrabackup_stop_replica: Whether to stop the replica before xtrabackup.
    :type xtrabackup_stop_replica: bool
    :param xtrabackup_lock_ddl: Whether to lock DDL operations during backup.
    :type xtrabackup_lock_ddl: bool
    :param xtrabackup_bin_cmd: Backup tool to use.
    :type xtrabackup_bin_cmd: Literal["xtrabackup", "mariadb-backup", "innobackupex"] | EmptyStrToNone
    :param binlog_prefix: Prefix used in binlog backup naming.
    :type binlog_prefix: NonEmptyStr | EmptyStrToNone
    :param binlog_purge_days: Number of days to retain binlogs before purging.
    :type binlog_purge_days: int | EmptyStrToNone
    :param binlog_extra_args: Extra arguments for binlog backup command.
    :type binlog_extra_args: NonEmptyStr | EmptyStrToNone
    :param binlog_compress_cmd: Command used to compress binlog backups.
    :type binlog_compress_cmd: NonEmptyStr | EmptyStrToNone
    :param binlog_cmd: Command used to create binlog backups.
    :type binlog_cmd: NonEmptyStr | EmptyStrToNone
    :param binlog_run_all: Whether to run all binlog backup types.
    :type binlog_run_all: bool
    :param s3_bucket: S3 bucket where backups will be stored.
    :type s3_bucket: NonEmptyStr | EmptyStrToNone
    :param s3_storage_class: S3 storage class (e.g., STANDARD, GLACIER).
    :type s3_storage_class: NonEmptyStr | EmptyStrToNone
    :param skip_s3_safety_check: Whether to disable safety checks before uploading to S3.
    :type skip_s3_safety_check: bool
    :param awscli_s3_upload_extra_args: Extra arguments to pass to AWS S3 upload (ExtraArgs dict).
        Example: "ChecksumAlgorithm=CRC32C".
    :type awscli_s3_upload_extra_args: NonEmptyStr | EmptyStrToNone
    :param rsync_path: Remote destination path for Rsync transfers.
    :type rsync_path: NonEmptyStr | EmptyStrToNone
    :param task_name: The name of the backup task.
    :type task_name: NonEmptyStr
    :param hostname: The hostname of the machine to back up.
    :type hostname: NonEmptyStr
    :param service_id: The identifier of the related service.
    :type service_id: int
    :param backup_type: The type of backup to perform.
    :type backup_type: BackupType
    :param encryption_recipient: The recipient used for encryption.
    :type encryption_recipient: NonEmptyStr | EmptyStrToNone
    :param binlog_alternative_host: Optional alternative host for binlog operations.
    :type binlog_alternative_host: NonEmptyStr | EmptyStrToNone
    :param alias: Optional alias for the server in the SERVERS_LIST section.
    :type alias: NonEmptyStr | EmptyStrToNone
    :param alert_on_fail: If True, send an alert if the task fails. Defaults to False.
    :type alert_on_fail: bool
    """

    task_name: NonEmptyStr
    hostname: NonEmptyStr
    service_id: int
    backup_type: BackupType
    encryption_recipient: NonEmptyStr | EmptyStrToNone = None
    binlog_alternative_host: NonEmptyStr | EmptyStrToNone = None
    alias: NonEmptyStr | EmptyStrToNone = None
    alert_on_fail: bool = False
    upload: list[UploadProvider] | None = None

    @field_validator("upload", mode="before")
    @classmethod
    def _coerce_empty_upload_to_none(cls, value: Any) -> Any:
        """Normalise the legacy empty-string ``upload`` to ``None``.

        The Jinja2 form path serialises an unset ``upload`` MultiChoice as
        an empty string; the JSON API path sends ``null`` or omits the
        field entirely. Coerce ``""`` and ``None`` to ``None`` so downstream
        parsing receives a clean ``list[UploadProvider] | None``.

        An explicit empty list (``upload=[]``) is rejected: ``None`` means
        "infer providers from bucket presence" (legacy semantics) while
        ``[]`` would mean "explicitly no providers selected" — distinct
        intents that must not collapse silently.
        """
        if value == []:
            raise ValueError(
                "'upload' cannot be an empty list; omit the field or send null."
            )
        if value in ("", None):
            return None
        if isinstance(value, str):
            return [value]
        return value

    @model_validator(mode="after")
    def validate_mode_bool_fields(self) -> Self:
        """Reject truthy boolean fields belonging to a different ``backup_type``.

        The framework's ``forbidden`` :class:`FieldGate` cannot express this
        constraint because ``_field_is_present`` treats ``False`` as
        present and would reject the (legitimate) default value too. This
        validator only fires for explicit ``True`` values.

        :return: The validated instance.
        :rtype: Self
        :raises ValueError: When a boolean field owned by mode A is
            ``True`` while ``backup_type`` is mode B (≠ A).
        """
        for owner_mode, names in _MODE_BOOL_FIELDS.items():
            if owner_mode == self.backup_type:
                continue
            for name in names:
                if getattr(self, name, False):
                    raise ValueError(
                        f"{name!r} must not be set when "
                        f"backup_type={self.backup_type.value}"
                    )
        return self

    @model_validator(mode="after")
    def validate_upload_provider_consistency(self) -> Self:
        """Enforce bidirectional consistency between ``upload`` and provider fields.

        Skipped when ``upload`` is ``None`` (legacy Jinja2 form path which
        infers providers from bucket-presence in
        :func:`app.sep.plugins.mysql_backups.deps._build_backup_task_payload_core`).
        On JSON API calls ``upload`` is the authoritative list; mismatched
        destination fields or missing destinations are rejected with 422.

        :return: The validated instance.
        :rtype: Self
        :raises ValueError: When a provider's destination field disagrees
            with the ``upload`` list, or when S3 auxiliary fields are set
            without ``S3`` in ``upload``.
        """
        if self.upload is None:
            return self
        selected = set(self.upload)
        pairs = (
            (UploadProvider.S3, self.s3_bucket),
            (UploadProvider.GSUTIL, self.gs_bucket),
            (UploadProvider.RSYNC, self.rsync_path),
        )
        for provider, value in pairs:
            present = bool(value)
            in_list = provider in selected
            if present and not in_list:
                raise ValueError(
                    f"{provider.name} destination field set but {provider.name!r} "
                    "is not in the upload list."
                )
            if in_list and not present:
                raise ValueError(
                    f"{provider.name!r} selected in upload but its destination "
                    "field is empty."
                )
        s3_aux = (
            self.s3_storage_class
            or self.skip_s3_safety_check
            or self.awscli_s3_upload_extra_args
        )
        if s3_aux and UploadProvider.S3 not in selected:
            raise ValueError(
                "S3 auxiliary fields set but 'S3' is not in the upload list."
            )
        return self

    @model_validator(mode="after")
    def validate_compression_algorithm(self) -> Self:
        """Validate that the compression_algorithm is compatible with the selected backup_type.

        :return: The validated instance
        :rtype: Self
        :raises ValueError: If the compression_algorithm is not valid for the specified backup_type.
        """
        allowed_algorithms = ALLOWED_COMPRESSIONS.get(self.backup_type, [])
        if (
            self.compression_algorithm is not None
            and self.compression_algorithm not in allowed_algorithms
        ):
            raise ValueError(
                f"Invalid compression algorithm {self.compression_algorithm!r} for "
                f"{self.backup_type.name} backup. Options are {allowed_algorithms}"
            )

        return self


class BackupConfigServer(BaseCaseInsensitiveModel):
    """Represent an individual server configuration.

    :param alias: A unique alias for the server.
    :type alias: NonEmptyStr
    :param backup_type: The type of the backup.
    :type backup_type: BackupType
    :param host: The hostname or address of the server.
    :type host: NonEmptyStr
    :param port: The port number used to connect to the host.
    :type port: int | None
    :param upload: A unique list of upload providers to use for the backup, if any.
    :type upload: UniqueList[UploadProvider] | None
    :param dir_encrypt_config: Specific configuration for the backup encryption.
    :type dir_encrypt_config: DirEncryptConfig | None
    """

    alias: NonEmptyStr
    backup_type: str
    host: NonEmptyStr
    port: int | None
    upload: list[str] | None = None
    dir_encrypt_config: DirEncryptConfig | None = None


class BackupConfig(BaseCaseInsensitiveModel):
    """Represent the overall backup configuration.

    :param all_servers: General settings for the backup.
    :type all_servers: BackupConfigAll
    :param server_list: A list of backup configuration for each server.
    :type server_list: list[BackupConfigServer]
    """

    all_servers: BackupConfigAll
    server_list: list[BackupConfigServer]


class BackupExecuteWrite(BaseModel):
    """Represent a JSON request body for executing a backup task.

    :param eta: Optional future datetime at which to schedule execution.
    :type eta: FutureDatetime | None
    :param chain_task_names: Optional list of task names to chain after this one.
    :type chain_task_names: list[str] | None
    :param chain_on_failure: Whether chained tasks run even on failure.
    :type chain_on_failure: bool | None
    """

    eta: FutureDatetime | None = None
    chain_task_names: list[str] | None = None
    chain_on_failure: bool | None = None


class BackupExecutionResponse(BaseModel):
    """Carry the response payload from ``POST /api/plugins/mysql_backups/{task_name}/execute``.

    :param task_name: The name of the task that was executed.
    :type task_name: str
    :param task_id: The id of the task-history row created by the tasks API.
    :type task_id: int | None
    """

    task_name: str
    task_id: int | None = None


class BackupTaskBase(BaseModel):
    """Carry the fields common to every backup-task API response.

    :param name: The name of the backup task.
    :type name: str
    :param owner: The entity or user that owns the task.
    :type owner: TaskOwner
    :param backup_type: The backup type recorded in task config.
    :type backup_type: BackupType | None
    :param status: The latest execution status of the task.
    :type status: TaskHistoryStatusEnum | None
    """

    name: str
    owner: TaskOwner
    backup_type: BackupType | None = None
    status: TaskHistoryStatusEnum | None = None


class BackupResponse(BackupTaskBase):
    """Represent a backup task API response.

    :param id: The unique identifier for the backup task.
    :type id: int | None
    :param backend: The backend executing the task.
    :type backend: TaskBackendEnum
    :param data: The raw configuration and parameters for the task.
    :type data: dict[str, Any]
    :param hostname: The executor hostname target.
    :type hostname: str | None
    :param protected: Whether the task is protected from deletion or modification.
    :type protected: bool
    :param alert_on_fail: If True, notifications fire on task failure.
    :type alert_on_fail: bool
    :param created_at: When the task was created.
    :type created_at: datetime | None
    :param updated_at: When the task was last modified.
    :type updated_at: datetime | None
    :param created_by: The user who initiated the task.
    :type created_by: str | None
    :param last_updated_by: The user who last modified the task record.
    :type last_updated_by: str | None
    """

    id: int | None = None
    backend: TaskBackendEnum
    data: dict[str, Any]
    hostname: str | None = None
    protected: bool
    alert_on_fail: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: str | None = None
    last_updated_by: str | None = None
