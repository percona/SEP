# Copyright (C) 2025 Percona LLC
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

"""Define the payload for MySQL Sync tasks."""

import argparse
import hashlib
import json
import os
import socket
import string
import sys
from collections import defaultdict
from collections.abc import Generator, Iterable
from gzip import GzipFile
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import quote

import myloginpath
import pymysql
from pymysql.cursors import DictCursor

SAFE_FILENAME_CHARS = string.ascii_letters + string.digits + "._-"


def format_filename(
    name: str,
    suffix: str = "",
    safe_chars: str = SAFE_FILENAME_CHARS,
    max_length: int = 255,
) -> str:
    """Format a filename by escaping unsafe characters and ensuring length limits.

    This function escapes unsafe characters in the provided name using URL
    encoding, appends the specified suffix, and ensures that the total length
    does not exceed the maximum length. If it does, a SHA-1 hash of the
    original name is appended to ensure uniqueness.

    :param name: The original name to be formatted.
    :type name: str
    :param suffix: The suffix to append to the formatted name. Defaults to an empty
        string.
    :type suffix: str
    :param safe_chars: A string of characters that should not be escaped. Defaults to
        alphanumeric characters, dot, underscore, and hyphen.
    :type safe_chars: str
    :param max_length: The maximum allowed length for the final filename. Defaults to
        255 characters.
    :type max_length: int
    :return: The formatted filename.
    :rtype: str
    """
    escaped_name = quote(name, safe=safe_chars)
    if len(escaped_name + suffix) > max_length:
        hashed_name = hashlib.sha1(
            name.encode("utf8"), usedforsecurity=False
        ).hexdigest()
        return f"{escaped_name[: max_length - len(suffix) - len(hashed_name) - 1]}-{hashed_name}{suffix}"
    return f"{escaped_name}{suffix}"


def atomic_write_gzip_json(
    obj_iter: Iterable[dict[str, Any]], out_path: Path, *, compresslevel: int = 6
) -> dict[str, int]:
    """Write lines to a gzip-compressed file atomically.

    Write JSON lines from the provided iterable to a gzip-compressed file at the
    specified output path. The write operation is atomic, ensuring that the
    file is either fully written or not written at all.

    :param obj_iter: An iterable of dictionaries to write as JSON lines.
    :type obj_iter: Iterable[dict[str, Any]]
    :param out_path: The path to the output gzip-compressed file.
    :type out_path: Path
    :param compresslevel: The compression level for the gzip file. Defaults to 6.
    :type compresslevel: int
    :return: A dictionary containing the number of lines written and the size of
        the output file in bytes.
    :rtype: dict[str, int]
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with (
        NamedTemporaryFile(dir=out_path.parent, delete=False) as tmp,
        GzipFile(filename="", fileobj=tmp, mode="wb", compresslevel=compresslevel, mtime=0) as gz,
    ):
        for obj in obj_iter:
            gz.write(json.dumps(obj, separators=(",", ":")).encode("utf8") + b"\n")
            total += 1
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_name = tmp.name
    os.replace(tmp_name, out_path)
    dfd = os.open(out_path.parent, os.O_DIRECTORY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)
    return {"lines": total, "bytes": out_path.stat().st_size}


def get_table(cursor: DictCursor, db_name: str, table_name: str) -> dict[str, Any]:
    """Retrieve the CREATE statement and key information for a specific table.

    Execute the SHOW CREATE TABLE command to obtain the creation statement
    of the specified table within a given database. Extracts the primary key
    and unique keys using the SHOW KEYS command.

    :param cursor: The database cursor to execute queries.
    :type cursor: DictCursor
    :param db_name: The name of the database containing the table.
    :type db_name: str
    :param table_name: The name of the table to retrieve the CREATE statement for.
    :type table_name: str
    :return: A dictionary containing:
             - "name" (str): The name of the table.
             - "create" (str): The CREATE TABLE SQL statement.
             - "keys" (dict): A dictionary describing the keys.
    :rtype: dict[str, Any]
    """
    query = "SHOW CREATE TABLE `{}`.`{}`".format(
        db_name.replace("`", "``"),
        table_name.replace("`", "``"),
    )
    cursor.execute(query)
    create_table_result = cursor.fetchone()
    create_statement = create_table_result["Create Table"]

    cursor.execute(
        "SELECT `INDEX_NAME`, `COLUMN_NAME`, `NON_UNIQUE`, `NULLABLE` FROM "
        "`INFORMATION_SCHEMA`.`STATISTICS` WHERE `TABLE_SCHEMA` = %s AND `TABLE_NAME` = %s",
        (db_name, table_name),
    )
    keys = cursor.fetchall()

    keys_dict = {}

    for row in keys:
        key_name = row["INDEX_NAME"]

        if key_name not in keys_dict:
            keys_dict[key_name] = {
                "type": "PRIMARY" if key_name == "PRIMARY" else "INDEX",
                "columns": [],
                "unique": not bool(int(row.get("NON_UNIQUE", 0))),
                "nullable": row.get("NULLABLE", "NO").upper() == "YES",
            }

        keys_dict[key_name]["columns"].append(row["COLUMN_NAME"])

    return {"name": table_name, "create": create_statement, "keys": keys_dict}


def iter_tables(cursor: DictCursor, db_name: str) -> Generator[dict[str, str]]:
    """Yield all tables and their CREATE statements for a specific schema.

    Fetch all table names within the specified database and obtain their
    corresponding CREATE statements.

    :param cursor: The database cursor to execute queries.
    :type cursor: DictCursor
    :param db_name: The name of the database to retrieve the schema for.
    :type db_name: str
    :yield: A dictionary containing the name and CREATE statement of each table.
    :rtype: dict[str, any]
    """
    cursor.execute(
        "SELECT `TABLE_NAME` FROM `INFORMATION_SCHEMA`.`TABLES` WHERE "
        "`TABLE_SCHEMA` = %s AND `TABLE_TYPE` = 'BASE TABLE'",
        (db_name),
    )
    for table in cursor.fetchall():
        yield get_table(
            cursor,
            db_name,
            table["TABLE_NAME"],
        )


def iter_schemas(
    cursor: DictCursor,
    ignored_databases: Iterable[str],
) -> Generator[dict[str, str]]:
    """Yield schemas excluding specified databases.

    Fetch all databases from the MySQL server, exclude the ones specified in
    `ignored_databases`, and retrieve their data.

    :param cursor: The database cursor to execute queries.
    :type cursor: DictCursor
    :param ignored_databases: A sequence of database names to ignore.
    :type ignored_databases: Iterable[str]
    :yield: A dictionary containing the name of each schema.
    :rtype: Generator[dict[str, str]]
    """
    cursor.execute("SHOW DATABASES")
    for db in cursor.fetchall():
        db_name = db["Database"]
        if db_name not in ignored_databases:
            yield {"name": db_name}


def parse_host_port(host_entry: str) -> tuple[str, int]:
    """Parse a host entry into host and port components.

    Split the host entry string into its host and port parts. If the port is
    not specified, default to port 3306.

    :param host_entry: The host entry in the format 'address[:port]'.
    :type host_entry: str
    :return: A tuple containing the host address and port number.
    :rtype: tuple[str, int]
    """
    if ":" in host_entry:
        host, port = host_entry.split(":")
        port = int(port)
    else:
        host = host_entry
        port = 3306
    return host, port


def main() -> None:
    """Define main function to parse arguments and initiate the retrieval of data."""
    parser = argparse.ArgumentParser(
        description="Fetch MySQL create table statements from multiple hosts.",
    )
    parser.add_argument(
        "-c",
        "--config",
        required=True,
        help="Path to JSON config file",
        type=Path,
    )

    args = parser.parse_args()
    with args.config.open() as config_file:
        config = json.load(config_file)

    table = config.get("table")
    schema = config.get("schema")
    hosts = config.get("hosts", [])

    if table and not schema:
        sys.exit("schema must be passed along with table")
    if schema and len(hosts) > 1:
        sys.exit("Only one host allowed if schema is specified")

    # Try to read creds from .mylogin.cnf
    try:
        creds = myloginpath.parse("client")
    except Exception:
        creds = {}

    result = defaultdict(dict)

    local_ip = socket.gethostbyname(socket.gethostname())

    if schema:
        host_entry = hosts.pop()
        host, port = parse_host_port(host_entry)
        if config.get("resolve_localhost") and host == local_ip:
            host = "127.0.0.1"
        try:
            with (
                pymysql.connect(
                    host=host,
                    port=port,
                    user=creds.get("user"),
                    password=creds.get("password"),
                    read_default_file="~/.my.cnf",
                ) as connection,
                connection.cursor(DictCursor) as cursor,
            ):
                if table:
                    result["tables"][f"{host_entry}/{schema}.{table}"] = get_table(
                        cursor, schema, table
                    )
                elif schema:
                    tables_path = Path(
                        format_filename(f"{schema}_tables", ".ndjson.gz")
                    )
                    tables_stats = atomic_write_gzip_json(
                        iter_tables(cursor, schema), tables_path
                    )
                    result["schemas"][f"{host_entry}/{schema}"] = {
                        "name": schema,
                        "tables_path": str(tables_path),
                        "tables_count": tables_stats["lines"],
                    }
        except pymysql.MySQLError as err:
            print(f"Error connecting to {host}:{port} - {err}", file=sys.stderr)
            sys.exit(2)

    for host_entry in hosts:
        host, port = parse_host_port(host_entry)
        if config.get("resolve_localhost") and host == local_ip:
            host = "127.0.0.1"

        try:
            with (
                pymysql.connect(
                    host=host,
                    port=port,
                    user=creds.get("user"),
                    password=creds.get("password"),
                    read_default_file="~/.my.cnf",
                ) as connection,
                connection.cursor(DictCursor) as cursor,
            ):
                service_dir = Path(format_filename(host_entry))
                schema_iter = (
                    [schema]
                    if schema
                    else iter_schemas(cursor, config.get("ignore_schemas", []))
                )

                def schema_lines() -> Generator[dict[str, Any]]:
                    for db in schema_iter:
                        schema_name = db["name"]
                        tables_path = service_dir / format_filename(
                            f"{schema_name}_tables", ".ndjson.gz"
                        )
                        tables_stats = atomic_write_gzip_json(
                            iter_tables(cursor, db["name"]), tables_path
                        )
                        yield {
                            **db,
                            "tables_path": str(tables_path),
                            "tables_count": tables_stats["lines"],
                        }

                schemas_path = service_dir / "schemas.ndjson.gz"
                schemas_stats = atomic_write_gzip_json(schema_lines(), schemas_path)
                result["services"][host_entry] = {
                    "schemas_path": str(schemas_path),
                    "schemas_count": schemas_stats["lines"],
                }
        except pymysql.MySQLError as err:
            print(f"Error connecting to {host}:{port} - {err}", file=sys.stderr)

    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
