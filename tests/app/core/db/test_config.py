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


def test_database_options_rejects_mysql_engine():
    """Reject a removed MySQL backing-store engine at config load."""
    with pytest.raises(ValidationError):
        DatabaseOptions(ENGINE="mysql", NAME="testdb", HOST="localhost")


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
        ENGINE=AsyncDatabaseEngine.POSTGRESQL,
        HOST="localhost",
        USER="user",
        PASSWORD="supersecret",
        NAME="testdb",
    )
    assert "supersecret" not in repr(db_options)


def _postgresql_options(**overrides) -> DatabaseOptions:
    """Return PostgreSQL options, the dialect the sizing kwargs are emitted for."""
    return DatabaseOptions(
        ENGINE=AsyncDatabaseEngine.POSTGRESQL,
        HOST="localhost",
        NAME="testdb",
        **overrides,
    )


@pytest.mark.parametrize(
    ("engine", "expected"),
    [
        pytest.param(
            AsyncDatabaseEngine.POSTGRESQL,
            {
                "pool_pre_ping": True,
                "pool_size": 3,
                "max_overflow": 2,
                "pool_timeout": 10.0,
            },
            id="postgresql-sized",
        ),
        pytest.param(
            AsyncDatabaseEngine.SQLITE,
            {"pool_pre_ping": True},
            id="sqlite-omitted",
        ),
    ],
)
def test_pool_engine_kwargs_sizes_only_the_dialects_that_accept_it(engine, expected):
    """Emit the sizing defaults for PostgreSQL and omit them for SQLite."""
    db_options = DatabaseOptions(ENGINE=engine, HOST="localhost", NAME="testdb")

    assert db_options.pool_engine_kwargs == expected


@pytest.mark.parametrize("name", ["test.db", ""], ids=["file-backed", "in-memory"])
def test_pool_engine_kwargs_omits_sizing_for_sqlite_even_when_configured(name):
    """Discard a sizing value configured against SQLite, on either backing.

    Only the in-memory backing's ``StaticPool`` would reject the kwargs; a
    file-backed engine's pool would accept them. The carve-out is deliberately
    blanket anyway, so that one setting cannot work on one SQLite database and
    crash another — which makes this a discarded override, not a passthrough.
    """
    db_options = DatabaseOptions(
        ENGINE=AsyncDatabaseEngine.SQLITE,
        NAME=name,
        POOL_SIZE=7,
        MAX_OVERFLOW=3,
        POOL_TIMEOUT=25.0,
    )

    assert db_options.pool_engine_kwargs == {"pool_pre_ping": True}


def test_pool_engine_kwargs_includes_all_set_fields():
    """Map all set pool fields to lowercase create_engine kwargs."""
    db_options = _postgresql_options(POOL_SIZE=7, MAX_OVERFLOW=3, POOL_TIMEOUT=25.0)

    assert db_options.pool_engine_kwargs == {
        "pool_pre_ping": True,
        "pool_size": 7,
        "max_overflow": 3,
        "pool_timeout": 25.0,
    }


@pytest.mark.parametrize(
    ("field_kwargs", "expected_sizing"),
    [
        pytest.param(
            {"POOL_SIZE": 7},
            {"pool_size": 7, "max_overflow": 2, "pool_timeout": 10.0},
            id="pool-size-only",
        ),
        pytest.param(
            {"MAX_OVERFLOW": 7},
            {"pool_size": 3, "max_overflow": 7, "pool_timeout": 10.0},
            id="max-overflow-only",
        ),
        pytest.param(
            {"POOL_TIMEOUT": 7.0},
            {"pool_size": 3, "max_overflow": 2, "pool_timeout": 7.0},
            id="pool-timeout-only",
        ),
    ],
)
def test_pool_engine_kwargs_partial_override_takes_the_companion_defaults(
    field_kwargs, expected_sizing
):
    """Let one set field win while its unset companions take this class's defaults.

    A deployment that configured a single field used to inherit SQLAlchemy's
    ``10``/``30`` for the other two, so these cases pin the documented change.
    """
    db_options = _postgresql_options(**field_kwargs)

    assert db_options.pool_engine_kwargs == {"pool_pre_ping": True, **expected_sizing}


def test_pool_engine_kwargs_omits_a_field_set_to_none():
    """Fall back to SQLAlchemy's own default for a field explicitly set to None."""
    db_options = _postgresql_options(POOL_SIZE=None)

    assert db_options.pool_engine_kwargs == {
        "pool_pre_ping": True,
        "max_overflow": 2,
        "pool_timeout": 10.0,
    }


def test_pool_engine_kwargs_includes_zero_max_overflow():
    """Keep MAX_OVERFLOW=0 because 0 is set, not None."""
    db_options = _postgresql_options(MAX_OVERFLOW=0)

    assert db_options.pool_engine_kwargs == {
        "pool_pre_ping": True,
        "pool_size": 3,
        "max_overflow": 0,
        "pool_timeout": 10.0,
    }


def test_pool_engine_kwargs_respects_pre_ping_opt_out():
    """Allow disabling pool_pre_ping per engine."""
    db_options = DatabaseOptions(NAME="test.db", POOL_PRE_PING=False)

    assert db_options.pool_engine_kwargs == {"pool_pre_ping": False}


@pytest.mark.parametrize(
    ("engine", "expected"),
    [
        pytest.param(
            AsyncDatabaseEngine.POSTGRESQL,
            {"connect_args": {"timeout": 2.5}},
            id="asyncpg-timeout",
        ),
        pytest.param(AsyncDatabaseEngine.SQLITE, {}, id="sqlite-omitted"),
    ],
)
def test_connect_engine_kwargs_maps_per_dialect(engine, expected):
    """Map CONNECT_TIMEOUT to the driver key each dialect understands."""
    db_options = DatabaseOptions(
        ENGINE=engine, NAME="testdb", HOST="localhost", CONNECT_TIMEOUT=2.5
    )

    assert db_options.connect_engine_kwargs == expected


def test_connect_engine_kwargs_empty_when_unset():
    """Return no connect_args when CONNECT_TIMEOUT is unset."""
    db_options = DatabaseOptions(
        ENGINE=AsyncDatabaseEngine.POSTGRESQL,
        NAME="testdb",
        HOST="localhost",
    )

    assert db_options.connect_engine_kwargs == {}


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
