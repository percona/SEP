"""Define tests for the app.core.db.config module."""

from pydantic import SecretStr

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
        PASSWORD=SecretStr("pass"),
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
        PASSWORD=SecretStr("pass"),
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
        PASSWORD=SecretStr("supersecret"),
        NAME="testdb",
    )
    assert "supersecret" not in repr(db_options)
