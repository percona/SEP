"""Define tests for the app.sep.sync.mysql.syncer.payload module."""

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.syncmysql

try:
    from pymysql.cursors import DictCursor

    from app.sep.sync.syncers.mysql.payload import (
        get_all_schemas,
        get_schema,
        get_table,
        parse_host_port,
    )
except ImportError as exc:
    pytest.skip(f"skipping mysql payload tests ({exc})", allow_module_level=True)


@pytest.fixture
def mock_cursor():
    """Mockcursor object for testing DB-related functions."""
    return MagicMock(spec=DictCursor)


def test_get_table(mock_cursor):
    """Test get_table function with a mocked cursor."""
    mock_cursor.fetchone.return_value = {
        "Create Table": "CREATE TABLE `test_table` (id INT PRIMARY KEY)"
    }

    mock_cursor.fetchall.return_value = [
        {
            "INDEX_NAME": "PRIMARY",
            "COLUMN_NAME": "id",
            "NON_UNIQUE": 0,
            "NULLABLE": "NO",
        }
    ]

    result = get_table(mock_cursor, "test_db", "test_table")
    expected_call_count = 2
    assert result["name"] == "test_table"
    assert "CREATE TABLE `test_table`" in result["create"]
    assert "PRIMARY" in result["keys"]
    assert result["keys"]["PRIMARY"]["columns"] == ["id"]
    assert result["keys"]["PRIMARY"]["unique"] is True
    assert result["keys"]["PRIMARY"]["nullable"] is False

    assert mock_cursor.execute.call_count == expected_call_count


def test_get_schema(mock_cursor):
    """Test get_schema function with a mocked cursor."""
    mock_cursor.fetchall.return_value = [{"TABLE_NAME": "test_table"}]

    with patch("app.sep.sync.syncers.mysql.payload.get_table") as mocked_get_table:
        mocked_get_table.return_value = {
            "name": "test_table",
            "create": "CREATE TABLE `test_table` (...)",
            "keys": {},
        }

        schema = get_schema(mock_cursor, "test_db")

        assert schema["name"] == "test_db"
        assert len(schema["tables"]) == 1
        assert schema["tables"][0]["name"] == "test_table"

    mock_cursor.execute.assert_called_once()
    mocked_get_table.assert_called_once()


def test_get_all_schemas(mock_cursor):
    """Test get_all_schemas function with a mocked cursor."""
    mock_schema_count = 2
    mock_cursor.fetchall.side_effect = [
        [
            {"Database": "mysql"},
            {"Database": "test_db"},
            {"Database": "information_schema"},
        ],  # For SHOW DATABASES
        [{"TABLE_NAME": "table1"}],
        [{"TABLE_NAME": "table2"}],
    ]

    with patch("app.sep.sync.syncers.mysql.payload.get_table") as mocked_get_table:
        mocked_get_table.side_effect = [
            {"name": "table1", "create": "CREATE TABLE ...", "keys": {}},
            {"name": "table2", "create": "CREATE TABLE ...", "keys": {}},
        ]

        ignored = ["information_schema"]
        schemas = get_all_schemas(mock_cursor, ignored)

        assert len(schemas) == mock_schema_count
        assert schemas[0]["name"] == "mysql"
        assert schemas[1]["name"] == "test_db"

        assert len(schemas[0]["tables"]) == 1
        assert len(schemas[1]["tables"]) == 1


def test_parse_host_port():
    """Test parse_host_port function to ensure it splits host:port correctly."""
    mock_port1, mock_port2 = 3307, 3306
    host, port = parse_host_port("localhost:3307")
    assert host == "localhost"
    assert port == mock_port1

    host, port = parse_host_port("127.0.0.1")
    assert host == "127.0.0.1"
    assert port == mock_port2
