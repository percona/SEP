"""Define models for the Archives plugin."""

from datetime import date
from enum import IntEnum
from typing import Self

from pydantic import Field, model_validator

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import RequiredStr


class SwapDropEnum(IntEnum):
    """Enum for defining types of swap actions for table data handling."""

    PURGE_ONLY = 0
    SWAP_DROP = 1
    SWAP_ARCHIVE_DROP = 2


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
    :type source_db_id: int | None
    :param source_table_id: The source table ID within the specified schema from which
        data will be purged. Must be None if source_query is set.
    :type source_table_id: int | None
    :param source_query: Optional; a query defining the source data to be purged.
        Must be None if both source_db_id and source_table_id are set.
    :type source_query: RequiredStr | None
    :param where: Optional; The WHERE condition that defines which data will be purged
        from the source table. Must be None when swap_drop is SWAP_DROP.
    :type where: RequiredStr | None
    :param dest_table_id: Optional; The destination table ID.
        Must be None if dest_file is set.
    :type dest_table_id: int | None
    :param dest_file: Optional; The destination file path.
        Must be None if dest_table_id is set.
    :type dest_file: RequiredStr | None
    :param swap_drop: Integer field (0-2) indicating the drop behavior.
        If 1, both dest_table_id and dest_file must be None.
    :type swap_drop: int
    :param swp_table_suffix: Optional; Date suffix for the swap table.
    :type swp_table_suffix: date | None
    :param use_index: Optional; The index to be used for optimizing the query.
    :type use_index: RequiredStr | None
    :param extra_args: Optional; Additional arguments for the archive task.
    :type extra_args: RequiredStr | None
    :param limit: Optional; The maximum number of records to be processed.
    :type limit: int | None
    :param sleep: Optional; Sleep duration between operations for rate limiting.
    :type sleep: int | None
    :param disable_binlog: Integer flag (0 or 1) to disable binary logging.
        Default is 0 (binary logging enabled).
    :type disable_binlog: int
    :param delete_data: Optional integer flag (0 or 1) to indicate data deletion.
        If set, dest_table and dest_file must not be set, and vice versa.
    :type delete_data: int | None
    :param anonymize: The bitmask for entities to be anonymized in logs.
    :type anonymize: int
    """

    alias: RequiredStr
    hostname: RequiredStr
    service_id: int
    source_db_id: int | None = None
    source_table_id: int | None = None
    source_query: RequiredStr | None = None
    where: RequiredStr | None = None
    dest_table_id: int | None = None
    dest_file: RequiredStr | None = None
    swap_drop: int = Field(..., ge=0, le=2)
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
    anonymize: int = 0

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
        :raises ValueError: If swap_drop is SWAP_DROP or delete_data is set, and either
            dest_file or dest_table_id is provided.
        :raises ValueError: If neither swap_drop nor delete_data is set, and
            neither dest_file nor dest_table_id is provided.
        """
        if dest_is_set := self.dest_table_id is not None or self.dest_file is not None:
            if (
                self.swap_drop == SwapDropEnum.SWAP_DROP or self.delete_data
            ) and dest_is_set:
                raise ValueError(
                    "When swap_drop is SWAP_DROP or delete_data is set, both dest_table_id and "
                    "dest_file must be None."
                )
        elif not self.delete_data and self.swap_drop != SwapDropEnum.SWAP_DROP:
            raise ValueError("At least one of dest_file or dest_table_id must be set.")

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
        """Validate source_query exclusivity with source_db_id and source_table_id.

        :return: The validated instance.
        :rtype: ArchivesCreate
        :raises ValueError: If source_query and source_db_id/source_table_id are both set,
            or if neither source_query nor both source_db_id and source_table_id are set.
        """
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
    :type source_db: RequiredStr | None
    :param source_table: The name of the source table within the specified schema.
    :type source_table: RequiredStr | None
    :param source_query: Optional; a query defining the source data to be purged.
    :type source_query: RequiredStr | None
    :param where: Optional; The WHERE condition that defines which data will be purged
        from the source table. Must be None when swap_drop is SWAP_DROP.
    :type where: RequiredStr | None
    :param dest_table: Optional; The name of the destination table where the purged data
        will be archived. Must be None if dest_file is set.
    :type dest_table: RequiredStr | None
    :param dest_file: Optional; The destination file path.
        Must be None if dest_table_id is set.
    :type dest_file: RequiredStr | None
    :param swp_table_suffix: Optional; Date suffix for the swap table.
    :type swap_drop: int
    :param swp_table_suffix: Optional; Date suffix for the swap table.
    :type swp_table_suffix: date | None
    :param use_index: Optional; The index to be used for optimizing the query.
    :type use_index: RequiredStr | None
    :param extra_args: Optional; Additional arguments for the archive task.
    :type extra_args: RequiredStr | None
    :param limit: Optional; The maximum number of records to be processed.
    :type limit: int | None
    :param sleep: Optional; Sleep duration between operations for rate limiting.
    :type sleep: int | None
    :param disable_binlog: Integer flag (0 or 1) to disable binary logging.
        Default is 0 (binary logging enabled).
    :type disable_binlog: int
    :param delete_data: Optional integer flag (0 or 1) to indicate data deletion.
        If set, dest_table and dest_file must not be set, and vice versa.
    :type delete_data: int | None
    """

    alias: RequiredStr
    source_db: RequiredStr | None = None
    source_table: RequiredStr | None = None
    source_query: RequiredStr | None = None
    where: RequiredStr | None = None
    dest_table: RequiredStr | None = None
    dest_file: RequiredStr | None = None
    swap_drop: int = Field(..., ge=0, le=2)
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
