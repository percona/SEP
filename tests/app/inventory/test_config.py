"""Test inventory configuration defaults."""

from app.inventory.config import InventorySettings

DEFAULT_UVICORN_PORT = 8001


class TestInventorySettings:
    """Test InventorySettings default values."""

    def test_defaults(self) -> None:
        """Assert InventorySettings has expected default values."""
        settings = InventorySettings()
        assert settings.UVICORN_PORT == DEFAULT_UVICORN_PORT
        assert settings.DATABASE.NAME == "inventory.db"
        assert settings.SECURITY_HEADERS is not None
