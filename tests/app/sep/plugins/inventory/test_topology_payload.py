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

"""Unit tests for the executor-side inventory topology payload."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


class _FakeCursor:
    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(self, query: str) -> None:
        self.query = query

    def fetchone(self) -> dict[str, Any] | None:
        query = getattr(self, "query", "")
        if "@@server_id" in query:
            return {
                "server_hash": "server-hash",
                "server_id": 1,
                "server_uuid": "uuid-1",
                "port": 3307,
                "super_read_only": 0,
                "read_only": 0,
                "version": "8.0.42",
                "log_bin": 1,
                "hostname": "db.example",
            }
        if query.startswith(("SHOW REPLICA", "SHOW SLAVE")):
            return None
        if "@@wsrep_provider" in query:
            return {"name": ""}
        if "gtid_mode" in query:
            return {"Value": "ON"}
        return {}

    def fetchall(self) -> list[dict[str, Any]]:
        return []


class _FakeConnection:
    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def cursor(self, _cursor_cls: Any) -> _FakeCursor:
        return _FakeCursor()


def _load_payload_module(monkeypatch):
    calls: list[dict[str, Any]] = []

    fake_myloginpath = ModuleType("myloginpath")
    fake_myloginpath.read = lambda: (
        '[db]\nhost = "db.example"\nport = 3307\nuser = "root"\npassword = "secret"\n'
    )

    fake_pymysql = ModuleType("pymysql")
    fake_pymysql.MySQLError = Exception

    def _connect(**kwargs: Any) -> _FakeConnection:
        calls.append(kwargs)
        return _FakeConnection()

    fake_pymysql.connect = _connect
    fake_cursors = ModuleType("pymysql.cursors")
    fake_cursors.DictCursor = object

    monkeypatch.setitem(sys.modules, "myloginpath", fake_myloginpath)
    monkeypatch.setitem(sys.modules, "pymysql", fake_pymysql)
    monkeypatch.setitem(sys.modules, "pymysql.cursors", fake_cursors)

    repo_root = Path(__file__).resolve().parents[5]
    payload_path = repo_root / "app/sep/plugins/inventory/payloads/topology.py"
    spec = importlib.util.spec_from_file_location(
        "inventory_topology_payload_test", payload_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, calls


def test_collect_host_uses_my_cnf_fallback(monkeypatch) -> None:
    """PyMySQL gets both per-host login-path creds and the ~/.my.cnf fallback."""
    payload, calls = _load_payload_module(monkeypatch)

    payload.collect_host("db.example:3307")

    assert calls
    assert calls[0]["user"] == "root"
    assert calls[0]["password"] == "secret"
    assert calls[0]["read_default_file"] == "~/.my.cnf"


def test_query_repl_info_uses_source_fallback_when_master_columns_are_null(
    monkeypatch,
) -> None:
    """New MySQL source columns are used when old master columns exist but are NULL."""
    payload, _calls = _load_payload_module(monkeypatch)
    cursor = _FakeCursor()

    def _fetchone() -> dict[str, Any]:
        return {
            "Master_Host": None,
            "Source_Host": "primary.example",
            "Master_Port": None,
            "Source_Port": 3307,
            "Master_Server_Id": None,
            "Source_Server_Id": 99,
            "Master_UUID": None,
            "Source_UUID": "source-uuid",
            "Slave_IO_Running": None,
            "Replica_IO_Running": "Yes",
            "Slave_SQL_Running": None,
            "Replica_SQL_Running": "Yes",
            "Seconds_Behind_Master": None,
            "Seconds_Behind_Source": 3,
            "Auto_Position": 1,
        }

    cursor.fetchone = _fetchone

    repl = payload._query_repl_info(cursor)

    assert repl["source_host"] == "primary.example"
    assert repl["source_port"] == 3307
    assert repl["source_server_id"] == 99
    assert repl["source_uuid"] == "source-uuid"
    assert repl["seconds_behind"] == 3
    assert repl["repl_status"] == "ok"


def test_query_server_info_rejects_empty_identity_row(monkeypatch) -> None:
    """Empty identity query results become host_error instead of mostly-null nodes."""
    payload, _calls = _load_payload_module(monkeypatch)
    cursor = _FakeCursor()
    cursor.fetchone = lambda: None

    with pytest.raises(payload.pymysql.MySQLError, match="Server identity query"):
        payload._query_server_info(cursor)
