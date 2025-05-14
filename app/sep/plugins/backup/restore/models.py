"""Define models for the Restore plugin."""

from enum import StrEnum

from pydantic import Field

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import EmptyStrToNone, EnumFieldMixin, RequiredStr
from app.sep.plugins.backup.models import BackupType


class S3Tool(EnumFieldMixin, StrEnum):
    """Allowed tools to interact with S3-compatible services."""

    S3CMD = "s3cmd"
    AWSCLI = "awscli"


class RestoreConfigAll(BaseCaseInsensitiveModel):
    """Global config values for restore operations.

    This model contains settings that apply to all servers in a restore operation,
    including logging, SSH options, S3 tool selection, and GPG encryption.

    :param logging_dir: Directory path for storing restore operation logs.
    :type logging_dir: RequiredStr | EmptyStrToNone
    :param port: Port number for the restore operation.
    :type port: int | None
    :param custom_mysql_init_command: Custom MySQL initialization command.
    :type custom_mysql_init_command: RequiredStr | EmptyStrToNone
    :param ssh_user: SSH username for remote operations (default: "percona").
    :type ssh_user: RequiredStr | EmptyStrToNone
    :param ssh_port: SSH port for remote operations (default: 22).
    :type ssh_port: int | None
    :param ssh_key: SSH key name for authentication (not full path).
    :type ssh_key: RequiredStr | EmptyStrToNone
    :param s3_tool: Tool to use for S3 operations (default: S3CMD).
    :type s3_tool: S3Tool
    :param gpg_password_file: Path to the GPG encryption key password file.
    :type gpg_password_file: RequiredStr | EmptyStrToNone
    """

    logging_dir: RequiredStr | EmptyStrToNone = None
    port: int | None = None
    custom_mysql_init_command: RequiredStr | EmptyStrToNone = None

    # SSH Options
    ssh_user: RequiredStr | EmptyStrToNone = Field(default="percona")
    ssh_port: int | None = Field(default=22)
    ssh_key: RequiredStr | EmptyStrToNone = None  # only key name, not full path

    # S3 tool selection (default is s3cmd)
    s3_tool: S3Tool = S3Tool.S3CMD

    # GPG encryption key password file path
    gpg_password_file: RequiredStr | EmptyStrToNone = None


class BaseRestoreConfigServer(BaseCaseInsensitiveModel):
    """Restore job configuration for a specific Mydumper restore job.

    This model contains server-specific settings for a restore operation, including
    backup source, destination, threading, and script hooks.

    :param backup_type: Type of backup to restore from.
    :type backup_type: BackupType
    :param backup_source: Source location of the backup.
    :type backup_source: RequiredStr
    :param local_path: Local path for backup files.
    :type local_path: RequiredStr | EmptyStrToNone
    :param overwrite_tables: Whether to overwrite existing tables.
    :type overwrite_tables: bool
    :param myloader_threads: Number of threads for myloader operations.
    :type myloader_threads: int | None
    :param myloader_extra_args: Additional arguments for myloader.
    :type myloader_extra_args: RequiredStr | EmptyStrToNone
    :param skip_databases: Comma-separated string of databases to skip during restore.
    :type skip_databases: RequiredStr | EmptyStrToNone
    :param include_databases: Comma-separated string of databases to include in restore.
    :type include_databases: RequiredStr | EmptyStrToNone
    :param pre_script: Script to execute before restore.
    :type pre_script: RequiredStr | EmptyStrToNone
    :param post_script: Script to execute after restore.
    :type post_script: RequiredStr | EmptyStrToNone
    """

    backup_type: BackupType
    backup_source: RequiredStr
    local_path: RequiredStr | EmptyStrToNone = None
    overwrite_tables: bool = False
    myloader_threads: int | None = None
    myloader_extra_args: RequiredStr | EmptyStrToNone = None
    skip_databases: RequiredStr | EmptyStrToNone = None
    include_databases: RequiredStr | EmptyStrToNone = None
    pre_script: RequiredStr | EmptyStrToNone = None
    post_script: RequiredStr | EmptyStrToNone = None


class RestoreConfigServer(BaseRestoreConfigServer):
    """Server-specific restore configuration.

    Extends BaseRestoreConfigServer with additional required fields for alias, destination host, and port.

    :param alias: Unique identifier for the restore job.
    :type alias: RequiredStr
    :param dest_host: Destination host for the restore.
    :type dest_host: RequiredStr
    :param dest_port: Destination port for the restore.
    :type dest_port: int
    :param database: Target database name for restore.
    :type database: RequiredStr | EmptyStrToNone
    """

    alias: RequiredStr
    dest_host: RequiredStr
    dest_port: int
    database: RequiredStr | EmptyStrToNone = None


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

    :param task_name: Name of the restore task.
    :type task_name: RequiredStr
    :param service_id: Service identifier for the restore task.
    :type service_id: RequiredStr
    :param database: Target database name for restore.
    :type database: RequiredStr | EmptyStrToNone
    """

    task_name: RequiredStr
    service_id: RequiredStr
    database: RequiredStr | EmptyStrToNone = None
