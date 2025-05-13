"""Define models for the Restore plugin."""

from typing import Literal

from pydantic import Field
from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import RequiredStr, EmptyStrToNone
from app.sep.plugins.backup.models import BackupType


class RestoreConfigAll(BaseCaseInsensitiveModel):
    """Define global configuration values for restore operations.

    This model contains settings that apply to all servers in a restore operation,
    including logging, slave configuration, checksum settings, SSH options, and
    backup tool-specific parameters.

    :param logging_dir: Directory path for storing restore operation logs.
    :type logging_dir: RequiredStr | EmptyStrToNone
    :param custom_mysql_init_command: Custom MySQL initialization command.
    :type custom_mysql_init_command: RequiredStr | EmptyStrToNone
    :param port: Port number for the restore operation.
    :type port: int | None
    :param slave_from_master: Whether to configure the restored server as a slave.
    :type slave_from_master: bool
    :param wait_for_catchup: Whether to wait for slave to catch up with master.
    :type wait_for_catchup: bool
    :param master_ip: IP address of the master server.
    :type master_ip: RequiredStr | EmptyStrToNone
    :param master_port: Port number of the master server.
    :type master_port: int | None
    :param master_user: Username for master server authentication.
    :type master_user: RequiredStr | EmptyStrToNone
    :param master_password: Password for master server authentication.
    :type master_password: RequiredStr | EmptyStrToNone
    :param continue_replication: Whether to continue replication after restore.
    :type continue_replication: bool
    :param run_checksum: Whether to run checksum verification after restore.
    :type run_checksum: bool
    :param pt_checksum_extra_args: Additional arguments for pt-checksum.
    :type pt_checksum_extra_args: RequiredStr | EmptyStrToNone
    :param ssh_port: SSH port for remote operations.
    :type ssh_port: int | None
    :param ssh_user: SSH username for remote operations.
    :type ssh_user: RequiredStr | EmptyStrToNone
    :param xb_prepare_memory: Memory limit for xtrabackup prepare.
    :type xb_prepare_memory: RequiredStr | EmptyStrToNone
    :param xb_parallel: Number of parallel threads for xtrabackup.
    :type xb_parallel: int | None
    :param xtrabackup_aes256_keyfile: Path to AES256 keyfile for encrypted backups.
    :type xtrabackup_aes256_keyfile: RequiredStr | EmptyStrToNone
    :param xtrabackup_bin_cmd: Binary command to use for xtrabackup operations.
    :type xtrabackup_bin_cmd: Literal["xtrabackup", "mariadb-backup", "innobackupex"] | EmptyStrToNone
    :param xtrabackup_restore_args: Additional arguments for xtrabackup restore.
    :type xtrabackup_restore_args: RequiredStr | EmptyStrToNone
    :param myloader_threads: Number of threads for myloader operations.
    :type myloader_threads: int | None
    :param hostname: Hostname for alert notifications.
    :type hostname: RequiredStr | EmptyStrToNone
    """

    logging_dir: RequiredStr | EmptyStrToNone = None
    custom_mysql_init_command: RequiredStr | EmptyStrToNone = None
    port: int | None = None

    # Slave Settings
    slave_from_master: bool = False
    wait_for_catchup: bool = False
    master_ip: RequiredStr | EmptyStrToNone = None
    master_port: int | None = None
    master_user: RequiredStr | EmptyStrToNone = None
    master_password: RequiredStr | EmptyStrToNone = None
    continue_replication: bool = Field(False, alias="continue_replication")

    # Checksum Settings
    run_checksum: bool = False
    pt_checksum_extra_args: RequiredStr | EmptyStrToNone = None

    # SSH Options
    ssh_port: int | None = None
    ssh_user: RequiredStr | EmptyStrToNone = None

    # Xtrabackup
    xb_prepare_memory: RequiredStr | EmptyStrToNone = None
    xb_parallel: int | None = None
    xtrabackup_aes256_keyfile: RequiredStr | EmptyStrToNone = None
    xtrabackup_bin_cmd: Literal["xtrabackup", "mariadb-backup", "innobackupex"] | EmptyStrToNone = None
    xtrabackup_restore_args: RequiredStr | EmptyStrToNone = None

    # Myloader
    myloader_threads: int | None = None

    # Alerts
    hostname: RequiredStr | EmptyStrToNone = None


class RestoreConfigServer(BaseCaseInsensitiveModel):
    """Define restore job configuration for a specific server.

    This model contains server-specific settings for restore operations, including
    common fields applicable to all backup types and specific fields for different
    backup tools (XtraBackup and Mydumper).

    :param alias: Unique identifier for the restore job.
    :type alias: RequiredStr
    :param backup_type: Type of backup to restore from.
    :type backup_type: BackupType
    :param backup_source: Source location of the backup.
    :type backup_source: RequiredStr
    :param pre_script: Script to execute before restore.
    :type pre_script: RequiredStr | EmptyStrToNone
    :param post_script: Script to execute after restore.
    :type post_script: RequiredStr | EmptyStrToNone
    :param nagios_check_at: Nagios check configuration.
    :type nagios_check_at: RequiredStr | EmptyStrToNone
    :param datadir: Data directory path for XtraBackup restores.
    :type datadir: RequiredStr | EmptyStrToNone
    :param kill_mysql: Whether to kill MySQL process before restore.
    :type kill_mysql: bool
    :param restore_config: Whether to restore server configuration.
    :type restore_config: bool
    :param dest_host: Destination host for Mydumper restores.
    :type dest_host: RequiredStr | EmptyStrToNone
    :param dest_port: Destination port for Mydumper restores.
    :type dest_port: int | None
    :param local_path: Local path for backup files.
    :type local_path: RequiredStr | EmptyStrToNone
    :param overwrite_tables: Whether to overwrite existing tables.
    :type overwrite_tables: bool
    :param policy: Database policy type for restore.
    :type policy: Literal["mysql", "mongodb", "postgresql"] | EmptyStrToNone
    :param database: Target database name for restore.
    :type database: RequiredStr | EmptyStrToNone
    :param myloader_extra_args: Additional arguments for myloader.
    :type myloader_extra_args: RequiredStr | EmptyStrToNone
    :param skip_databases: List of databases to skip during restore.
    :type skip_databases: list[str] | None
    :param include_databases: List of databases to include in restore.
    :type include_databases: list[str] | None
    """

    alias: RequiredStr
    backup_type: BackupType
    backup_source: RequiredStr

    # -- Common Fields (safe to use with any backup_type) --
    pre_script: RequiredStr | EmptyStrToNone = None
    post_script: RequiredStr | EmptyStrToNone = None
    nagios_check_at: RequiredStr | EmptyStrToNone = None

    # -- XtraBackup-Specific Fields (backup_type == X) --
    datadir: RequiredStr | EmptyStrToNone = None
    kill_mysql: bool = False
    restore_config: bool = False

    # -- Mydumper-Specific Fields (backup_type == M) --
    dest_host: RequiredStr | EmptyStrToNone = None
    dest_port: int | None = None
    local_path: RequiredStr | EmptyStrToNone = None
    overwrite_tables: bool = False
    policy: Literal["mysql", "mongodb", "postgresql"] | EmptyStrToNone = None
    database: RequiredStr | EmptyStrToNone = None
    myloader_extra_args: RequiredStr | EmptyStrToNone = None
    skip_databases: list[str] | None = None
    include_databases: list[str] | None = None


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
