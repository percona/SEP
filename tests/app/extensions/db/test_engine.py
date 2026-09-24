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

"""Define tests for the app.extensions.db.engine module."""

import importlib
from unittest.mock import MagicMock, patch

import app.extensions.db.engine as extensions_engine_module
from app.extensions.config import extensions_settings


def test_engine_built_from_extensions_database():
    """Assert the PMM Extensions engine is built via the shared factory from its own DATABASE."""
    try:
        with patch(
            "app.core.db.utils.create_app_async_engine", return_value=MagicMock()
        ) as create_engine:
            importlib.reload(extensions_engine_module)
            create_engine.assert_called_once_with(extensions_settings.DATABASE)
    finally:
        importlib.reload(extensions_engine_module)
