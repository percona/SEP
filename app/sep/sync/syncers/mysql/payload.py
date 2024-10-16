"""Define the payload for MySQL Sync tasks."""

import argparse
import json
import sys
from collections.abc import Sequence

import pymysql
from pymysql.cursors import Cursor


def get_table(cursor: Cursor, db_name: str, table_name: str) -> dict[str, str]:
    """Retrieve the CREATE statement for a specific table.

    Execute the `SHOW CREATE TABLE` command to obtain the creation statement
    of the specified table within a given database.

    :param cursor: The database cursor to execute queries.
    :type cursor: Cursor
    :param db_name: The name of the database containing the table.
    :type db_name: str
    :param table_name: The name of the table to retrieve the CREATE statement for.
    :type table_name: str
    :return: A dictionary containing the table name and its CREATE statement.
    :rtype: dict[str, str]
    """
    cursor.execute(f"SHOW CREATE TABLE `{db_name}`.`{table_name}`;")
    create_table_result = cursor.fetchone()
    return {"name": table_name, "create": create_table_result[1]}


def get_schema(cursor: Cursor, db_name: str) -> dict[str, str]:
    """Retrieve all tables and their CREATE statements for a specific schema.

    Fetch all table names within the specified database and obtain their
    corresponding CREATE statements.

    :param cursor: The database cursor to execute queries.
    :type cursor: Cursor
    :param db_name: The name of the database to retrieve the schema for.
    :type db_name: str
    :return: A dictionary containing the schema name and a list of its tables.
    :rtype: dict[str, any]
    """
    schema = {"name": db_name, "tables": []}
    cursor.execute(f"SHOW TABLES FROM `{db_name}`;")
    tables = cursor.fetchall()
    for table in tables:
        table_name = table[0]
        schema["tables"].append(
            get_table(
                cursor,
                db_name,
                table_name,
            ),
        )
    return schema


def get_all_schemas(
    cursor: Cursor,
    ignored_databases: Sequence[str],
) -> list[dict[str, str]]:
    """Retrieve all schemas excluding specified databases.

    Fetch all databases from the MySQL server, exclude the ones specified in
    `ignored_databases`, and retrieve their respective schemas.

    :param cursor: The database cursor to execute queries.
    :type cursor: Cursor
    :param ignored_databases: A sequence of database names to ignore.
    :type ignored_databases: Sequence[str]
    :return: A list of dictionaries, each containing a schema's name and its tables.
    :rtype: list[dict[str, any]]
    """
    schemas = []
    cursor.execute("SHOW DATABASES;")
    databases = cursor.fetchall()
    for db in databases:
        db_name = db[0]
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
        "--host",
        action="append",
        required=True,
        help="Host in the format address[:port]",
    )
    parser.add_argument(
        "-i",
        "--ignore",
        action="append",
        default=[],
        help="Database names to ignore",
    )
    parser.add_argument(
        "--schema",
        help="Name of the database to fetch create table statements for",
    )
    parser.add_argument(
        "--table",
        help="Name of the table to fetch create statement for",
    )

    args = parser.parse_args()
    if args.table and not args.schema:
        sys.exit("--schema must be passed along with --table")
    if args.schema and len(args.host) > 1:
        sys.exit("Only one host allowed if --schema is specified")

    result = {}
    for host_entry in args.host:
        host, port = parse_host_port(host_entry)
        try:
            with (
                pymysql.connect(
                    host=host,
                    port=port,
                ) as connection,
                connection.cursor() as cursor,
            ):
                if args.table:
                    print(
                        json.dumps(
                            get_table(
                                cursor,
                                args.schema,
                                args.table,
                            ),
                        ),
                    )
                    return
                if args.schema:
                    print(
                        json.dumps(
                            get_schema(
                                cursor,
                                args.schema,
                            ),
                        ),
                    )
                    return
                result[host_entry] = get_all_schemas(cursor, args.ignore)
        except pymysql.MySQLError as e:
            print(f"Error connecting to {host}:{port} - {e}", file=sys.stderr)

    print(json.dumps(result))


if __name__ == "__main__":
    main()
