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

"""Test the connectivity check payload script."""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_pymysql():
    """Inject a mock pymysql module into sys.modules."""
    mock = MagicMock()
    old = sys.modules.get("pymysql")
    sys.modules["pymysql"] = mock
    yield mock
    if old is None:
        sys.modules.pop("pymysql", None)
    else:
        sys.modules["pymysql"] = old


@pytest.fixture
def mock_myloginpath():
    """Inject a mock myloginpath module into sys.modules."""
    mock = MagicMock()
    old = sys.modules.get("myloginpath")
    sys.modules["myloginpath"] = mock
    yield mock
    if old is None:
        sys.modules.pop("myloginpath", None)
    else:
        sys.modules["myloginpath"] = old


@pytest.fixture
def mock_psycopg2():
    """Inject a mock psycopg2 module into sys.modules."""
    mock = MagicMock()
    old = sys.modules.get("psycopg2")
    sys.modules["psycopg2"] = mock
    yield mock
    if old is None:
        sys.modules.pop("psycopg2", None)
    else:
        sys.modules["psycopg2"] = old


@pytest.fixture
def mock_pymongo():
    """Inject a mock pymongo module into sys.modules."""
    mock = MagicMock()
    old = sys.modules.get("pymongo")
    sys.modules["pymongo"] = mock
    yield mock
    if old is None:
        sys.modules.pop("pymongo", None)
    else:
        sys.modules["pymongo"] = old


class TestCheckMySQL:
    """Test MySQL connectivity checker."""

    def test_success(self, mock_myloginpath, mock_pymysql):
        """Verify successful MySQL connectivity check."""
        from app.tasks.connectivity.payload import check_mysql

        mock_myloginpath.parse.return_value = {
            "user": "root",
            "password": "secret",
        }
        mock_conn = MagicMock()
        mock_pymysql.connect.return_value = mock_conn
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        result = check_mysql("db-host", 3306)

        assert result == {"success": True}
        mock_pymysql.connect.assert_called_once_with(
            host="db-host",
            port=3306,
            connect_timeout=10,
            user="root",
            password="secret",
        )
        mock_cursor.execute.assert_called_once_with("SELECT 1")
        mock_conn.close.assert_called_once()

    def test_connection_failure(self, mock_myloginpath, mock_pymysql):
        """Verify MySQL check returns error on connection failure."""
        from app.tasks.connectivity.payload import check_mysql

        mock_myloginpath.parse.return_value = {}
        mock_pymysql.connect.side_effect = Exception("Connection refused")

        result = check_mysql("db-host", 3306)

        assert result == {"success": False, "error": "Connection refused"}

    def test_myloginpath_failure_falls_back(self, mock_myloginpath, mock_pymysql):
        """Verify connectivity check proceeds when myloginpath parsing fails."""
        from app.tasks.connectivity.payload import check_mysql

        mock_myloginpath.parse.side_effect = Exception("No login path found")
        mock_conn = MagicMock()
        mock_pymysql.connect.return_value = mock_conn
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        result = check_mysql("db-host", 3306)

        assert result == {"success": True}
        mock_pymysql.connect.assert_called_once_with(
            host="db-host", port=3306, connect_timeout=10
        )


class TestCheckPostgreSQL:
    """Test PostgreSQL connectivity checker."""

    def test_success(self, mock_psycopg2):
        """Verify successful PostgreSQL connectivity check."""
        from app.tasks.connectivity.payload import check_postgresql

        mock_conn = MagicMock()
        mock_psycopg2.connect.return_value = mock_conn
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        result = check_postgresql("db-host", 5432)

        assert result == {"success": True}
        mock_psycopg2.connect.assert_called_once_with(
            host="db-host", port=5432, connect_timeout=10
        )
        mock_cursor.execute.assert_called_once_with("SELECT 1")
        mock_conn.close.assert_called_once()

    def test_connection_failure(self, mock_psycopg2):
        """Verify PostgreSQL check returns error on connection failure."""
        from app.tasks.connectivity.payload import check_postgresql

        mock_psycopg2.connect.side_effect = Exception("Connection refused")

        result = check_postgresql("db-host", 5432)

        assert result == {"success": False, "error": "Connection refused"}


class TestCheckMongoDB:
    """Test MongoDB connectivity checker."""

    def test_success(self, mock_pymongo):
        """Verify successful MongoDB connectivity check."""
        from app.tasks.connectivity.payload import check_mongodb

        mock_client = MagicMock()
        mock_pymongo.MongoClient.return_value = mock_client

        result = check_mongodb("db-host", 27017)

        assert result == {"success": True}
        mock_pymongo.MongoClient.assert_called_once_with(
            host="db-host", port=27017, serverSelectionTimeoutMS=10000
        )
        mock_client.admin.command.assert_called_once_with("ping")
        mock_client.close.assert_called_once()

    def test_connection_failure(self, mock_pymongo):
        """Verify MongoDB check returns error on connection failure."""
        from app.tasks.connectivity.payload import check_mongodb

        mock_pymongo.MongoClient.side_effect = Exception("Server selection timeout")

        result = check_mongodb("db-host", 27017)

        assert result == {"success": False, "error": "Server selection timeout"}


class TestMain:
    """Test the payload main entry point."""

    def test_reads_config_from_file_path(
        self, tmp_path, mock_myloginpath, mock_pymysql
    ):
        """Verify main reads the JSON config from the path given by ``--config``.

        The Nomad ``run-python`` task invokes the script with
        ``--config ${NOMAD_TASK_DIR}/script_config`` — a file path, not an inline
        JSON string. The script must open and parse that file.
        """
        mock_myloginpath.parse.return_value = {}
        mock_conn = MagicMock()
        mock_pymysql.connect.return_value = mock_conn
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        config_path = tmp_path / "script_config"
        config_path.write_text(
            json.dumps({"service_type": "mysql", "host": "db-host", "port": 3306})
        )

        with patch("sys.argv", ["payload.py", "--config", str(config_path)]):
            from app.tasks.connectivity.payload import main

            main()

        mock_pymysql.connect.assert_called_once_with(
            host="db-host",
            port=3306,
            connect_timeout=10,
            user=None,
            password=None,
        )

    def test_unknown_service_type_raises(self, tmp_path):
        """Verify KeyError raised for unsupported service type."""
        from app.tasks.connectivity.payload import main

        config_path = tmp_path / "script_config"
        config_path.write_text(
            json.dumps({"service_type": "REDIS", "host": "db-host", "port": 6379})
        )

        with (
            patch("sys.argv", ["payload.py", "--config", str(config_path)]),
            pytest.raises(KeyError),
        ):
            main()
