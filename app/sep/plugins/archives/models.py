"""Define models for the Archives plugin."""

from app.core.config import BaseCaseInsensitiveModel
from app.core.fields import RequiredStr


class ArchivesCreate(BaseCaseInsensitiveModel):
    """Represent an Archives creation form with proper case-insensitive fields.

    :param alias: The alias name for the task being created. This name is used for
        identifying the task in the backend.
    :type alias: RequiredStr
    :param hostname: The source hostname where the task will be executed.
    :type hostname: RequiredStr
    :param connect_to: The connection type, which could be a hostname or `localhost`.
    :type connect_to: RequiredStr
    :param source_db: The source database schema from which data will be purged.
    :type source_db: RequiredStr
    :param source_table: The source table within the specified schema from which
        data will be purged.
    :type source_table: RequiredStr
    :param where: The WHERE condition that defines which data will be purged from
        the source table.
    :type where: RequiredStr
    :param dest_table: The destination table where purged data can be archived.
    :type dest_table: RequiredStr
    """

    alias: RequiredStr
    hostname: RequiredStr
    connect_to: RequiredStr
    source_db: RequiredStr
    source_table: RequiredStr
    where: RequiredStr
    dest_table: RequiredStr


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
    dest_table: RequiredStr


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
