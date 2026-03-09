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

from pydantic import Field

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import EmptyStrToNone, EnumFieldMixin, NonEmptyStr
from app.sep.plugins.backup.models import BackupType


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
    :type binlog_restore_extra_args: RequiredStr | EmptyStrToNone
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
    binlog_restore_extra_args: RequiredStr | EmptyStrToNone = None


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


class RestoreCreate(RestoreConfigAll, BaseRestoreConfigServer):
    """Model for creating a restore task.

    Inherits from RestoreConfigAll and BaseRestoreConfigServer, adding task and service identifiers.

    :param hostname: The hostname of the machine to back up.
    :type hostname: NonEmptyStr
    :param task_name: Name of the restore task.
    :type task_name: NonEmptyStr
    :param service_id: Service identifier for the restore task.
    :type service_id: NonEmptyStr | EmptyStrToNone = None
    :param schema_id: Schema identifier for restore.
    :type schema_id: NonEmptyStr | EmptyStrToNone
    """

    hostname: NonEmptyStr
    task_name: NonEmptyStr
    service_id: NonEmptyStr | EmptyStrToNone = None
    schema_id: NonEmptyStr | EmptyStrToNone = None
