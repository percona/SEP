"""Define models for the Archives plugin."""

from typing import Optional, Self

from pydantic import model_validator

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
    :type source_db_id: int
    :param source_table_id: The source table ID within the specified schema from which
        data will be purged.
    :type source_table_id: int
    :param where: The WHERE condition that defines which data will be purged from
        the source table.
    :type where: RequiredStr
    :param dest_table_id: The destination table ID where purged data can be archived.
    :type dest_table_id: int
    """

    alias: RequiredStr
    hostname: RequiredStr
    service_id: int
    source_db_id: int
    source_table_id: int
    where: RequiredStr
    dest_table_id: int

    @model_validator(mode="after")
    def validate_tables_are_different(self) -> Self:
        """Validate that the source_table_id and dest_table_id are not the same.

        :return: The validated instance
        :rtype: ArchivesCreate
        :raises ValueError: If the source_table_id is the same as the dest_table_id.
        """
        if self.source_table_id == self.dest_table_id:
            raise ValueError("Source and Destination tables cannot be the same.")
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
    :type source_db: RequiredStr
    :param source_table: The name of the source table within the specified schema.
    :type source_table: RequiredStr
    :param where: A WHERE condition that determines which data will be purged
        from the source table.
    :type where: RequiredStr
    :param dest_table: The name of the destination table where the purged data
        will be archived.
    :type dest_table: RequiredStr
    """

    alias: RequiredStr
    source_db: RequiredStr
    source_table: RequiredStr
    where: RequiredStr
    dest_table: Optional[RequiredStr] = None
    dest_file: Optional[RequiredStr] = None

    @model_validator(mode='after')
    def check_dest_fields(cls, data):
        if (data.dest_table is None) == (data.dest_file is None):
            raise ValueError('Exactly one of dest_table or dest_file must be set.')
        return data


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
