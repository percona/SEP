"""Define models for the Archives plugin."""

from datetime import date
from typing import Self

from pydantic import Field, model_validator

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import RequiredStr


class ArchivesCreate(BaseCaseInsensitiveModel):
    """Represent an Archives creation form with proper case-insensitive fields.

    :param alias: The alias name for the task being created. This name is used for
        identifying the task in the backend.
    :type alias: RequiredStr
    :param hostname: The source hostname where the task will be executed.
    :type hostname: RequiredStr
    :param service_id: The Inventory ID of the database service to connect to.
    :type service_id: int
    :param source_db_id: The source database schema ID from which data will be purged.
        Must be None if source_query is set.
    :type source_db_id: Optional[int]
    :param source_table_id: The source table ID within the specified schema from which
        data will be purged. Must be None if source_query is set.
    :type source_table_id: Optional[int]
    :param source_query: Optional; a query defining the source data to be purged.
        Must be None if both source_db_id and source_table_id are set.
    :type source_query: Optional[RequiredStr]
    :param where: The WHERE condition that defines which data will be purged from
        the source table.
    :type where: RequiredStr
    :param dest_table_id: Optional; The destination table ID.
        Must be None if dest_file is set.
    :type dest_table_id: Optional[int]
    :param dest_file: Optional; The destination file path.
        Must be None if dest_table_id is set.
    :type dest_file: Optional[RequiredStr]
    :param swap_drop: Integer field (0-2) indicating the drop behavior.
        If 1, both dest_table_id and dest_file must be None.
    :type swap_drop: int
    :param swp_table_suffix: Optional; Date suffix for the swap table.
    :type swp_table_suffix: Optional[date]
    :param use_index: Optional; The index to be used for optimizing the query.
    :type use_index: Optional[RequiredStr]
    :param extra_args: Optional; Additional arguments for the archive task.
    :type extra_args: Optional[RequiredStr]
    :param limit: Optional; The maximum number of records to be processed.
    :type limit: Optional[int]
    :param sleep: Optional; Sleep duration between operations for rate limiting.
    :type sleep: Optional[int]
    :param disable_binlog: Integer flag (0 or 1) to disable binary logging.
    Default is 0 (binary logging enabled).
    :type disable_binlog: int
    :param delete_data: Optional integer flag (0 or 1) to indicate data deletion.
        If set, dest_table and dest_file must not be set, and vice versa.
    :type delete_data: Optional[int]
    """

    alias: RequiredStr
    hostname: RequiredStr
    service_id: int
    source_db_id: int | None = None
    source_table_id: int | None = None
    source_query: RequiredStr | None = None
    where: RequiredStr
    dest_table_id: int | None = None
    dest_file: RequiredStr | None = None
    swap_drop: int = Field(..., ge=0, le=2, description="Must be between 0 and 2.")
    swp_table_suffix: date | None = None
    use_index: RequiredStr | None = None
    extra_args: RequiredStr | None = None
    limit: int | None = None
    sleep: int | None = None
    disable_binlog: int | None = Field(
        None, ge=0, le=1, description="Optional flag to disable binary logging."
    )
    delete_data: int | None = Field(
        None, ge=0, le=1, description="Optional flag to delete data."
    )

    @model_validator(mode="after")
    def validate_tables_are_different(self) -> Self:
        """Validate that the source_table_id and dest_table_id are not the same.

        :return: The validated instance
        :rtype: ArchivesCreate
        :raises ValueError: If the source_table_id is the same as the dest_table_id.
        """
        if (
            self.source_table_id == self.dest_table_id
            and self.dest_table_id is not None
        ):
            raise ValueError("Source and Destination tables cannot be the same.")
        return self

    @model_validator(mode="after")
    def validate_dest_file_or_dest_table_id(self) -> Self:
        """Validate that exactly one of dest_file or dest_table_id is set.

        :return: The validated instance
        :rtype: ArchivesCreate
        :raises ValueError: If both dest_file and dest_table_id are set or both are None.
        """
        if self.swap_drop == 1:
            if self.dest_table_id is not None or self.dest_file is not None:
                raise ValueError(
                    "When swap_drop is 1, both dest_table_id and dest_file must be None."
                )
        elif self.delete_data is not None:
            if self.dest_table_id is not None or self.dest_file is not None:
                raise ValueError(
                    "When delete_data is set, dest_table and dest_file must not be set."
                )
        elif (self.dest_file is not None) == (self.dest_table_id is not None):
            raise ValueError("Exactly one of dest_file or dest_table_id must be set.")

        return self

    @model_validator(mode="after")
    def validate_swp_table_suffix(self) -> Self:
        """Validate that swp_table_suffix is set if swap_drop is 2."""
        if self.swap_drop == 2 and self.swp_table_suffix is None:  # noqa: PLR2004
            raise ValueError("swp_table_suffix must be provided when swap_drop is 2.")
        return self

    @model_validator(mode="after")
    def validate_source_query_exclusivity(self) -> Self:
        """Validate that source_query is mutually exclusive with source_db_id and source_table_id."""
        if self.source_query is not None:
            if self.source_db_id is not None or self.source_table_id is not None:
                raise ValueError(
                    "source_query is set, so source_db_id and source_table_id must be None."
                )
        elif self.source_db_id is None or self.source_table_id is None:
            raise ValueError(
                "When source_query is not set, both source_db_id and source_table_id must be provided."
            )
        return self


class PurgeConfigAll(BaseCaseInsensitiveModel):
    """Represents the general configuration for the archive task.

    :param source_host: The hostname or IP address of the source where the data will
        be archived from.
    :type source_host: RequiredStr
    :param source_port: The port number used to connect to the source host.
    :type source_port: int
    """

    source_host: RequiredStr
    source_port: int


class PurgeConfigItem(BaseCaseInsensitiveModel):
    """Represents an individual purge configuration item.

    :param alias: A unique alias for the task being created, identifying it
        within the system.
    :type alias: RequiredStr
    :param source_db: The name of the source database schema from which the data
        will be archived.
    :type source_db: Optional[RequiredStr]
    :param source_table: The name of the source table within the specified schema.
    :type source_table: Optional[RequiredStr]
    :param source_query: Optional; a query defining the source data to be purged.
    :type source_query: Optional[RequiredStr]
    :param where: A WHERE condition that determines which data will be purged
        from the source table.
    :type where: RequiredStr
    :param dest_table: The name of the destination table where the purged data
        will be archived.
    :type dest_table: RequiredStr
    :param swp_table_suffix: Optional; Date suffix for the swap table.
    :type swp_table_suffix: Optional[date]
    :param use_index: Optional; The index to be used for optimizing the query.
    :type use_index: Optional[RequiredStr]
    :param extra_args: Optional; Additional arguments for the archive task.
    :type extra_args: Optional[RequiredStr]
    :param limit: Optional; The maximum number of records to be processed.
    :type limit: Optional[int]
    :param sleep: Optional; Sleep duration between operations for rate limiting.
    :type sleep: Optional[int]
    :param disable_binlog: Integer flag (0 or 1) to disable binary logging.
        Default is 0 (binary logging enabled).
    :type disable_binlog: int
    :param delete_data: Optional integer flag (0 or 1) to indicate data deletion.
        If set, dest_table and dest_file must not be set, and vice versa.
    :type delete_data: Optional[int]
    """

    alias: RequiredStr
    source_db: RequiredStr | None = None
    source_table: RequiredStr | None = None
    source_query: RequiredStr | None = None
    where: RequiredStr
    dest_table: RequiredStr | None = None
    dest_file: RequiredStr | None = None
    swap_drop: int = Field(..., ge=0, le=2, description="Must be between 0 and 2.")
    swp_table_suffix: date | None = None
    use_index: RequiredStr | None = None
    extra_args: RequiredStr | None = None
    limit: int | None = None
    sleep: int | None = None
    disable_binlog: int | None = Field(
        None,
        ge=0,
        le=1,
        description="Optional flag to disable binary logging; set to 0 or 1",
    )
    delete_data: int | None = Field(
        None, ge=0, le=1, description="Optional flag to delete data."
    )


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
