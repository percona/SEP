"""Define settings for the Inventory API."""

from pydantic import HttpUrl

from app.core.config import BaseYamlExtraSettings
from app.core.fields import RelativeFilePath
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

    PMM: PMMSource
    INVENTORY_ENDPOINT: HttpUrl
    INVENTORY_SSL_KEYFILE: RelativeFilePath | None = None
    INVENTORY_SSL_CERTFILE: RelativeFilePath | None = None


inventory_settings = InventorySettings()
