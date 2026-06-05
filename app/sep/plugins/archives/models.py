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

from datetime import date
from enum import IntEnum
from typing import Annotated, Self

from pydantic import Field, field_validator, model_validator

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import EmptyStrToNone, NonEmptyStr


class SwapDropEnum(IntEnum):
    """Enum for defining types of swap actions for table data handling."""

    PURGE_ONLY = 0
    SWAP_DROP = 1
    SWAP_ARCHIVE_DROP = 2


class ArchivesCreate(BaseCaseInsensitiveModel):
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
    :param delete_data: Optional integer flag (0 or 1). When set to 1, source
        rows are deleted without being written to any destination; the
        destination table/file fields (dest_table_id, dest_table_name,
        dest_file) must not be set, and vice versa.
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
        None,
        ge=0,
        le=1,
        title="Delete Without Archiving",
        description=(
            "Delete source rows without writing them to any destination; "
            "the destination table/file fields must be left unset."
        ),
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

    @model_validator(mode="after")
    def validate_tables_are_different(self) -> Self:
        """Validate that the source and destination tables are not the same.

        For the manual-source path the destination is the *same* table only
        when its host, schema, and table name all resolve to the source. An
        absent, empty, or whitespace-only destination host or schema falls back
        to the source at execution time (see
        ``deps._resolve_destination_host_and_db`` and the payload script), so a
        populated-but-differing
        ``dest_service_id``/``dest_host``/``dest_db_id``/``dest_db_name`` marks
        a distinct table and is accepted.

        :return: The validated instance
        :rtype: ArchivesCreate
        :raises ValueError: If the source and destination tables are the same.
        """
        if self.source_table_id is not None and self.dest_table_id is not None:
            if self.source_table_id == self.dest_table_id:
                raise ValueError("Source and Destination tables cannot be the same.")
        elif (
            (source_table := self.source_table_name.rstrip())
            and (dest_table := self.dest_table_name.rstrip())
            and (source_db := self.source_db_name.rstrip())
            and source_table == dest_table
            # Destination host resolves to the source host. An absent or
            # whitespace-only ``dest_host`` is stripped to empty by the runtime
            # resolver and falls back to the source, so it counts as the source
            # host here too -- mirroring the strip-aware presence test in
            # ``validate_dest_host_exclusivity``.
            and (
                (
                    self.dest_service_id is None
                    and not (self.dest_host and self.dest_host.strip())
                )
                or self.dest_service_id == self.service_id
            )
            # Destination schema resolves to the source schema. The resolver
            # rstrips ``dest_db_name``, so a whitespace-only value also falls
            # back to the source schema.
            and (
                (dest_db := self.dest_db_name.rstrip()) == source_db
                or (self.dest_db_id is None and not dest_db)
            )
        ):
            raise ValueError("Source and Destination tables cannot be the same.")
        return self

    @model_validator(mode="after")
    def validate_dest_file_or_dest_table_id(self) -> Self:
        """Validate that exactly one of dest_file or dest_table_id/dest_table_name is set.

        :return: The validated instance
        :rtype: ArchivesCreate
        :raises ValueError: If swap_drop is SWAP_DROP or delete_data is set, and either
            dest_file or dest_table_id/dest_table_name is provided.
        :raises ValueError: If neither swap_drop nor delete_data is set, and
            neither dest_file nor dest_table_id/dest_table_name is provided.
        """
        has_dest_table = self.dest_table_id is not None or bool(
            self.dest_table_name.rstrip()
        )
        if dest_is_set := has_dest_table or self.dest_file is not None:
            if (
                self.swap_drop == SwapDropEnum.SWAP_DROP or self.delete_data
            ) and dest_is_set:
                raise ValueError(
                    "When swap_drop is SWAP_DROP or delete_data is set, both dest_table_id/dest_table_name and "
                    "dest_file must be None/empty."
                )
        elif not self.delete_data and self.swap_drop != SwapDropEnum.SWAP_DROP:
            raise ValueError(
                "At least one of dest_file or dest_table_id/dest_table_name must be set."
            )

        if self.dest_table_id is not None and bool(self.dest_table_name.rstrip()):
            raise ValueError(
                "Cannot use both dest_table_id and dest_table_name at the same time."
            )

        return self

    @model_validator(mode="after")
    def validate_dest_host_exclusivity(self) -> Self:
        """Validate destination host/db field exclusivity and compatibility.

        :return: The validated instance
        :rtype: ArchivesCreate
        :raises ValueError: If dest_service_id and dest_host are both set, or if
            dest_db_id and dest_db_name are both set, or if dest_db_id is set
            without dest_service_id, or if destination fields are set with
            SWAP_ARCHIVE_DROP (swap_drop=2).
        """
        has_dest_service = self.dest_service_id is not None
        has_dest_host = bool(self.dest_host and self.dest_host.strip())
        has_dest_db_id = self.dest_db_id is not None
        has_dest_db_name = bool(self.dest_db_name.rstrip())

        if has_dest_service and has_dest_host:
            raise ValueError(
                "Cannot use both dest_service_id (inventory) and dest_host (manual input) at the same time."
            )

        if has_dest_db_id and has_dest_db_name:
            raise ValueError(
                "Cannot use both dest_db_id (inventory) and dest_db_name (manual input) at the same time."
            )

        if has_dest_db_id and not has_dest_service:
            raise ValueError(
                "dest_db_id requires dest_service_id to be set (cannot pick inventory schema with manual host)."
            )

        if self.swap_drop == SwapDropEnum.SWAP_ARCHIVE_DROP and (
            has_dest_service or has_dest_host
        ):
            raise ValueError(
                "Cannot set destination host when swap_drop is SWAP_ARCHIVE_DROP (2) "
                "(cross-host table swapping is not supported)."
            )

        return self

    @model_validator(mode="after")
    def validate_swp_table_suffix(self) -> Self:
        """Validate that swp_table_suffix is set if swap_drop is 2.

        :return: The validated instance.
        :rtype: ArchivesCreate
        :raises ValueError: If swap_drop is 2 but swp_table_suffix is not provided.
        """
        if (
            self.swap_drop == SwapDropEnum.SWAP_ARCHIVE_DROP
            and self.swp_table_suffix is None
        ):
            raise ValueError("swp_table_suffix must be provided when swap_drop is 2.")
        return self

    @model_validator(mode="after")
    def validate_source_query_exclusivity(self) -> Self:
        """Validate source_query exclusivity with source_db_id/source_table_id or source_db_name/source_table_name.

        :return: The validated instance.
        :rtype: ArchivesCreate
        :raises ValueError: If source_query and source_db_id/source_table_id or source_db_name/source_table_name are both set,
            or if neither source_query nor both source_db_id and source_table_id (or source_db_name and source_table_name) are set.
        """
        if self.source_query is not None:
            if (
                self.source_db_id is not None
                or self.source_table_id is not None
                or bool(self.source_db_name.rstrip())
                or bool(self.source_table_name.rstrip())
            ):
                raise ValueError(
                    "source_query is set, so source_db_id/source_table_id and source_db_name/source_table_name must be None/empty."
                )
        else:
            has_ids = self.source_db_id is not None and self.source_table_id is not None
            has_typed_names = bool(self.source_db_name.rstrip()) and bool(
                self.source_table_name.rstrip()
            )

            if not has_ids and not has_typed_names:
                raise ValueError(
                    "When source_query is not set, either both source_db_id and source_table_id, "
                    "or both source_db_name and source_table_name must be provided."
                )
            if has_ids and has_typed_names:
                raise ValueError(
                    "Cannot use both source_db_id/source_table_id and source_db_name/source_table_name at the same time."
                )
        return self

    @model_validator(mode="after")
    def validate_where_based_on_swap_drop(self) -> Self:
        """Validate that 'where' is set or unset based on the value of swap_drop.

        :return: The validated instance.
        :rtype: ArchivesCreate
        :raises ValueError: If swap_drop is SWAP_DROP and where is set,
            or if swap_drop is not SWAP_DROP and where is None.
        """
        if self.swap_drop == SwapDropEnum.SWAP_DROP and self.where is not None:
            raise ValueError("When swap_drop is SWAP_DROP, 'where' must be None.")
        if self.swap_drop != SwapDropEnum.SWAP_DROP and self.where is None:
            raise ValueError("When swap_drop is not SWAP_DROP, 'where' must be set.")

        return self


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
    :param swap_drop: Integer field (0-2) indicating the swap/drop behavior.
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
    :param delete_data: Optional integer flag (0 or 1). When set to 1, source
        rows are deleted without being written to any destination; dest_table
        and dest_file must not be set, and vice versa.
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
        None,
        ge=0,
        le=1,
        title="Delete Without Archiving",
        description=(
            "Delete source rows without writing them to any destination; "
            "the destination table/file fields must be left unset."
        ),
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
