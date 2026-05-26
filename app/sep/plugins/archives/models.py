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

"""Define models for the Archives plugin."""

from datetime import date, datetime
from enum import IntEnum
from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import EmptyStrToNone, NonEmptyStr
from app.inventory.models import ServiceTypeEnum
from app.sep.plugins.archives.schema import archives_schema
from app.sep.plugins.framework import ConnectivityWarning
from app.sep.plugins.framework.rules import (
    apply_conditional_rules,
    ConditionalRulesModel,
)
from app.tasks.models import TaskBackendEnum, TaskHistoryStatusEnum, TaskOwner


class SwapDropEnum(IntEnum):
    """Enum for defining types of swap actions for table data handling."""

    PURGE_ONLY = 0
    SWAP_DROP = 1
    SWAP_ARCHIVE_DROP = 2


@apply_conditional_rules(archives_schema)
class ArchivesCreate(ConditionalRulesModel, BaseCaseInsensitiveModel):
    """Represent an Archives creation form with proper case-insensitive fields.

    :param alias: The alias name for the task being created. This name is used for
        identifying the task in the backend.
    :type alias: NonEmptyStr
    :param hostname: The source hostname where the task will be executed.
    :type hostname: NonEmptyStr
    :param service_id: The Inventory ID of the database service to connect to.
    :type service_id: int
    :param source_db_id: The source database schema ID from which data will be purged.
        Must be None if source_query is set.
    :type source_db_id: int | EmptyStrToNone
    :param source_db_name: The name of the source database schema.
    :type source_db_name: str
    :param source_table_id: The source table ID within the specified schema from which
        data will be purged. Must be None if source_query is set.
    :type source_table_id: int | EmptyStrToNone
    :param source_table_name: The name of the source table.
    :type source_table_name: str
    :param source_query: Optional; a query defining the source data to be purged.
        Must be None if both source_db_id and source_table_id are set.
    :type source_query: NonEmptyStr | None
    :param where: Optional; The WHERE condition that defines which data will be purged
        from the source table. Must be None when swap_drop is SWAP_DROP.
    :type where: NonEmptyStr | None
    :param dest_table_id: Optional; The destination table ID.
        Must be None if dest_file is set.
    :type dest_table_id: int | EmptyStrToNone
    :param dest_table_name: The name of the destination table.
    :type dest_table_name: str
    :param dest_file: Optional; The destination file path.
        Must be None if dest_table_id is set.
    :type dest_file: NonEmptyStr | None
    :param swap_drop: Integer field (0-2) indicating the drop behavior.
        If 1, both dest_table_id and dest_file must be None.
    :type swap_drop: int
    :param swp_table_suffix: Optional; Date suffix for the swap table.
    :type swp_table_suffix: date | None
    :param use_index: Optional; The index to be used for optimizing the query.
    :type use_index: NonEmptyStr | None
    :param extra_args: Optional; Additional arguments for the archive task.
    :type extra_args: NonEmptyStr | None
    :param limit: Optional; The maximum number of records to be processed.
    :type limit: int | EmptyStrToNone
    :param sleep: Optional; Sleep duration between operations for rate limiting.
    :type sleep: int | EmptyStrToNone
    :param disable_binlog: Optional integer flag (0 or 1) to disable binary logging.
        ``None`` means the checkbox was left unset (binary logging stays enabled).
    :type disable_binlog: int | None
    :param disable_bulk_insert: Optional integer flag (0 or 1) to disable bulk
        insert. ``None`` means the checkbox was left unset / default behavior is
        used; 0 means bulk insert remains enabled, and 1 means bulk insert is
        disabled.
    :type disable_bulk_insert: int | None
    :param delete_data: Optional integer flag (0 or 1) to indicate data deletion.
        If set, dest_table and dest_file must not be set, and vice versa.
    :type delete_data: int | None
    :param dest_service_id: Optional; The Inventory ID of the destination database service.
    :type dest_service_id: int | EmptyStrToNone
    :param dest_host: Optional; The hostname of the destination database.
    :type dest_host: str | None
    :param dest_port: Optional; The port of the destination database (1-65535).
        The ``ge``/``le`` range constraint is scoped to the ``int`` arm so it
        does not run against ``None`` when ``EmptyStrToNone`` coerces an empty
        form input.
    :type dest_port: Annotated[int, Field(ge=1, le=65535)] | EmptyStrToNone
    :param dest_db_id: Optional; The destination database schema ID.
    :type dest_db_id: int | EmptyStrToNone
    :param dest_db_name: The name of the destination database schema.
    :type dest_db_name: str
    :param alert_on_fail: If True, send an alert if the task fails. Defaults to False.
    :type alert_on_fail: bool
    """

    alias: NonEmptyStr
    hostname: NonEmptyStr
    service_id: int
    source_db_id: int | EmptyStrToNone = None
    source_db_name: str = ""
    source_table_id: int | EmptyStrToNone = None
    source_table_name: str = ""
    source_query: NonEmptyStr | None = None
    where: NonEmptyStr | None = None
    dest_table_id: int | EmptyStrToNone = None
    dest_table_name: str = ""
    dest_file: NonEmptyStr | None = None
    swap_drop: int = Field(..., ge=0, le=2)
    swp_table_suffix: date | None = None
    use_index: NonEmptyStr | None = None
    extra_args: NonEmptyStr | None = None
    limit: int | EmptyStrToNone = None
    sleep: int | EmptyStrToNone = None
    disable_binlog: int | None = Field(
        None, ge=0, le=1, description="Optional flag to disable binary logging."
    )
    disable_bulk_insert: int | None = Field(
        None, ge=0, le=1, description="Optional flag to disable bulk insert."
    )
    delete_data: int | None = Field(
        None, ge=0, le=1, description="Optional flag to delete data."
    )
    dest_service_id: int | EmptyStrToNone = None
    dest_host: str | None = None
    dest_port: Annotated[int, Field(ge=1, le=65535)] | EmptyStrToNone = None
    dest_db_id: int | EmptyStrToNone = None
    dest_db_name: str = ""
    alert_on_fail: bool = False

    @field_validator("dest_host", "dest_db_name")
    @classmethod
    def validate_no_dsn_delimiters(cls, v: str | None) -> str | None:
        """Validate that destination fields do not contain DSN delimiters.

        Prevents pt-archiver DSN injection by rejecting commas and equals signs
        which could split or modify the DSN key=value pairs. Applied to both
        ``dest_host`` and ``dest_db_name`` fields.

        :param v: The field value to validate.
        :type v: str | None
        :return: The validated value if no delimiters are present.
        :rtype: str | None
        :raises ValueError: If the value contains ``,`` or ``=`` characters.
        """
        if v and ("," in v or "=" in v):
            raise ValueError(
                "Values cannot contain ',' or '=' characters (DSN delimiters)."
            )
        return v


class PurgeConfigAll(BaseCaseInsensitiveModel):
    """Represents the general configuration for the archive task.

    :param source_host: The hostname or IP address of the source where the data will
        be archived from.
    :type source_host: NonEmptyStr
    :param source_port: The port number used to connect to the source host.
    :type source_port: int
    """

    source_host: NonEmptyStr
    source_port: int


class PurgeConfigItem(BaseCaseInsensitiveModel):
    """Represents an individual purge configuration item.

    :param alias: A unique alias for the task being created, identifying it
        within the system.
    :type alias: NonEmptyStr
    :param source_db: The name of the source database schema from which the data
        will be archived.
    :type source_db: NonEmptyStr | None
    :param source_table: The name of the source table within the specified schema.
    :type source_table: NonEmptyStr | None
    :param source_query: Optional; a query defining the source data to be purged.
    :type source_query: NonEmptyStr | None
    :param where: Optional; The WHERE condition that defines which data will be purged
        from the source table. Must be None when swap_drop is SWAP_DROP.
    :type where: NonEmptyStr | None
    :param dest_table: Optional; The name of the destination table where the purged data
        will be archived. Must be None if dest_file is set.
    :type dest_table: NonEmptyStr | None
    :param dest_file: Optional; The destination file path.
        Must be None if dest_table_id is set.
    :type dest_file: NonEmptyStr | None
    :param swp_table_suffix: Optional; Date suffix for the swap table.
    :type swap_drop: int
    :param swp_table_suffix: Optional; Date suffix for the swap table.
    :type swp_table_suffix: date | None
    :param use_index: Optional; The index to be used for optimizing the query.
    :type use_index: NonEmptyStr | None
    :param extra_args: Optional; Additional arguments for the archive task.
    :type extra_args: NonEmptyStr | None
    :param limit: Optional; The maximum number of records to be processed.
    :type limit: int | None
    :param sleep: Optional; Sleep duration between operations for rate limiting.
    :type sleep: int | None
    :param disable_binlog: Optional integer flag (0 or 1) to disable binary logging.
        ``None`` means the checkbox was left unset (binary logging stays enabled).
    :type disable_binlog: int | None
    :param disable_bulk_insert: Optional integer flag (0 or 1) to disable bulk
        insert. If ``None``, the setting is left unset so existing/default behavior is
        preserved.
    :type disable_bulk_insert: int | None
    :param delete_data: Optional integer flag (0 or 1) to indicate data deletion.
        If set, dest_table and dest_file must not be set, and vice versa.
    :type delete_data: int | None
    :param dest_host: Optional; The destination host address.
    :type dest_host: NonEmptyStr | None
    :param dest_port: Optional; The destination port number.
    :type dest_port: int | None
    :param dest_db: Optional; The destination database schema name.
    :type dest_db: NonEmptyStr | None
    """

    alias: NonEmptyStr
    source_db: NonEmptyStr | None = None
    source_table: NonEmptyStr | None = None
    source_query: NonEmptyStr | None = None
    where: NonEmptyStr | None = None
    dest_table: NonEmptyStr | None = None
    dest_file: NonEmptyStr | None = None
    swap_drop: int = Field(..., ge=0, le=2)
    swp_table_suffix: date | None = None
    use_index: NonEmptyStr | None = None
    extra_args: NonEmptyStr | None = None
    limit: int | None = None
    sleep: int | None = None
    disable_binlog: int | None = Field(
        None,
        ge=0,
        le=1,
        description="Optional flag to disable binary logging; set to 0 or 1",
    )
    disable_bulk_insert: int | None = Field(
        None,
        ge=0,
        le=1,
        description="Optional flag to disable bulk insert; set to 0 or 1",
    )
    delete_data: int | None = Field(
        None, ge=0, le=1, description="Optional flag to delete data."
    )
    dest_host: NonEmptyStr | None = None
    dest_port: int | None = None
    dest_db: NonEmptyStr | None = None


class PurgeConfig(BaseCaseInsensitiveModel):
    """Represents the overall purge configuration.

    :param all: General settings for the purge, including source host and port
        information.
    :type all: PurgeConfigAll
    :param purge_list: A list of purge configuration items specifying individual
        archive tasks.
    :type purge_list: list[PurgeConfigItem]
    """

    all: PurgeConfigAll
    purge_list: list[PurgeConfigItem]


class ArchivesTaskResponse(BaseModel):
    """Represent an Archives task in API responses.

    Lean Pydantic projection of ``app.tasks.models.Task`` carrying only the
    fields the React frontend consumes. Defined locally (not inherited from
    ``Task``) to keep relationship attributes (``history``) out of the
    serialised payload.

    :param id: The task primary key.
    :type id: int | None
    :param name: The task name.
    :type name: str
    :param backend: The execution backend.
    :type backend: TaskBackendEnum
    :param owner: The plugin that owns the task.
    :type owner: TaskOwner
    :param data: Raw task data (``task``/``meta``/``payload``).
    :type data: dict[str, Any]
    :param is_template: Whether the task is a template definition.
    :type is_template: bool
    :param protected: Whether the task is protected from deletion.
    :type protected: bool
    :param alert_on_fail: Whether the task triggers an alert on failure.
    :type alert_on_fail: bool
    :param created_at: Creation timestamp.
    :type created_at: datetime | None
    :param updated_at: Last update timestamp.
    :type updated_at: datetime | None
    :param created_by: User that created the task.
    :type created_by: str | None
    :param last_updated_by: User that last updated the task.
    :type last_updated_by: str | None
    :param service_type: The database service type the task targets.
    :type service_type: ServiceTypeEnum | None
    :param status: The latest known execution status from task history.
    :type status: TaskHistoryStatusEnum | None
    """

    id: int | None = None
    name: str
    backend: TaskBackendEnum
    owner: TaskOwner
    data: dict[str, Any]
    is_template: bool = False
    protected: bool = False
    alert_on_fail: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: str | None = None
    last_updated_by: str | None = None
    service_type: ServiceTypeEnum | None = None
    status: TaskHistoryStatusEnum | None = None


class ArchivesCreateResponse(ArchivesTaskResponse):
    """Represent the response body for ``POST /api/plugins/archives/``.

    Extends :class:`ArchivesTaskResponse` with a connectivity-warning field
    surfaced when the post-creation database probe fails or is skipped.

    :param connectivity_warning: ``None`` when the probe passes, was opted
        out, or the task meta lacks connectivity keys; populated otherwise.
    :type connectivity_warning: ConnectivityWarning | None
    """

    connectivity_warning: ConnectivityWarning | None = None
