# Copyright (C) 2026 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

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
