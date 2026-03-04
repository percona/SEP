"""Define tests for the app.sep.sync.syncers.mysql.payload module."""

import gzip
import json
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.syncmysql

try:
    import pymysql
    from pymysql.cursors import DictCursor

    from app.sep.sync.syncers.mysql.payload import (
        atomic_write_gzip_json,
        format_filename,
        get_table,
        iter_schemas,
        iter_tables,
        main,
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


class TestMain:
    """Test the main CLI entry point."""

    MODULE = "app.sep.sync.syncers.mysql.payload"

    def _write_config(self, tmp_path, config):
        """Write a JSON config file and return its path.

        :param tmp_path: Temporary directory provided by pytest.
        :type tmp_path: Path
        :param config: Configuration dictionary to serialize.
        :type config: dict
        :return: Path to the written config file.
        :rtype: Path
        """
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))
        return config_path

    def _make_mock_connection(self, mock_connect):
        """Set up pymysql.connect mock to return a cursor via context managers.

        :param mock_connect: The patched pymysql.connect mock.
        :type mock_connect: MagicMock
        :return: The mock cursor instance.
        :rtype: MagicMock
        """
        mock_cursor = MagicMock(spec=DictCursor)
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_connect.return_value = mock_conn
        return mock_cursor

    @patch(f"{MODULE}.socket")
    @patch(f"{MODULE}.myloginpath")
    @patch(f"{MODULE}.pymysql")
    @patch(f"{MODULE}.atomic_write_gzip_json")
    @patch(f"{MODULE}.iter_schemas")
    def test_main_multi_host(
        self,
        mock_iter_schemas,
        mock_write,
        mock_pymysql,
        mock_myloginpath,
        mock_socket,
        tmp_path,
        capsys,
        monkeypatch,
    ):
        """Assert main processes multiple hosts and writes JSON output."""
        config_path = self._write_config(
            tmp_path, {"hosts": ["host1:3306", "host2:3307"]}
        )
        monkeypatch.setattr("sys.argv", ["payload", "-c", str(config_path)])
        monkeypatch.chdir(tmp_path)

        mock_myloginpath.parse.side_effect = Exception("no .mylogin.cnf")
        mock_socket.gethostbyname.return_value = "10.0.0.1"
        mock_socket.gethostname.return_value = "testhost"
        self._make_mock_connection(mock_pymysql.connect)
        mock_iter_schemas.return_value = iter([{"name": "testdb"}])
        mock_write.return_value = {"lines": 1, "bytes": 100}

        main()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        expected_connect_calls = 2
        assert "services" in output
        assert mock_pymysql.connect.call_count == expected_connect_calls

    @patch(f"{MODULE}.socket")
    @patch(f"{MODULE}.myloginpath")
    @patch(f"{MODULE}.pymysql")
    @patch(f"{MODULE}.get_table")
    def test_main_schema_and_table(
        self,
        mock_get_table,
        mock_pymysql,
        mock_myloginpath,
        mock_socket,
        tmp_path,
        capsys,
        monkeypatch,
    ):
        """Assert main fetches a single table when schema and table are specified."""
        config_path = self._write_config(
            tmp_path, {"hosts": ["host1:3306"], "schema": "mydb", "table": "mytable"}
        )
        monkeypatch.setattr("sys.argv", ["payload", "-c", str(config_path)])

        mock_myloginpath.parse.return_value = {"user": "root", "password": "pass"}
        mock_socket.gethostbyname.return_value = "10.0.0.1"
        mock_socket.gethostname.return_value = "testhost"
        mock_cursor = self._make_mock_connection(mock_pymysql.connect)
        mock_get_table.return_value = {
            "name": "mytable",
            "create": "CREATE TABLE ...",
            "keys": {},
        }

        main()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "tables" in output
        assert "host1:3306/mydb.mytable" in output["tables"]
        mock_get_table.assert_called_once_with(mock_cursor, "mydb", "mytable")

    @patch(f"{MODULE}.socket")
    @patch(f"{MODULE}.myloginpath")
    @patch(f"{MODULE}.pymysql")
    @patch(f"{MODULE}.atomic_write_gzip_json")
    @patch(f"{MODULE}.iter_tables")
    def test_main_schema_only(
        self,
        mock_iter_tables,
        mock_write,
        mock_pymysql,
        mock_myloginpath,
        mock_socket,
        tmp_path,
        capsys,
        monkeypatch,
    ):
        """Assert main fetches schema tables when only schema is specified."""
        config_path = self._write_config(
            tmp_path, {"hosts": ["host1:3306"], "schema": "mydb"}
        )
        monkeypatch.setattr("sys.argv", ["payload", "-c", str(config_path)])
        monkeypatch.chdir(tmp_path)

        mock_myloginpath.parse.side_effect = Exception("no .mylogin.cnf")
        mock_socket.gethostbyname.return_value = "10.0.0.1"
        mock_socket.gethostname.return_value = "testhost"
        self._make_mock_connection(mock_pymysql.connect)
        expected_tables_count = 3
        mock_write.return_value = {"lines": expected_tables_count, "bytes": 200}

        main()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "schemas" in output
        assert "host1:3306/mydb" in output["schemas"]
        assert (
            output["schemas"]["host1:3306/mydb"]["tables_count"]
            == expected_tables_count
        )

    def test_main_table_without_schema_exits(self, tmp_path, monkeypatch):
        """Assert main exits with error when table is specified without schema."""
        config_path = self._write_config(
            tmp_path, {"hosts": ["host1:3306"], "table": "mytable"}
        )
        monkeypatch.setattr("sys.argv", ["payload", "-c", str(config_path)])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == "schema must be passed along with table"

    def test_main_schema_with_multiple_hosts_exits(self, tmp_path, monkeypatch):
        """Assert main exits with error when schema has multiple hosts."""
        config_path = self._write_config(
            tmp_path, {"hosts": ["host1:3306", "host2:3306"], "schema": "mydb"}
        )
        monkeypatch.setattr("sys.argv", ["payload", "-c", str(config_path)])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == "Only one host allowed if schema is specified"

    @patch(f"{MODULE}.socket")
    @patch(f"{MODULE}.myloginpath")
    @patch(f"{MODULE}.pymysql")
    def test_main_connection_error_with_schema_exits(
        self, mock_pymysql, mock_myloginpath, mock_socket, tmp_path, capsys, monkeypatch
    ):
        """Assert main exits with code 2 when connection fails in schema mode."""
        config_path = self._write_config(
            tmp_path, {"hosts": ["host1:3306"], "schema": "mydb"}
        )
        monkeypatch.setattr("sys.argv", ["payload", "-c", str(config_path)])

        mock_myloginpath.parse.side_effect = Exception("no .mylogin.cnf")
        mock_socket.gethostbyname.return_value = "10.0.0.1"
        mock_socket.gethostname.return_value = "testhost"
        mock_pymysql.connect.side_effect = pymysql.MySQLError("Connection refused")
        mock_pymysql.MySQLError = pymysql.MySQLError

        exit_code = 2
        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == exit_code
        captured = capsys.readouterr()
        assert "Error connecting to" in captured.err

    @patch(f"{MODULE}.socket")
    @patch(f"{MODULE}.myloginpath")
    @patch(f"{MODULE}.pymysql")
    def test_main_connection_error_multi_host_continues(
        self, mock_pymysql, mock_myloginpath, mock_socket, tmp_path, capsys, monkeypatch
    ):
        """Assert main continues processing when a host fails in multi-host mode."""
        config_path = self._write_config(tmp_path, {"hosts": ["host1:3306"]})
        monkeypatch.setattr("sys.argv", ["payload", "-c", str(config_path)])

        mock_myloginpath.parse.side_effect = Exception("no .mylogin.cnf")
        mock_socket.gethostbyname.return_value = "10.0.0.1"
        mock_socket.gethostname.return_value = "testhost"
        mock_pymysql.connect.side_effect = pymysql.MySQLError("Connection refused")
        mock_pymysql.MySQLError = pymysql.MySQLError

        main()

        captured = capsys.readouterr()
        assert "Error connecting to" in captured.err
        output = json.loads(captured.out)
        assert output == {}

    @patch(f"{MODULE}.socket")
    @patch(f"{MODULE}.myloginpath")
    @patch(f"{MODULE}.pymysql")
    @patch(f"{MODULE}.get_table")
    def test_main_resolve_localhost(
        self,
        mock_get_table,
        mock_pymysql,
        mock_myloginpath,
        mock_socket,
        tmp_path,
        capsys,
        monkeypatch,
    ):
        """Assert main resolves local IP to 127.0.0.1 when resolve_localhost is set."""
        local_ip = "192.168.1.100"
        config_path = self._write_config(
            tmp_path,
            {
                "hosts": [f"{local_ip}:3306"],
                "schema": "mydb",
                "table": "mytable",
                "resolve_localhost": True,
            },
        )
        monkeypatch.setattr("sys.argv", ["payload", "-c", str(config_path)])

        mock_myloginpath.parse.side_effect = Exception("no .mylogin.cnf")
        mock_socket.gethostbyname.return_value = local_ip
        mock_socket.gethostname.return_value = "testhost"
        self._make_mock_connection(mock_pymysql.connect)
        mock_get_table.return_value = {
            "name": "mytable",
            "create": "CREATE TABLE ...",
            "keys": {},
        }

        main()

        expected_port = 3306
        mock_pymysql.connect.assert_called_once_with(
            host="127.0.0.1",
            port=expected_port,
            user=None,
            password=None,
            read_default_file="~/.my.cnf",
        )
