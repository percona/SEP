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

from sqlalchemy.orm import sessionmaker

from app.tasks.db.engine import get_async_session_maker


class TestGetAsyncSessionMaker:
    """Test the get_async_session_maker function."""

    def test_returns_sessionmaker(self):
        """Assert get_async_session_maker returns a sessionmaker instance."""
        result = get_async_session_maker()
        assert isinstance(result, sessionmaker)

    def test_returns_new_instance_each_call(self):
        """Assert each call returns a distinct session maker instance."""
        maker_a = get_async_session_maker()
        maker_b = get_async_session_maker()
        assert maker_a is not maker_b
