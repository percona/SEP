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

"""Define the payload for system facts Sync tasks.

This standalone script runs on the executor host via the ``run-python`` task. It
collects best-effort host facts (OS version, installed packages, EOL-relevant config)
when co-located with the node, and the database engine version for each requested
service, emitting a single JSON document to stdout::

    {"host": {...} | null, "services": {"<address>": {"db_engine_version", "collected_at"}}}

Every collection step is best-effort: a failure to read a host fact or reach a single
service is logged to stderr and that key is omitted -- the script never raises and always
exits cleanly so a partial collection still produces a usable snapshot.

Database drivers (``pymysql``, ``psycopg``, ``pymongo``) and ``myloginpath`` are imported
lazily inside their collectors so the module imports without them present.
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from configparser import Error as ConfigParserError, RawConfigParser
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

#: Path to the OS release file (module-level so tests can redirect it).
OS_RELEASE_PATH = Path("/etc/os-release")
#: Host fact fields that constitute a meaningful host observation.
HOST_FIELDS = ("os_version", "installed_packages", "config")
#: Seconds to wait when connecting to a database service.
DB_CONNECT_TIMEOUT = 10
#: Seconds to wait for a package-manager query to complete.
PKG_QUERY_TIMEOUT = 60
#: Default port per engine when a service address omits one.
DEFAULT_PORTS = {"mysql": 3306, "postgresql": 5432, "mongodb": 27017}


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string.

    :return: The current UTC timestamp.
    :rtype: str
    """
    return datetime.now(UTC).isoformat()


def parse_host_port(host_entry: str, default_port: int = 3306) -> tuple[str, int]:
    """Split a ``host[:port]`` entry into host and port components.

    :param host_entry: The address in ``host`` or ``host:port`` form.
    :type host_entry: str
    :param default_port: The port to use when none is present. Defaults to 3306.
    :type default_port: int
    :return: A tuple of ``(host, port)``.
    :rtype: tuple[str, int]
    """
    if ":" in host_entry:
        host, _, port = host_entry.rpartition(":")
        try:
            return host, int(port)
        except ValueError:
            return host_entry, default_port
    return host_entry, default_port


def _read_os_release() -> dict[str, str]:
    """Parse ``/etc/os-release`` into a key/value mapping.

    :return: The parsed os-release fields, or an empty mapping if unavailable.
    :rtype: dict[str, str]
    """
    try:
        content = OS_RELEASE_PATH.read_text(encoding="utf-8")
    except OSError:
        return {}
    data: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip().strip('"')
    return data


def collect_os_version() -> str | None:
    """Collect the operating system version from ``/etc/os-release``.

    :return: A human-readable OS version, or ``None`` if it cannot be determined.
    :rtype: str | None
    """
    data = _read_os_release()
    if pretty_name := data.get("PRETTY_NAME"):
        return pretty_name
    name = data.get("NAME")
    version = data.get("VERSION_ID") or data.get("VERSION")
    if name and version:
        return f"{name} {version}"
    return name or None


def collect_installed_packages() -> list[dict[str, str]] | None:
    """Collect installed packages via the host package manager.

    Uses ``rpm`` or ``dpkg-query`` with a fixed argument vector (never a shell), guarded
    by :func:`shutil.which`. Returns ``None`` when no package manager is available or the
    query fails.

    :return: A list of ``{"name", "version"}`` dicts, or ``None``.
    :rtype: list[dict[str, str]] | None
    """
    if shutil.which("rpm"):
        cmd = ["rpm", "-qa", "--queryformat", "%{NAME}\t%{VERSION}-%{RELEASE}\n"]
    elif shutil.which("dpkg-query"):
        cmd = ["dpkg-query", "-W", "-f=${Package}\t${Version}\n"]
    else:
        return None
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
            cmd,
            capture_output=True,
            text=True,
            timeout=PKG_QUERY_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as err:
        print(f"Failed to query installed packages: {err}", file=sys.stderr)
        return None
    if proc.returncode != 0:
        print(f"Package query exited with {proc.returncode}", file=sys.stderr)
        return None
    packages = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        name, _, version = line.partition("\t")
        if name:
            packages.append({"name": name.strip(), "version": version.strip()})
    return packages or None


def collect_host_config() -> dict[str, Any]:
    """Collect EOL-relevant host configuration (kernel, architecture, OS identity).

    :return: A mapping of config keys to values (empty values omitted).
    :rtype: dict[str, Any]
    """
    os_release = _read_os_release()
    config = {
        "kernel": platform.release(),
        "arch": platform.machine(),
        "os_id": os_release.get("ID"),
        "os_version_id": os_release.get("VERSION_ID"),
    }
    return {key: value for key, value in config.items() if value}


def collect_host_facts() -> dict[str, Any]:
    """Collect all host-level facts, each best-effort.

    :return: A mapping always carrying ``collected_at`` plus any gathered host fields.
    :rtype: dict[str, Any]
    """
    facts: dict[str, Any] = {"collected_at": _now_iso()}
    if os_version := collect_os_version():
        facts["os_version"] = os_version
    if packages := collect_installed_packages():
        facts["installed_packages"] = packages
    if config := collect_host_config():
        facts["config"] = config
    return facts


def _mysql_creds(address: str) -> dict[str, str]:
    """Resolve MySQL credentials from ``~/.mylogin.cnf`` by matching host and port.

    :param address: The service address in ``host[:port]`` form.
    :type address: str
    :return: A mapping with ``user``/``password`` keys, or an empty mapping.
    :rtype: dict[str, str]
    """
    import myloginpath

    try:
        content = myloginpath.read()
    except (OSError, TypeError) as err:
        print(f"Cannot read login path file: {err}", file=sys.stderr)
        return {}
    if not isinstance(content, str):
        return {}
    parser = RawConfigParser(allow_no_value=True)
    try:
        parser.read_string(content, source=".mylogin.cnf")
    except ConfigParserError as err:
        print(f"Failed to parse login path file: {err}", file=sys.stderr)
        return {}

    def _creds(section: str) -> dict[str, str]:
        items = dict(parser.items(section))
        return {
            "user": (items.get("user") or "").strip('"'),
            "password": (items.get("password") or "").strip('"'),
            "host": (items.get("host") or "").strip('"'),
            "port": items.get("port", "3306"),
        }

    target_host, target_port = parse_host_port(address, default_port=3306)
    for section in parser.sections():
        data = _creds(section)
        if data["host"] == target_host and int(data["port"]) == target_port:
            return data
    if parser.has_section("client"):
        return _creds("client")
    return {}


def _collect_mysql_version(address: str) -> str | None:
    """Connect to a MySQL service and return its engine version.

    :param address: The service address in ``host[:port]`` form.
    :type address: str
    :return: The MySQL version string, or ``None``.
    :rtype: str | None
    """
    import pymysql

    creds = _mysql_creds(address)
    host, port = parse_host_port(address, default_port=DEFAULT_PORTS["mysql"])
    with pymysql.connect(
        host=host,
        port=port,
        user=creds.get("user") or None,
        password=creds.get("password") or None,
        connect_timeout=DB_CONNECT_TIMEOUT,
        read_timeout=DB_CONNECT_TIMEOUT,
    ) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT VERSION()")
        row = cursor.fetchone()
    return row[0] if row else None


def _collect_postgresql_version(address: str) -> str | None:
    """Connect to a PostgreSQL service and return its engine version.

    Authenticates via ``~/.pgpass`` and standard ``PG*`` environment variables.

    :param address: The service address in ``host[:port]`` form.
    :type address: str
    :return: The PostgreSQL ``server_version``, or ``None``.
    :rtype: str | None
    """
    import psycopg

    host, port = parse_host_port(address, default_port=DEFAULT_PORTS["postgresql"])
    conninfo: dict[str, Any] = {
        "host": host,
        "port": port,
        "dbname": os.environ.get("PGDATABASE", "postgres"),
        "connect_timeout": DB_CONNECT_TIMEOUT,
    }
    if user := os.environ.get("PGUSER"):
        conninfo["user"] = user
    with psycopg.connect(**conninfo) as connection, connection.cursor() as cursor:
        cursor.execute("SHOW server_version")
        row = cursor.fetchone()
    return row[0] if row else None


def _collect_mongodb_version(address: str) -> str | None:
    """Connect to a MongoDB service and return its engine version.

    Uses a connection URI from ``SEP_MONGO_URI``/``MONGO_URI`` when set, otherwise the
    service host and port directly.

    :param address: The service address in ``host[:port]`` form.
    :type address: str
    :return: The MongoDB ``buildInfo`` version, or ``None``.
    :rtype: str | None
    """
    import pymongo

    timeout_ms = DB_CONNECT_TIMEOUT * 1000
    if uri := (os.environ.get("SEP_MONGO_URI") or os.environ.get("MONGO_URI")):
        client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=timeout_ms)
    else:
        host, port = parse_host_port(address, default_port=DEFAULT_PORTS["mongodb"])
        client = pymongo.MongoClient(
            host=host, port=port, serverSelectionTimeoutMS=timeout_ms
        )
    try:
        info = client.admin.command("buildInfo")
    finally:
        client.close()
    return info.get("version")


def collect_service_version(address: str, service_type: str) -> str | None:
    """Collect the database engine version for a service, best-effort.

    Dispatches to the per-engine collector by service type. Any failure (missing creds,
    unavailable driver, unreachable host) is logged and yields ``None`` so siblings and
    host facts are unaffected.

    :param address: The service address in ``host[:port]`` form.
    :type address: str
    :param service_type: The engine type (``mysql``/``postgresql``/``mongodb``).
    :type service_type: str
    :return: The engine version string, or ``None``.
    :rtype: str | None
    """
    try:
        if service_type == "mysql":
            return _collect_mysql_version(address)
        if service_type == "postgresql":
            return _collect_postgresql_version(address)
        if service_type == "mongodb":
            return _collect_mongodb_version(address)
    except Exception as err:  # noqa: BLE001 - best-effort collection, never fatal
        print(
            f"Failed to collect version for {address} ({service_type}): {err}",
            file=sys.stderr,
        )
    return None


def main() -> None:
    """Parse the config, collect facts, and emit one JSON document to stdout."""
    parser = argparse.ArgumentParser(
        description="Collect host and service system facts.",
    )
    parser.add_argument(
        "-c",
        "--config",
        required=True,
        help="Path to JSON config file",
        type=Path,
    )
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))

    result: dict[str, Any] = {"host": None, "services": {}}

    if config.get("collect_host"):
        facts = collect_host_facts()
        if any(facts.get(field) for field in HOST_FIELDS):
            result["host"] = facts

    for service in config.get("services", []):
        address = service.get("address")
        service_type = service.get("type")
        if not address:
            continue
        if version := collect_service_version(address, service_type):
            result["services"][address] = {
                "db_engine_version": version,
                "collected_at": _now_iso(),
            }

    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
