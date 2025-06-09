"""Define the payload for MySQL Sync tasks."""

import argparse
import json
import socket
import sys
from collections.abc import Sequence
from pathlib import Path

import pymysql
from pymysql.cursors import DictCursor


def get_table(cursor: DictCursor, db_name: str, table_name: str) -> dict:
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
    :rtype: dict
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


def get_schema(cursor: DictCursor, db_name: str) -> dict[str, str]:
    """Retrieve all tables and their CREATE statements for a specific schema.

    Fetch all table names within the specified database and obtain their
    corresponding CREATE statements.

    :param cursor: The database cursor to execute queries.
    :type cursor: DictCursor
    :param db_name: The name of the database to retrieve the schema for.
    :type db_name: str
    :return: A dictionary containing the schema name and a list of its tables.
    :rtype: dict[str, any]
    """
    schema = {"name": db_name, "tables": []}
    cursor.execute(
        "SELECT `TABLE_NAME` FROM `INFORMATION_SCHEMA`.`TABLES` WHERE "
        "`TABLE_SCHEMA` = %s AND `TABLE_TYPE` = 'BASE TABLE'",
        (db_name),
    )
    tables = cursor.fetchall()
    for table in tables:
        schema["tables"].append(
            get_table(
                cursor,
                db_name,
                table["TABLE_NAME"],
            ),
        )
    return schema


def get_all_schemas(
    cursor: DictCursor,
    ignored_databases: Sequence[str],
) -> list[dict[str, str]]:
    """Retrieve all schemas excluding specified databases.

    Fetch all databases from the MySQL server, exclude the ones specified in
    `ignored_databases`, and retrieve their respective schemas.

    :param cursor: The database cursor to execute queries.
    :type cursor: DictCursor
    :param ignored_databases: A sequence of database names to ignore.
    :type ignored_databases: Sequence[str]
    :return: A list of dictionaries, each containing a schema's name and its tables.
    :rtype: list[dict[str, any]]
    """
    schemas = []
    cursor.execute("SHOW DATABASES")
    databases = cursor.fetchall()
    for db in databases:
        db_name = db["Database"]
        if db_name in ignored_databases:
            continue
        schemas.append(get_schema(cursor, db_name))
    return schemas


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

    result = {}
    local_ip = socket.gethostbyname(socket.gethostname())
    for host_entry in hosts:
        host, port = parse_host_port(host_entry)
        if config.get("resolve_localhost") and host == local_ip:
            host = "127.0.0.1"
        try:
            with (
                pymysql.connect(
                    host=host,
                    port=port,
                    read_default_file='~/.my.cnf',
                ) as connection,
                connection.cursor(DictCursor) as cursor,
            ):
                if table:
                    print(
                        json.dumps(
                            get_table(
                                cursor,
                                schema,
                                table,
                            ),
                        ),
                    )
                    return
                if schema:
                    print(
                        json.dumps(
                            get_schema(
                                cursor,
                                schema,
                            ),
                        ),
                    )
                    return
                result[host_entry] = get_all_schemas(
                    cursor,
                    config.get("ignore_schemas", []),
                )
        except pymysql.MySQLError as e:
            print(f"Error connecting to {host}:{port} - {e}", file=sys.stderr)

    print(json.dumps(result))


if __name__ == "__main__":
    main()
