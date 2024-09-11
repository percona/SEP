"""Define settings for the Inventory API."""

from typing import ClassVar

from app.core.config import BaseYamlExtraSettings
from app.inventory.sources import PMMSource


class InventorySettings(BaseYamlExtraSettings):
    """Settings for the Inventory API.

    Attributes
    ----------
    OAUTH : OAuthOptions
        OAuth configuration options.
    TEMPLATES_DIR : Path, optional
        The directory containing template files. Defaults to `BASE_DIR/"templates"`
    STATIC_DIR : Path, optional
        The directory containing static files. Defaults to `BASE_DIR/"static"`

    """

    SETTINGS_PREFIXES: ClassVar[tuple[str]] = ("INVENTORY",)
    UVICORN_PORT: int = 8001
    PMM: PMMSource


inventory_settings = InventorySettings()
