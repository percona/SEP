"""Define settings for the Inventory API."""

from pydantic_settings import SettingsConfigDict

from app.core.config import BaseYamlSettings
from app.inventory.sources import PMMSource


class InventorySettings(BaseYamlSettings):
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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        yaml_file="settings.yaml",
        cli_parse_args=False,
        extra="ignore",
    )
    PMM: PMMSource


inventory_settings = InventorySettings()
