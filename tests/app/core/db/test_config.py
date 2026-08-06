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

from urllib.parse import unquote, urlsplit

import pytest
from pydantic import ValidationError

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


def test_database_options_url_round_trips_a_password_with_reserved_characters():
    """Encode a password whose reserved characters would otherwise end the authority."""
    db_options = DatabaseOptions(
        ENGINE=AsyncDatabaseEngine.POSTGRESQL,
        HOST="localhost",
        PORT=5432,
        USER="user",
        PASSWORD="p@ss:w/rd123",
        NAME="testdb",
    )

    expected_url = "postgresql+asyncpg://user:p%40ss%3Aw%2Frd123@localhost:5432/testdb"
    assert expected_url == db_options.URL
    assert unquote(urlsplit(db_options.URL).password) == "p@ss:w/rd123"


def test_database_options_url_round_trips_a_user_with_reserved_characters():
    """Encode a user whose reserved characters would otherwise end the credentials."""
    db_options = DatabaseOptions(
        ENGINE=AsyncDatabaseEngine.POSTGRESQL,
        HOST="localhost",
        PORT=5432,
        USER="us/er:name",
        PASSWORD="pass",
        NAME="testdb",
    )

    assert unquote(urlsplit(db_options.URL).username) == "us/er:name"


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


def test_pool_engine_kwargs_empty_when_unset():
    """Yield no kwargs when pool fields are unset, so the engine keeps defaults."""
    db_options = DatabaseOptions(NAME="test.db")

    assert db_options.pool_engine_kwargs == {}


def test_pool_engine_kwargs_includes_all_set_fields():
    """Map all three set pool fields to lowercase create_engine kwargs."""
    db_options = DatabaseOptions(
        NAME="test.db", POOL_SIZE=7, MAX_OVERFLOW=3, POOL_TIMEOUT=25.0
    )

    assert db_options.pool_engine_kwargs == {
        "pool_size": 7,
        "max_overflow": 3,
        "pool_timeout": 25.0,
    }


def test_pool_engine_kwargs_omits_unset_fields():
    """Omit unset pool fields from the kwargs."""
    db_options = DatabaseOptions(NAME="test.db", POOL_SIZE=7)

    assert db_options.pool_engine_kwargs == {"pool_size": 7}


def test_pool_engine_kwargs_includes_zero_max_overflow():
    """Keep MAX_OVERFLOW=0 because 0 is set, not None."""
    db_options = DatabaseOptions(NAME="test.db", MAX_OVERFLOW=0)

    assert db_options.pool_engine_kwargs == {"max_overflow": 0}


@pytest.mark.parametrize(
    ("engine", "expected"),
    [
        pytest.param(
            AsyncDatabaseEngine.POSTGRESQL, {"timeout": 2.5}, id="asyncpg-timeout"
        ),
        pytest.param(
            AsyncDatabaseEngine.MYSQL,
            {"connect_timeout": 2.5},
            id="aiomysql-connect-timeout",
        ),
        pytest.param(AsyncDatabaseEngine.SQLITE, {}, id="sqlite-omitted"),
    ],
)
def test_connect_args_maps_per_dialect(engine, expected):
    """Map CONNECT_TIMEOUT to the driver key each dialect understands."""
    db_options = DatabaseOptions(
        ENGINE=engine, NAME="testdb", HOST="localhost", CONNECT_TIMEOUT=2.5
    )

    assert db_options.connect_args == expected


def test_connect_args_empty_when_unset():
    """Yield no connect_args when CONNECT_TIMEOUT is unset."""
    db_options = DatabaseOptions(
        ENGINE=AsyncDatabaseEngine.POSTGRESQL,
        NAME="testdb",
        HOST="localhost",
    )

    assert db_options.connect_args == {}


@pytest.mark.parametrize(
    "field_kwargs",
    [
        {"POOL_SIZE": 0},
        {"MAX_OVERFLOW": -1},
        {"POOL_TIMEOUT": 0},
        {"CONNECT_TIMEOUT": 0},
    ],
)
def test_pool_field_bounds_rejected_at_config_load(field_kwargs):
    """Reject out-of-range pool values at config load, not at engine creation."""
    with pytest.raises(ValidationError):
        DatabaseOptions(NAME="test.db", **field_kwargs)
