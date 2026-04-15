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

"""Define the payload for database connectivity check tasks.

This script runs on a Nomad client node. It receives a ``--config`` JSON
argument, connects to the target database, and prints a JSON result to stdout.
"""

import argparse
import contextlib
import json
import sys


def check_mysql(host: str, port: int) -> dict[str, bool | str]:
    """Check MySQL connectivity via ``SELECT 1``.

    :param host: The database host address.
    :type host: str
    :param port: The database port number.
    :type port: int
    :return: A dict with ``success`` and optionally ``error``.
    :rtype: dict[str, bool | str]
    """
    import myloginpath
    import pymysql

    connect_kwargs = {"host": host, "port": port, "connect_timeout": 10}
    with contextlib.suppress(Exception):
        login = myloginpath.parse("client")
        connect_kwargs["user"] = login.get("user")
        connect_kwargs["password"] = login.get("password")

    try:
        conn = pymysql.connect(**connect_kwargs)
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
            return {"success": True}
        finally:
            conn.close()
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def check_postgresql(host: str, port: int) -> dict[str, bool | str]:
    """Check PostgreSQL connectivity via ``SELECT 1``.

    :param host: The database host address.
    :type host: str
    :param port: The database port number.
    :type port: int
    :return: A dict with ``success`` and optionally ``error``.
    :rtype: dict[str, bool | str]
    """
    import psycopg2

    try:
        conn = psycopg2.connect(host=host, port=port, connect_timeout=10)
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
            return {"success": True}
        finally:
            conn.close()
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def check_mongodb(host: str, port: int) -> dict[str, bool | str]:
    """Check MongoDB connectivity via the ``ping`` command.

    :param host: The database host address.
    :type host: str
    :param port: The database port number.
    :type port: int
    :return: A dict with ``success`` and optionally ``error``.
    :rtype: dict[str, bool | str]
    """
    import pymongo

    try:
        client = pymongo.MongoClient(
            host=host, port=port, serverSelectionTimeoutMS=10000
        )
        try:
            client.admin.command("ping")
            return {"success": True}
        finally:
            client.close()
    except Exception as exc:
        return {"success": False, "error": str(exc)}


CHECKERS = {
    "mysql": check_mysql,
    "postgresql": check_postgresql,
    "mongodb": check_mongodb,
}


def main() -> None:
    """Parse the config file and run the appropriate database checker.

    The ``--config`` argument is a path to a file containing the JSON
    configuration (written by Nomad from the ``NOMAD_META_config`` env var),
    not an inline JSON string.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    with open(args.config) as config_file:
        config = json.load(config_file)
    checker = CHECKERS[config["service_type"]]
    result = checker(config["host"], config["port"])
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
