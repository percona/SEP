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

"""Define tests for the app.tasks.db.engine module."""

import importlib
from unittest.mock import MagicMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker

import app.tasks.db.engine as tasks_engine_module
from app.tasks.config import tasks_settings
from app.tasks.db.engine import get_async_session_maker


class TestGetAsyncSessionMaker:
    """Test the get_async_session_maker function."""

    def test_returns_sessionmaker(self):
        """Assert get_async_session_maker returns an async session maker."""
        result = get_async_session_maker()
        assert isinstance(result, async_sessionmaker)

    def test_returns_new_instance_each_call(self):
        """Assert each call returns a distinct session maker instance."""
        maker_a = get_async_session_maker()
        maker_b = get_async_session_maker()
        assert maker_a is not maker_b


def test_engine_built_from_tasks_database():
    """Assert the Tasks engine is built via the shared factory from its own DATABASE."""
    try:
        with patch(
            "app.core.db.utils.create_app_async_engine", return_value=MagicMock()
        ) as create_engine:
            importlib.reload(tasks_engine_module)
            create_engine.assert_called_once_with(tasks_settings.DATABASE)
    finally:
        importlib.reload(tasks_engine_module)
