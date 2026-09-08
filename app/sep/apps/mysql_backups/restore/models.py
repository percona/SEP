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

from enum import StrEnum
from typing import Annotated, Any

from pydantic import Field, field_validator, model_validator

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import EmptyStrToNone, EnumFieldMixin, NonEmptyStr
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework import BaseTaskResponse
from app.sep.apps.framework.form_dsl import (
    Choices,
    RemoteChoices,
    SchemaRef,
    ServiceRef,
    TaskFormModel,
    Ui,
)
from app.sep.apps.mysql_backups.models import (
    BackupType,
    ensure_backup_source_shell_safe,
)

OWNER = "RESTORES"


class S3Tool(EnumFieldMixin, StrEnum):
    """Allowed tools to interact with S3-compatible services."""

    S3CMD = "s3cmd"
    AWSCLI = "awscli"


class XtraBackupTool(EnumFieldMixin, StrEnum):
    """Allowed commands for XtraBackup-style restores."""

    INNOBACKUPEX = "innobackupex"
    XTRABACKUP = "xtrabackup"
    MARIADB_BACKUP = "mariadb-backup"


class RestoreConfigAll(BaseCaseInsensitiveModel):
    """Global config values for restore operations.

    This model contains settings that apply to all servers in a restore operation,
    including logging, SSH options, S3 tool selection, and GPG encryption.

    :param logging_dir: Directory path for storing restore operation logs.
    :type logging_dir: NonEmptyStr | EmptyStrToNone
    :param port: Port number for the restore operation.
    :type port: int | None
    :param custom_mysql_init_command: Custom MySQL initialization command.
    :type custom_mysql_init_command: NonEmptyStr | EmptyStrToNone
    :param ssh_user: SSH username for remote operations (default: "percona").
    :type ssh_user: NonEmptyStr | EmptyStrToNone
    :param ssh_port: SSH port for remote operations (default: 22).
    :type ssh_port: int | EmptyStrToNone
    :param ssh_key: SSH key name for authentication (not full path).
    :type ssh_key: NonEmptyStr | EmptyStrToNone
    :param s3_tool: Tool to use for S3 operations (default: S3CMD).
    :type s3_tool: S3Tool
    :param gpg_password_file: Path to the GPG encryption key password file.
    :type gpg_password_file: NonEmptyStr | EmptyStrToNone
    """

    logging_dir: NonEmptyStr | EmptyStrToNone = None
    port: int | None = None
    custom_mysql_init_command: NonEmptyStr | EmptyStrToNone = None

    # SSH Options
    ssh_user: NonEmptyStr | EmptyStrToNone = Field(default="percona")
    ssh_port: int | EmptyStrToNone = Field(default=22)
    ssh_key: NonEmptyStr | EmptyStrToNone = None  # only key name, not full path

    # S3 tool selection (default is s3cmd)
    s3_tool: S3Tool = S3Tool.S3CMD

    # GPG encryption key password file path
    gpg_password_file: NonEmptyStr | EmptyStrToNone = None


class BaseRestoreConfigServer(BaseCaseInsensitiveModel):
    """Restore job configuration for a specific Mydumper restore job.

    This model contains server-specific settings for a restore operation, including
    backup source, destination, threading, and script hooks.

    :param backup_type: Type of backup to restore from.
    :type backup_type: BackupType
    :param backup_source: Source location of the backup.
    :type backup_source: NonEmptyStr
    :param local_path: Local path for backup files.
    :type local_path: NonEmptyStr | EmptyStrToNone
    :param overwrite_tables: Whether to overwrite existing tables.
    :type overwrite_tables: bool
    :param myloader_threads: Number of threads for myloader operations.
    :type myloader_threads: int | None
    :param myloader_extra_args: Additional arguments for myloader.
    :type myloader_extra_args: NonEmptyStr | EmptyStrToNone
    :param skip_databases: Comma-separated string of databases to skip during restore.
    :type skip_databases: NonEmptyStr | EmptyStrToNone
    :param include_databases: Comma-separated string of databases to include in restore.
    :type include_databases: NonEmptyStr | EmptyStrToNone
    :param pre_script: Script to execute before restore.
    :type pre_script: NonEmptyStr | EmptyStrToNone
    :param post_script: Script to execute after restore.
    :type post_script: NonEmptyStr | EmptyStrToNone
    :param skip_incrementals: Whether to skip incremental backups during restore.
    :type skip_incrementals: bool
    :param datadir: MySQL data directory path.
    :type datadir: NonEmptyStr
    :param kill_mysql: Whether to kill MySQL process before restore.
    :type kill_mysql: bool
    :param xb_prepare_memory: Memory limit for xtrabackup prepare operation.
    :type xb_prepare_memory: NonEmptyStr | EmptyStrToNone
    :param xb_parallel: Number of parallel threads for xtrabackup operations.
    :type xb_parallel: int | None
    :param xtrabackup_bin_cmd: Tool to use for xtrabackup operations.
    :type xtrabackup_bin_cmd: XtraBackupTool
    :param restore_mycnf: Whether to restore my.cnf file during restore.
    :type restore_mycnf: bool
    :param incremental_dest_path: Path for incremental backup files.
    :type incremental_dest_path: NonEmptyStr | EmptyStrToNone
    :param xtrabackup_restore_args: Additional arguments for xtrabackup restore.
    :type xtrabackup_restore_args: NonEmptyStr | EmptyStrToNone
    :param keyring_file_data: Path to the keyring file for encryption.
    :type keyring_file_data: NonEmptyStr | EmptyStrToNone
    :param xtrabackup_aes256_keyfile: Path to AES-256 key file for encryption.
    :type xtrabackup_aes256_keyfile: NonEmptyStr | EmptyStrToNone
    :param slave_from_master: Whether to configure the restored instance as a slave.
    :type slave_from_master: bool
    :param wait_for_catchup: Whether to wait for slave to catch up with master.
    :type wait_for_catchup: bool
    :param master_ip: IP address of the master server for replication.
    :type master_ip: NonEmptyStr | EmptyStrToNone
    :param master_port: Port number of the master server for replication.
    :type master_port: int | None
    :param master_user: Username for replication user on master.
    :type master_user: NonEmptyStr | EmptyStrToNone
    :param master_password: Password for replication user on master.
    :type master_password: NonEmptyStr | EmptyStrToNone
    :param start_file: Binary log file to start replication from.
    :type start_file: NonEmptyStr | EmptyStrToNone
    :param start_position: Position in binary log file to start replication from.
    :type start_position: int | EmptyStrToNone
    :param stop_file: Binary log file to stop replication at.
    :type stop_file: NonEmptyStr | EmptyStrToNone
    :param stop_position: Position in binary log file to stop replication at.
    :type stop_position: int | EmptyStrToNone
    :param use_sql_file: Path to SQL file to use for restore instead of backup files.
    :type use_sql_file: NonEmptyStr | EmptyStrToNone
    :param binlog_restore_extra_args: Additional arguments for mysqlbinlog restore command.
    :type binlog_restore_extra_args: NonEmptyStr | EmptyStrToNone
    """

    backup_type: BackupType
    backup_source: NonEmptyStr
    local_path: NonEmptyStr | EmptyStrToNone = None
    overwrite_tables: bool = False
    myloader_threads: int | EmptyStrToNone = Field(default=4)
    myloader_extra_args: NonEmptyStr | EmptyStrToNone = None
    skip_databases: NonEmptyStr | EmptyStrToNone = None
    include_databases: NonEmptyStr | EmptyStrToNone = None
    pre_script: NonEmptyStr | EmptyStrToNone = None
    post_script: NonEmptyStr | EmptyStrToNone = None
    skip_incrementals: bool = False
    datadir: NonEmptyStr | EmptyStrToNone = None
    kill_mysql: bool = False
    xb_prepare_memory: NonEmptyStr | EmptyStrToNone = None
    xb_parallel: int | EmptyStrToNone = Field(default=4)
    xtrabackup_bin_cmd: XtraBackupTool | EmptyStrToNone = None
    restore_mycnf: bool = False
    incremental_dest_path: NonEmptyStr | EmptyStrToNone = None
    xtrabackup_restore_args: NonEmptyStr | EmptyStrToNone = None
    keyring_file_data: NonEmptyStr | EmptyStrToNone = None
    xtrabackup_aes256_keyfile: NonEmptyStr | EmptyStrToNone = None
    slave_from_master: bool = False
    wait_for_catchup: bool = False
    master_ip: NonEmptyStr | EmptyStrToNone = None
    master_port: int | EmptyStrToNone = Field(default=3306)
    master_user: NonEmptyStr | EmptyStrToNone = None
    master_password: NonEmptyStr | EmptyStrToNone = None
    start_file: NonEmptyStr | EmptyStrToNone = None
    start_position: int | EmptyStrToNone = None
    stop_file: NonEmptyStr | EmptyStrToNone = None
    stop_position: int | EmptyStrToNone = None
    use_sql_file: NonEmptyStr | EmptyStrToNone = None
    binlog_restore_extra_args: NonEmptyStr | EmptyStrToNone = None

    @field_validator("backup_source")
    @classmethod
    def validate_backup_source_shell_safe(cls, value: str) -> str:
        """Reject shell metacharacters in backup source (defense in depth)."""
        return ensure_backup_source_shell_safe(value)


class RestoreConfigServer(BaseRestoreConfigServer):
    """Server-specific restore configuration.

    Extends BaseRestoreConfigServer with additional required fields for alias, destination host, and port.

    :param alias: Unique identifier for the restore job.
    :type alias: NonEmptyStr
    :param dest_host: Destination host for the restore.
    :type dest_host: NonEmptyStr | EmptyStrToNone
    :param dest_port: Destination port for the restore.
    :type dest_port: int
    :param database: Target database name for restore.
    :type database: NonEmptyStr | EmptyStrToNone
    """

    alias: NonEmptyStr
    dest_host: NonEmptyStr | EmptyStrToNone = None
    dest_port: int | EmptyStrToNone = None
    database: NonEmptyStr | EmptyStrToNone = None


class RestoreConfig(BaseCaseInsensitiveModel):
    """Define the complete configuration for a restore operation.

    This model combines global settings applicable to all servers with a list of
    server-specific configurations for a complete restore operation setup.

    :param all_servers: Global configuration settings for all servers.
    :type all_servers: RestoreConfigAll
    :param server_list: List of server-specific restore configurations.
    :type server_list: list[RestoreConfigServer]
    """

    all_servers: RestoreConfigAll
    server_list: list[RestoreConfigServer]


class RestoreCreate(TaskFormModel):
    """Declare the model-first create/update body and ``GET /schema`` source for Restores.

    Declares every restore form field once, in section order (Task, General,
    Mydumper, XtraBackup, Binlog), with the DSL markers driving the derived
    schema. The previously-inherited config models (:class:`RestoreConfigAll` and
    :class:`BaseRestoreConfigServer`) stay the YAML-serialization targets the
    payload builder populates via ``extract_model_from_instance``; this model
    re-declares their fields directly so it can also carry presentation metadata.

    The per-``backup_type`` section visibility is expressed in the view layout
    (``restore/views.py``), not as field-level gates: several mode-specific config
    fields carry non-``None`` defaults (``myloader_threads``, ``xb_parallel``,
    ``master_port``), so a field-level ``Forbidden`` gate would reject those
    defaults on a cross-mode restore. Keeping the model permissive preserves the
    legacy payload contract byte-for-byte.

    ``service_id`` / ``schema_id`` keep their str-accepting annotation (carrying
    the ``"-1"`` ``UNKNOWN_SERVICE_SENTINEL``); their ``ServiceRef`` / ``SchemaRef``
    markers drive only the ``GET /schema`` widgets, while the conditional,
    404-tolerant resolution lives in ``deps.resolve_restore_entities``.
    """

    backup_type: Annotated[
        BackupType,
        Choices((("M", "Mydumper"), ("X", "XtraBackup"), ("B", "Binlog"))),
        Ui(
            section="Task",
            description=(
                "Restore method for this task; it has to match how the backup was "
                "taken, and it selects which sections below apply"
            ),
        ),
    ]

    service_id: Annotated[
        NonEmptyStr | EmptyStrToNone,
        ServiceRef(service_types=(ServiceTypeEnum.MYSQL,), allow_custom=True),
        Ui(
            label="Destination Database Service",
            section="Task",
            description=(
                "Database service being restored into. A Mydumper restore needs an "
                "existing MySQL service, whose address and port become the load "
                "destination; an XtraBackup or Binlog restore only records the name, "
                "so a typed one is accepted there."
            ),
        ),
    ] = None
    backup_source: Annotated[
        NonEmptyStr,
        RemoteChoices(
            endpoint="/apps/mysql_backups/backup-sources/choices",
            allow_custom=True,
        ),
        Ui(
            section="Task",
            depends_on="service_id",
            description=(
                "Where the backup is stored. Select a database service above to list "
                "its completed backups, then pick one — or enter a local path "
                "(/backups/mydumper/20240101), a remote host (db01:/path/to/backup), "
                "s3://bucket/path, or gs://bucket/path. Add /latest to any of these to "
                "restore the most recent backup. Avoid these characters: $ ; | & ( ) `"
            ),
        ),
    ]
    logging_dir: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(
            label="Logging directory",
            section="General",
            description="Directory on the target host for this restore's log files",
        ),
    ] = None
    port: Annotated[
        int | None,
        Ui(
            section="General",
            description=(
                "Port SEP connects to on the target host when it queries the server "
                "during an XtraBackup restore (defaults to 3306). A Mydumper restore "
                "loads over the destination service's own address and a Binlog restore "
                "replays through a local client, so neither uses it."
            ),
        ),
    ] = None
    custom_mysql_init_command: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(
            label="Custom MySQL init command",
            section="General",
            description=(
                "Service command used to stop and start MySQL during an XtraBackup "
                "restore, such as /usr/bin/systemctl; detected automatically when left "
                "empty. Mydumper and Binlog restores never stop MySQL, so they ignore "
                "it."
            ),
        ),
    ] = None
    ssh_user: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(
            label="SSH user",
            section="General",
            description=(
                "SSH user for fetching a backup stored on a remote host. Unused for a "
                "local, S3 or Google Cloud Storage source."
            ),
        ),
    ] = Field(default="percona")
    ssh_port: Annotated[
        int | EmptyStrToNone,
        Ui(
            label="SSH port",
            section="General",
            description="SSH port for fetching a backup stored on a remote host",
        ),
    ] = Field(default=22)
    ssh_key: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(
            label="SSH key name",
            section="General",
            description=(
                "Unused: fetching a backup from a remote host always authenticates "
                "with the SSH user's own id_rsa key."
            ),
        ),
    ] = None
    s3_tool: Annotated[
        S3Tool,
        Ui(
            label="S3 tool",
            section="General",
            description=(
                "Client used to download the backup. Only used for an s3:// source."
            ),
        ),
    ] = S3Tool.S3CMD
    gpg_password_file: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(
            label="GPG password file",
            section="General",
            description=(
                "Path on the target host to the file holding the passphrase for a "
                "GPG-encrypted backup"
            ),
        ),
    ] = None

    schema_id: Annotated[
        NonEmptyStr | EmptyStrToNone,
        SchemaRef(allow_custom=True),
        Ui(
            label="Target database",
            section="Mydumper",
            depends_on="service_id",
            description=(
                "Database the backup is loaded into; pick one from inventory. Leave "
                "empty to restore into the databases the backup came from. A name "
                "typed here instead of picked is ignored and does the same."
            ),
        ),
    ] = None
    local_path: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(
            label="Local path",
            section="Mydumper",
            description=(
                "Staging directory on the target host where the backup is assembled "
                "before it is loaded; the staging copy is removed once the load "
                "succeeds, and left behind after a failure (defaults to /tmp)"
            ),
        ),
    ] = None
    overwrite_tables: Annotated[
        bool,
        Ui(
            label="Overwrite tables",
            section="Mydumper",
            description=(
                "Let the load replace tables that already exist in the target "
                "database. Without it the load fails on the first table that is "
                "already there."
            ),
            destructive=(
                "Existing tables in the target database are dropped before the "
                "backup is loaded. Rows written since the backup was taken are "
                "lost."
            ),
        ),
    ] = False
    myloader_threads: Annotated[
        int | EmptyStrToNone,
        Ui(
            label="Myloader threads",
            section="Mydumper",
            description="How many tables are loaded in parallel",
        ),
    ] = Field(default=4)
    myloader_extra_args: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(
            label="Myloader extra args",
            section="Mydumper",
            description="Extra arguments appended to the myloader command",
        ),
    ] = None
    skip_databases: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(
            label="Skip databases",
            section="Mydumper",
            description=(
                "Databases to leave out of the restore, comma-separated. They are "
                "filtered out as the backup is fetched, by file name, and are ignored "
                "for a Google Cloud Storage source."
            ),
        ),
    ] = None
    include_databases: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(
            label="Include databases",
            section="Mydumper",
            description=(
                "Databases to restore, comma-separated, ignoring the rest of the "
                "backup. Filtered as the backup is fetched, by file name, and ignored "
                "for a Google Cloud Storage source."
            ),
        ),
    ] = None
    pre_script: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(
            label="Pre-script",
            section="Mydumper",
            description=(
                "Path on the target host to a script run before the load. A .sql file "
                "is executed against the target MySQL; anything else runs as a "
                "command."
            ),
        ),
    ] = None
    post_script: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(
            label="Post-script",
            section="Mydumper",
            description=(
                "Path on the target host to a script run after the load. A .sql file "
                "is executed against the target MySQL; anything else runs as a "
                "command."
            ),
        ),
    ] = None

    skip_incrementals: Annotated[
        bool,
        Ui(
            label="Skip incrementals",
            section="XtraBackup",
            description=(
                "Restore only the base backup and ignore the incrementals chained to it"
            ),
        ),
    ] = False
    # The mark belongs on the field naming the target rather than on a toggle:
    # the wipe is unconditional, and an empty entry aborts the restore instead of
    # being autodetected, so every restore that runs sets this.
    datadir: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(
            label="Data directory",
            section="XtraBackup",
            description=(
                "MySQL data directory the backup is restored into. Required: it has to "
                "exist already, and everything currently in it is deleted."
            ),
            destructive=(
                "The data directory is emptied before the backup is restored into "
                "it. Whatever it holds now, including a live dataset, is lost."
            ),
        ),
    ] = None
    kill_mysql: Annotated[
        bool,
        Ui(
            label="Kill MySQL",
            section="XtraBackup",
            description=(
                "MySQL is always stopped before the data directory is replaced, so "
                "this setting changes nothing."
            ),
        ),
    ] = False
    xb_prepare_memory: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(
            label="XtraBackup prepare memory",
            section="XtraBackup",
            description=(
                "Memory the prepare step may use, as a size such as 2G (defaults to "
                "100M)"
            ),
        ),
    ] = None
    xb_parallel: Annotated[
        int | EmptyStrToNone,
        Ui(
            label="XtraBackup parallel",
            section="XtraBackup",
            description=(
                "How many files are decrypted and decompressed in parallel (defaults "
                "to 4). Clearing it leaves the decompression unbounded."
            ),
        ),
    ] = Field(default=4)
    xtrabackup_bin_cmd: Annotated[
        XtraBackupTool | EmptyStrToNone,
        Ui(
            label="XtraBackup binary",
            section="XtraBackup",
            description=(
                "Which binary prepares the backup; pick the one matching the tool that "
                "took it"
            ),
        ),
    ] = None
    restore_mycnf: Annotated[
        bool,
        Ui(
            label="Restore my.cnf",
            section="XtraBackup",
            description=(
                "Restore the MySQL configuration files saved in the backup before "
                "preparing it, rewriting server id to a fresh value. Choosing one that "
                "is not already taken queries the replication source below."
            ),
        ),
    ] = False
    incremental_dest_path: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(
            label="Incremental destination path",
            section="XtraBackup",
            description=(
                "Directory where an incremental chain is assembled before it is "
                "prepared (defaults to /tmp/pxb_incrementals)"
            ),
        ),
    ] = None
    xtrabackup_restore_args: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(
            label="XtraBackup restore args",
            section="XtraBackup",
            description="Extra arguments appended to the prepare command",
        ),
    ] = None
    keyring_file_data: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(
            label="Keyring file data",
            section="XtraBackup",
            description=(
                "Keyring file the prepare needs for a backup with encrypted "
                "tablespaces; read only when the backup binary above is xtrabackup. "
                "Falls back to a path found in the configuration files stored inside "
                "the backup when left empty."
            ),
        ),
    ] = None
    xtrabackup_aes256_keyfile: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(
            label="XtraBackup AES-256 keyfile",
            section="XtraBackup",
            description=(
                "AES-256 key file the backup was encrypted with, needed to decrypt it "
                "before the prepare"
            ),
        ),
    ] = None
    slave_from_master: Annotated[
        bool,
        Ui(
            label="Slave from master",
            section="XtraBackup",
            description=(
                "Start replication once the restore finishes, using the coordinates "
                "saved in the backup"
            ),
        ),
    ] = False
    wait_for_catchup: Annotated[
        bool,
        Ui(
            label="Wait for catchup",
            section="XtraBackup",
            description=(
                "Wait for the restored replica to catch up and fail the task if it "
                "does not. Needs replication to be started above."
            ),
        ),
    ] = False
    master_ip: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(
            label="Master IP",
            section="XtraBackup",
            description=(
                "Replication source the restored instance connects to. Used when "
                "replication is started above."
            ),
        ),
    ] = None
    master_port: Annotated[
        int | EmptyStrToNone,
        Ui(
            label="Master port",
            section="XtraBackup",
            description=(
                "Port used to query the replication source for an unused server id "
                "when 'Restore my.cnf' is set. Starting replication itself uses the "
                "port in the coordinates saved in the backup."
            ),
        ),
    ] = Field(default=3306)
    master_user: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(
            label="Master user",
            section="XtraBackup",
            description="Account the restored instance replicates with",
        ),
    ] = None
    master_password: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(
            label="Master password",
            section="XtraBackup",
            description="Password for the replication account",
        ),
    ] = None

    start_file: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(
            label="Start file",
            section="Binlog",
            description="First binlog file to replay",
        ),
    ] = None
    start_position: Annotated[
        int | EmptyStrToNone,
        Ui(
            label="Start position",
            section="Binlog",
            description="Position in the first file to start replaying from",
        ),
    ] = None
    stop_file: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(
            label="Stop file",
            section="Binlog",
            description="Last binlog file to replay",
        ),
    ] = None
    stop_position: Annotated[
        int | EmptyStrToNone,
        Ui(
            label="Stop position",
            section="Binlog",
            description="Position in the last file to stop replaying at",
        ),
    ] = None
    use_sql_file: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(
            label="Use SQL file",
            section="Binlog",
            description=(
                "Dump the binlog range to restore.sql in the staging directory first "
                "and then apply that file, instead of piping the binlogs straight into "
                "MySQL"
            ),
        ),
    ] = None
    binlog_restore_extra_args: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(
            label="Binlog restore extra args",
            section="Binlog",
            description="Extra arguments appended to the mysqlbinlog replay command",
        ),
    ] = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_int_reference_ids(cls, data: Any) -> Any:
        """Coerce int ``service_id`` / ``schema_id`` (JSON body) to str.

        The HTML form path receives these fields as ``NonEmptyStr |
        EmptyStrToNone`` directly. The JSON API (React schema form) may send
        inventory ids as ints; without coercion they fail the str-typed fields.
        Form submissions arriving as strings are unaffected.

        :param data: The raw input passed to ``model_validate``.
        :return: The input with stringified reference ids when they were ints,
            or ``data`` unchanged otherwise.
        """
        if not isinstance(data, dict):
            return data
        updates: dict[str, str] = {}
        for key in ("service_id", "schema_id"):
            value = data.get(key)
            if isinstance(value, int):
                updates[key] = str(value)
        if updates:
            return {**data, **updates}
        return data

    @field_validator("backup_source")
    @classmethod
    def validate_backup_source_shell_safe(cls, value: str) -> str:
        """Reject shell metacharacters in backup source (defense in depth)."""
        return ensure_backup_source_shell_safe(value)


class RestoresResponse(BaseTaskResponse):
    """Represent a restore task API response.

    Extend the standard task-response surface with the restore-specific
    destination facts the detail view renders; the shared task identity,
    status, audit, and anonymization fields come from
    :class:`~app.sep.apps.framework.responses.BaseTaskResponse`.

    :param backup_type: The backup type recorded in task config.
    :param hostname: The executor hostname target.
    :param host: The destination host recorded in task config.
    :param port: The destination port recorded in task config.
    """

    backup_type: BackupType | None = None
    hostname: str | None = None
    host: str | None = None
    port: int | None = None
