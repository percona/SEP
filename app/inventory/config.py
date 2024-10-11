"""Define settings for the Inventory API."""

from typing import ClassVar

from app.core.config import BaseYamlExtraSettings
from app.core.db.config import DatabaseOptions


class InventorySettings(BaseYamlExtraSettings):
    """Settings for the Inventory API.

    Attributes
    ----------
    SETTINGS_PREFIXES : ClassVar[tuple[str]]
        The prefixes for task-related settings in the configuration file.
    UVICORN_PORT : int
        The port to be used by Uvicorn for running the server. Defaults to 8001.
    DATABASE : DatabaseOptions
        The database configuration options.
        Defaults to an SQLite database with the name 'inventory.db'.

    """

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["INVENTORY"]
    UVICORN_PORT: int = 8001
    DATABASE: DatabaseOptions = DatabaseOptions(NAME="inventory.db")


inventory_settings = InventorySettings()
