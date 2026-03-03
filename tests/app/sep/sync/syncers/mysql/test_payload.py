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

"""Define tests for the app.sep.sync.syncers.mysql.payload module."""

import gzip
import json
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.syncmysql

try:
    from pymysql.cursors import DictCursor

    from app.sep.sync.syncers.mysql.payload import (
        atomic_write_gzip_json,
        format_filename,
        get_table,
        iter_schemas,
        iter_tables,
        parse_host_port,
    )
except ImportError as exc:
    pytest.skip(f"skipping mysql payload tests ({exc})", allow_module_level=True)


@pytest.fixture
def mock_cursor():
    """Mock cursor object for testing DB-related functions."""
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
    expected_execute_call_count = 2

    result = get_table(mock_cursor, "test_db", "test_table")
    assert result["name"] == "test_table"
    assert "CREATE TABLE `test_table`" in result["create"]
    assert "PRIMARY" in result["keys"]
    assert result["keys"]["PRIMARY"]["columns"] == ["id"]
    assert result["keys"]["PRIMARY"]["unique"] is True
    assert result["keys"]["PRIMARY"]["nullable"] is False

    assert mock_cursor.execute.call_count == expected_execute_call_count


def test_iter_tables(mock_cursor):
    """Test iter_tables yields tables with a mocked cursor."""
    mock_cursor.fetchall.return_value = [
        {"TABLE_NAME": "table1"},
        {"TABLE_NAME": "table2"},
    ]
    expected_get_table_call_count = 2

    with patch("app.sep.sync.syncers.mysql.payload.get_table") as mocked_get_table:
        mocked_get_table.side_effect = [
            {"name": "table1", "create": "CREATE TABLE ...", "keys": {}},
            {"name": "table2", "create": "CREATE TABLE ...", "keys": {}},
        ]
        expected_tables_len = 2

        tables = list(iter_tables(mock_cursor, "test_db"))

        assert len(tables) == expected_tables_len
        assert tables[0]["name"] == "table1"
        assert tables[1]["name"] == "table2"

    mock_cursor.execute.assert_called_once()
    assert mocked_get_table.call_count == expected_get_table_call_count


def test_iter_schemas(mock_cursor):
    """Test iter_schemas yields schema names, respecting ignored list."""
    mock_cursor.fetchall.return_value = [
        {"Database": "mysql"},
        {"Database": "test_db"},
        {"Database": "information_schema"},
    ]
    expected_schemas_len = 2

    ignored = ["information_schema"]
    schemas = list(iter_schemas(mock_cursor, ignored))

    assert len(schemas) == expected_schemas_len
    assert schemas[0]["name"] == "mysql"
    assert schemas[1]["name"] == "test_db"


def test_parse_host_port():
    """Test parse_host_port function to ensure it splits host:port correctly."""
    expected_port = 3307
    host, port = parse_host_port("localhost:3307")
    assert host == "localhost"
    assert port == expected_port

    expected_default_port = 3306
    host, port = parse_host_port("127.0.0.1")
    assert host == "127.0.0.1"
    assert port == expected_default_port


class TestFormatFilename:
    """Test format_filename utility."""

    def test_format_filename_preserve_safe_chars(self):
        """Test preserve safe characters and append suffix."""
        name = "host_127.0.0.1-3306.v1"
        out = format_filename(name, suffix=".ndjson.gz")
        assert out == f"{name}.ndjson.gz"

    def test_format_filename_escape_unsafe_chars(self):
        """Test percent-encode unsafe characters."""
        name = "db:name/with spaces?&"
        out = format_filename(name, suffix=".gz")
        assert out.startswith("db%3Aname%2Fwith%20spaces%3F%26")
        assert out.endswith(".gz")

    def test_format_filename_hash_when_too_long(self):
        """Test hash and truncate when exceeding max length."""
        long_name = "x" * 300
        out = format_filename(long_name, suffix=".ndjson.gz")
        digest_len = 40
        filename_max_len = 255
        assert out.endswith(".ndjson.gz")
        stem = out[: -len(".ndjson.gz")]
        assert "-" in stem
        digest = stem.split("-")[-1]
        assert len(digest) == digest_len
        assert len(out) <= filename_max_len


class TestAtomicWriteGzipJson:
    """Test atomic_write_gzip_json utility."""

    def test_atomic_write_gzip_json_writes_lines_and_bytes(self, tmp_path):
        """Test write json objects as ndjson.gz and report counts."""
        objs = [{"a": 1}, {"b": 2}]
        out = tmp_path / "out.ndjson.gz"
        expected_lines = 2

        stats = atomic_write_gzip_json(objs, out)
        assert stats["lines"] == expected_lines
        assert stats["bytes"] == out.stat().st_size > 0

        data = gzip.decompress(out.read_bytes()).decode("utf8").splitlines()
        assert [json.loads(x) for x in data] == objs

    def test_atomic_write_gzip_json_is_deterministic(self, tmp_path):
        """Test produce deterministic gzip (mtime=0 stabilises bytes)."""
        objs = [{"x": 1}, {"y": [1, 2, 3]}, {"z": "ok"}]
        out1 = tmp_path / "one.ndjson.gz"
        out2 = tmp_path / "two.ndjson.gz"

        atomic_write_gzip_json(objs, out1)
        atomic_write_gzip_json(objs, out2)

        b1, b2 = out1.read_bytes(), out2.read_bytes()
        assert b1 == b2
