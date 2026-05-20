#!/usr/bin/env python3
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

"""Collect MySQL replication topology data.

Runs on an executor host via the Tasks API ``run-python`` task. Reads a JSON
config (host list + per-host options), queries each MySQL instance
concurrently with ``pymysql``, and emits one NDJSON line per host to
stdout as soon as that host finishes. The SEP backend tails this stream
in real time so the React Flow graph renders progressively.

NDJSON event shapes::

    {"event":"host_done","host":"host:port","data":{...}}
    {"event":"host_error","host":"host:port","error":"msg"}
    {"event":"complete","ok":N,"err":N}
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from configparser import Error as ConfigParserError, RawConfigParser
from pathlib import Path
from typing import Any

import myloginpath
import pymysql
from pymysql.cursors import DictCursor

# Standalone payload: cannot import from app.* because it runs in an isolated executor venv.
DEFAULT_MYSQL_PORT = 3306
DEFAULT_CONNECT_TIMEOUT = 5
DEFAULT_READ_TIMEOUT = 10
DEFAULT_MAX_WORKERS = 16


def parse_host_port(host_entry: str) -> tuple[str, int]:
    """Split a ``host[:port]`` entry into host and port.

    :param host_entry: Host entry from the payload config. May include an
        explicit port suffix. Inventory currently supplies IPv4/hostname
        entries; bare IPv6 literals are not supported here.
    :type host_entry: str
    :return: Hostname/address plus parsed port, falling back to
        :data:`DEFAULT_MYSQL_PORT` when no valid port is supplied.
    :rtype: tuple[str, int]
    """
    if ":" in host_entry:
        host, port_str = host_entry.rsplit(":", 1)
        try:
            return host, int(port_str)
        except ValueError:
            return host, DEFAULT_MYSQL_PORT
    return host_entry, DEFAULT_MYSQL_PORT


def _strip_quotes(value: str) -> str:
    """Remove mylogin-path wrapping quotes from a config value.

    :param value: Raw value read from the login-path config parser.
    :type value: str
    :return: Unquoted string value.
    :rtype: str
    """
    if not isinstance(value, str):
        return str(value)
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value[1:-1].replace('\\"', '"')
    return value


def _section_to_creds(parser: RawConfigParser, section: str) -> dict[str, Any] | None:
    """Convert one login-path section into PyMySQL credential kwargs.

    :param parser: Parsed ``~/.mylogin.cnf`` content.
    :type parser: RawConfigParser
    :param section: Section name to read.
    :type section: str
    :return: Credential mapping, or ``None`` when the section is malformed.
    :rtype: dict[str, Any] | None
    """
    try:
        data = {k: _strip_quotes(v) for k, v in parser.items(section)}
        data["port"] = int(data["port"]) if "port" in data else DEFAULT_MYSQL_PORT
        return data
    except (ValueError, KeyError):
        return None


def get_creds_for_host(host_entry: str) -> dict[str, Any]:
    """Return credentials from ``~/.mylogin.cnf`` matching ``host[:port]``.

    Falls back to ``[client]`` when no host/port match exists.

    :param host_entry: Host entry from the payload config.
    :type host_entry: str
    :return: PyMySQL credential kwargs. Empty when login-path data is missing,
        unreadable, malformed, or has no matching section.
    :rtype: dict[str, Any]
    """
    try:
        content = myloginpath.read()
    except (OSError, TypeError) as err:
        print(f"Cannot read login path file: {err}", file=sys.stderr)
        return {}
    if not isinstance(content, str):
        return {}
    parser = RawConfigParser(dict_type=dict, allow_no_value=True)
    try:
        parser.read_string(content, source=".mylogin.cnf")
    except ConfigParserError as err:
        print(f"Failed to parse login path file: {err}", file=sys.stderr)
        return {}
    target_host, target_port = parse_host_port(host_entry)
    for section in parser.sections():
        data = _section_to_creds(parser, section)
        if data is None or "host" not in data:
            continue
        if data["host"] == target_host and data["port"] == target_port:
            return data
    if parser.has_section("client"):
        data = _section_to_creds(parser, "client")
        if data is not None:
            return data
    return {}


def _query_server_info(cursor: DictCursor) -> dict[str, Any]:
    """Return basic MySQL server identity and read-only mode.

    :param cursor: Open PyMySQL dict cursor for the target instance.
    :type cursor: DictCursor
    :return: Server identity, version, binary logging, and read-only state.
    :rtype: dict[str, Any]
    :raises pymysql.MySQLError: When server identity queries return no rows.
    """
    try:
        cursor.execute(
            "SELECT SHA2(CONCAT(@@server_id, @@server_uuid, @@port), 256) AS server_hash, "
            "@@server_id AS server_id, @@server_uuid AS server_uuid, @@port AS port, "
            "@@super_read_only AS super_read_only, @@read_only AS read_only, "
            "@@version AS version, @@log_bin AS log_bin, @@hostname AS hostname"
        )
        row = cursor.fetchone()
    except pymysql.MySQLError:
        cursor.execute(
            "SELECT SHA2(CONCAT(@@server_id, @@hostname, @@port), 256) AS server_hash, "
            "@@server_id AS server_id, @@port AS port, "
            "@@read_only AS read_only, @@version AS version, "
            "@@log_bin AS log_bin, @@hostname AS hostname"
        )
        row = cursor.fetchone()
        if not row:
            raise pymysql.MySQLError("Server identity query returned no rows")

        # Legacy servers do not expose ``@@server_uuid`` or ``@@super_read_only``.
        # Reuse the stable fallback hash as a synthetic identity so downstream
        # topology correlation still has a per-host key on this compatibility path.
        row["server_uuid"] = row.get("server_hash")
        row["super_read_only"] = 0
    if not row:
        raise pymysql.MySQLError("Server identity query returned no rows")
    if row.get("super_read_only") == 1:
        read_only = "SR"
    elif row.get("read_only") == 1:
        read_only = "RO"
    else:
        read_only = "RW"
    return {
        "server_hash": row.get("server_hash"),
        "server_id": row.get("server_id"),
        "server_uuid": row.get("server_uuid"),
        "port": row.get("port"),
        "hostname": row.get("hostname"),
        "version": row.get("version"),
        "log_bin": "ON" if row.get("log_bin") == 1 else "OFF",
        "read_only": read_only,
    }


def _first_not_none(row: dict[str, Any], primary: str, fallback: str) -> Any:
    """Return the primary column value unless it is ``None``.

    :param row: Row from a MySQL status query.
    :type row: dict[str, Any]
    :param primary: Preferred column name.
    :type primary: str
    :param fallback: Fallback column name.
    :type fallback: str
    :return: Primary value when non-``None``; otherwise fallback value.
    :rtype: Any
    """
    value = row.get(primary)
    return value if value is not None else row.get(fallback)


def _query_repl_info(cursor: DictCursor) -> dict[str, Any]:
    """Return replication source info from MySQL replication status.

    :param cursor: Open PyMySQL dict cursor for the target instance.
    :type cursor: DictCursor
    :return: Replication source host/port/id, lag, thread state, filtering,
        and auto-position metadata. Returns ``{"source_host": None}`` when
        the instance is not a replica or status cannot be read.
    :rtype: dict[str, Any]
    """
    for query in ("SHOW REPLICA STATUS", "SHOW SLAVE STATUS"):
        try:
            cursor.execute(query)
        except pymysql.MySQLError:
            continue
        row = cursor.fetchone()
        if not row:
            return {"source_host": None}
        io = _first_not_none(row, "Replica_IO_Running", "Slave_IO_Running")
        sql = _first_not_none(row, "Replica_SQL_Running", "Slave_SQL_Running")
        repl_status = "ok" if (io == "Yes" and sql == "Yes") else "err"
        repl_filter = "yes" if any(
            row.get(k)
            for k in (
                "Replicate_Do_DB",
                "Replicate_Ignore_DB",
                "Replicate_Do_Table",
                "Replicate_Ignore_Table",
                "Replicate_Wild_Do_Table",
                "Replicate_Wild_Ignore_Table",
            )
        ) else "none"
        auto_position = _first_not_none(row, "Auto_Position", "Source_Auto_Position")
        return {
            "source_host": _first_not_none(row, "Master_Host", "Source_Host"),
            "source_port": _first_not_none(row, "Master_Port", "Source_Port"),
            "source_server_id": _first_not_none(
                row, "Master_Server_Id", "Source_Server_Id"
            ),
            "source_uuid": _first_not_none(row, "Master_UUID", "Source_UUID"),
            "io_running": io,
            "sql_running": sql,
            "seconds_behind": _first_not_none(
                row, "Seconds_Behind_Master", "Seconds_Behind_Source"
            ),
            "repl_status": repl_status,
            "repl_filter": repl_filter,
            "auto_position": auto_position if auto_position is not None else 0,
        }
    return {"source_host": None}


def _query_cluster_info(cursor: DictCursor) -> dict[str, Any]:
    """Return PXC cluster metadata for a target instance.

    :param cursor: Open PyMySQL dict cursor for the target instance.
    :type cursor: DictCursor
    :return: Cluster name, size, status, and local state. Empty when the
        instance is not in a wsrep cluster or cluster status cannot be read.
    :rtype: dict[str, Any]
    """
    try:
        cursor.execute(
            "SELECT IF(@@wsrep_provider='none','',@@wsrep_cluster_name) AS name"
        )
        row = cursor.fetchone() or {}
    except pymysql.MySQLError:
        return {}
    name = row.get("name") or ""
    if not name:
        return {}
    try:
        cursor.execute(
            "SHOW GLOBAL STATUS WHERE Variable_name IN "
            "('wsrep_local_state_comment','wsrep_cluster_size','wsrep_cluster_status')"
        )
        rows = cursor.fetchall() or []
    except pymysql.MySQLError:
        rows = []
    by_var = {r["Variable_name"]: r["Value"] for r in rows}
    return {
        "cluster_name": name,
        "cluster_size": by_var.get("wsrep_cluster_size", ""),
        "cluster_status": by_var.get("wsrep_cluster_status", ""),
        "local_state_comment": by_var.get("wsrep_local_state_comment", ""),
    }


def _query_gtid_mode(cursor: DictCursor) -> str:
    """Return the target instance GTID mode.

    :param cursor: Open PyMySQL dict cursor for the target instance.
    :type cursor: DictCursor
    :return: ``gtid_mode`` value, or empty string when unavailable.
    :rtype: str
    """
    try:
        cursor.execute("SHOW VARIABLES LIKE 'gtid_mode'")
        row = cursor.fetchone()
    except pymysql.MySQLError:
        return ""
    if not row:
        return ""
    return row.get("Value") or ""


def collect_host(
    host_entry: str,
    *,
    connect_timeout: int = DEFAULT_CONNECT_TIMEOUT,
    read_timeout: int = DEFAULT_READ_TIMEOUT,
    resolve_localhost: bool = False,
    local_ip: str | None = None,
) -> dict[str, Any]:
    """Collect topology data for one MySQL host.

    :param host_entry: Host entry from the payload config.
    :type host_entry: str
    :param connect_timeout: MySQL TCP connect timeout in seconds.
    :type connect_timeout: int
    :param read_timeout: MySQL read/write timeout in seconds.
    :type read_timeout: int
    :param resolve_localhost: Whether to rewrite the executor's own address to
        ``127.0.0.1`` before connecting.
    :type resolve_localhost: bool
    :param local_ip: Executor host IP used for localhost rewrite.
    :type local_ip: str | None
    :return: Per-host topology record with server, replication, cluster, and
        GTID metadata.
    :rtype: dict[str, Any]
    :raises pymysql.MySQLError: When MySQL connection or required identity
        queries fail.
    :raises OSError: When network connection setup fails.
    """
    host, port = parse_host_port(host_entry)
    target_host = host
    if resolve_localhost and local_ip and host == local_ip:
        target_host = "127.0.0.1"
    creds = get_creds_for_host(host_entry)
    conn_kwargs = {
        "host": target_host,
        "port": port,
        "user": creds.get("user"),
        "password": creds.get("password"),
        "read_default_file": str(Path("~/.my.cnf").expanduser()),
        "connect_timeout": connect_timeout,
        "read_timeout": read_timeout,
        "write_timeout": read_timeout,
    }
    with (
        pymysql.connect(**conn_kwargs) as conn,
        conn.cursor(DictCursor) as cursor,
    ):
        return {
            "host_entry": host_entry,
            "address": host,
            "port": port,
            "server": _query_server_info(cursor),
            "replication": _query_repl_info(cursor),
            "cluster": _query_cluster_info(cursor),
            "gtid_mode": _query_gtid_mode(cursor),
        }


def _emit(obj: dict[str, Any]) -> None:
    """Write one NDJSON event to stdout.

    :param obj: JSON-serializable event payload.
    :type obj: dict[str, Any]
    :return: ``None``.
    :rtype: None
    """
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def run(config: dict[str, Any]) -> int:
    """Run topology collection for all configured hosts.

    Emits one NDJSON event per completed host, followed by a ``complete`` event.

    :param config: Payload config containing ``hosts`` plus optional timeout,
        worker, and localhost-resolution settings.
    :type config: dict[str, Any]
    :return: Count of hosts that failed collection.
    :rtype: int
    """
    hosts: list[str] = list(config.get("hosts") or [])
    if not hosts:
        _emit({"event": "complete", "ok": 0, "err": 0})
        return 0
    max_workers = max(1, min(int(config.get("max_workers", DEFAULT_MAX_WORKERS)), 64))
    connect_timeout = int(config.get("connect_timeout", DEFAULT_CONNECT_TIMEOUT))
    read_timeout = int(config.get("read_timeout", DEFAULT_READ_TIMEOUT))
    resolve_localhost = bool(config.get("resolve_localhost", False))
    local_ip = None
    if resolve_localhost:
        try:
            local_ip = socket.gethostbyname(socket.gethostname())
        except OSError:
            local_ip = None
    ok = 0
    err = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                collect_host,
                host,
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
                resolve_localhost=resolve_localhost,
                local_ip=local_ip,
            ): host
            for host in hosts
        }
        for fut in as_completed(futures):
            host = futures[fut]
            try:
                _emit({"event": "host_done", "host": host, "data": fut.result()})
                ok += 1
            except (pymysql.MySQLError, OSError) as exc:
                _emit({"event": "host_error", "host": host, "error": str(exc)})
                err += 1
    _emit({"event": "complete", "ok": ok, "err": err})
    return err


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and run topology collection.

    :param argv: Optional argument vector for tests. Defaults to
        :data:`sys.argv` when ``None``.
    :type argv: list[str] | None
    :return: Process exit code. Non-zero means at least one host failed.
    :rtype: int
    """
    parser = argparse.ArgumentParser(description="MySQL replication topology collector")
    parser.add_argument("-c", "--config", required=True, type=Path)
    args = parser.parse_args(argv)
    with args.config.open() as fh:
        config = json.load(fh)
    return run(config)


if __name__ == "__main__":
    sys.exit(main())
