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

"""Define tests for the app.core.db.config module."""

from app.core.db.config import DatabaseOptions
from app.core.utils.fields import AsyncDatabaseEngine


def test_database_options_url_with_none_host():
    """Test DatabaseOptions URL construction with None HOST."""
    db_options = DatabaseOptions(
        ENGINE=AsyncDatabaseEngine.SQLITE, HOST=None, NAME="test.db"
    )

    expected_url = "sqlite+aiosqlite:///test.db"
    assert expected_url == db_options.URL


def test_database_options_url_with_empty_host():
    """Test DatabaseOptions URL construction with empty string HOST."""
    db_options = DatabaseOptions(
        ENGINE=AsyncDatabaseEngine.SQLITE, HOST="", NAME="test.db"
    )

    expected_url = "sqlite+aiosqlite:///test.db"
    assert expected_url == db_options.URL


def test_database_options_url_with_host():
    """Test DatabaseOptions URL construction with actual HOST."""
    db_options = DatabaseOptions(
        ENGINE=AsyncDatabaseEngine.MYSQL,
        HOST="localhost",
        PORT=3306,
        USER="user",
        PASSWORD="pass",
        NAME="testdb",
    )

    expected_url = "mysql+aiomysql://user:pass@localhost:3306/testdb"
    assert expected_url == db_options.URL


def test_database_options_url_with_postgresql():
    """Test DatabaseOptions URL construction with PostgreSQL."""
    db_options = DatabaseOptions(
        ENGINE=AsyncDatabaseEngine.POSTGRESQL,
        HOST="localhost",
        PORT=5432,
        USER="user",
        PASSWORD="pass",
        NAME="testdb",
    )

    expected_url = "postgresql+asyncpg://user:pass@localhost:5432/testdb"
    assert expected_url == db_options.URL


def test_database_options_password_masked_in_repr():
    """Test that PASSWORD is masked in repr output."""
    db_options = DatabaseOptions(
        ENGINE=AsyncDatabaseEngine.MYSQL,
        HOST="localhost",
        USER="user",
        PASSWORD="supersecret",
        NAME="testdb",
    )
    assert "supersecret" not in repr(db_options)
