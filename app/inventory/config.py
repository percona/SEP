"""Define settings for the Inventory API."""

from typing import ClassVar

from app.core.config import BaseYamlAppSettings
from app.core.db.config import DatabaseOptions
from app.core.middleware.security_headers import SecurityHeadersOptions


class InventorySettings(BaseYamlAppSettings):
    """Settings for the Inventory API.

    :cvar SETTINGS_PREFIXES: The prefixes for task-related settings in the
        configuration file. Set to ["INVENTORY"].
    :vartype SETTINGS_PREFIXES: ClassVar[list[str]]
    :param UVICORN_PORT: The port to be used by Uvicorn for running the server.
        Defaults to 8001.
    :type UVICORN_PORT: int
    :param DATABASE: The database configuration options. Defaults to an SQLite database
        with the name "inventory.db".
    :type DATABASE: DatabaseOptions
    :param SECURITY_HEADERS: Specific options for the SecurityHeadersMiddleware.
        Use `False` to disable the middleware completely.
    :type SECURITY_HEADERS: SecurityHeadersOptions | None
    """

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["INVENTORY"]
    UVICORN_PORT: int = 8001
    DATABASE: DatabaseOptions = DatabaseOptions(NAME="inventory.db")
    SECURITY_HEADERS: SecurityHeadersOptions | None = SecurityHeadersOptions(
        content_security_policy_strict=False
    )


inventory_settings = InventorySettings()
