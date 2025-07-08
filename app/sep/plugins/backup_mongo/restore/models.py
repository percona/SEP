"""Define models for the Restore plugin."""

from enum import StrEnum

from pydantic import Field

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import EmptyStrToNone, EnumFieldMixin, RequiredStr
from app.sep.plugins.backup_mongo.models import BackupType


class S3Tool(EnumFieldMixin, StrEnum):
    """Allowed tools to interact with S3-compatible services."""

    S3CMD = "s3cmd"
    AWSCLI = "awscli"

class RestoreConfig(BaseCaseInsensitiveModel):
    """Define the complete configuration for a restore operation.

    :param logging_dir: Directory path for storing restore operation logs.
    :type logging_dir: RequiredStr | EmptyStrToNone
    :param port: Port number for the restore operation.
    :type port: int | None
    :param custom_mongod_init_command: Custom MySQL initialization command.
    :type custom_mongod_init_command: RequiredStr | EmptyStrToNone
    :param ssh_user: SSH username for remote operations (default: "percona").
    :type ssh_user: RequiredStr | EmptyStrToNone
    :param ssh_port: SSH port for remote operations (default: 22).
    :type ssh_port: int | EmptyStrToNone
    :param ssh_key: SSH key name for authentication (not full path).
    :type ssh_key: RequiredStr | EmptyStrToNone
    :param s3_tool: Tool to use for S3 operations (default: S3CMD).
    :type s3_tool: S3Tool
    """

    logging_dir: RequiredStr | EmptyStrToNone = None
    port: int | None = None
    custom_mongod_init_command: RequiredStr | EmptyStrToNone = None

    # SSH Options
    ssh_user: RequiredStr | EmptyStrToNone = Field(default="percona")
    ssh_port: int | EmptyStrToNone = Field(default=22)
    ssh_key: RequiredStr | EmptyStrToNone = None  # only key name, not full path

    # S3 tool selection (default is awscli)
    s3_tool: S3Tool = S3Tool.AWSCLI
    backup_name: RequiredStr | EmptyStrToNone = None
    backup_type: BackupType
    pitr: RequiredStr | EmptyStrToNone = None
    local_dbpath: RequiredStr | EmptyStrToNone = None
    overwrite_datadir: bool = False
    pbm_extra_args: RequiredStr | EmptyStrToNone = None
    pre_script: RequiredStr | EmptyStrToNone = None
    post_script: RequiredStr | EmptyStrToNone = None


class RestoreCreate(RestoreConfig):
    """Model for creating a restore task.

    Inherits from RestoreConfigAll and BaseRestoreConfigServer, adding task and service identifiers.

    :param hostname: The hostname of the machine to back up.
    :type hostname: RequiredStr
    :param task_name: Name of the restore task.
    :type task_name: RequiredStr
    :param service_id: Service identifier for the restore task.
    :type service_id: RequiredStr
    :param schema_id: Schema identifier  for restore.
    :type schema_id: RequiredStr | EmptyStrToNone
    """

    hostname: RequiredStr
    task_name: RequiredStr
    service_id: RequiredStr
    schema_id: RequiredStr | EmptyStrToNone = None