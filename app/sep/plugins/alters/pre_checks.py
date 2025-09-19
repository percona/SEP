#!/usr/bin/env python3
"""Pre-checks script for pt-online-schema-change operations.

This script performs various checks before executing pt-online-schema-change
against a MySQL table to ensure the operation can be safely performed.

Usage:
    python pre_checks.py --schema <database_name> --table <table_name> [options]
"""

import argparse
import logging
import shutil
import sys
from typing import Tuple, Union, Optional

import pymysql
from pymysql import Error as PyMySQLError
import os
from configparser import ConfigParser


class PreCheckError(Exception):
    """Custom exception for pre-check failures."""


class MySQLPreChecks:
    """Class to handle pre-checks for pt-online-schema-change operations."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 3306,
        user: str = None,
        password: str = None,
        schema: str = "",
        table: str = "",
        config_file: str = None,
    ) -> None:
        """Initialize the pre-checks class.

        Args:
            host: MySQL host
            port: MySQL port
            user: MySQL username
            password: MySQL password
            schema: Database name
            table: Table name
            config_file: Path to .my.cnf file

        """
        # Read .my.cnf configuration
        # cnf_config = self.read_my_cnf(config_file)

        # Use .my.cnf values as defaults, but allow command line to override
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.schema = schema
        self.table = table
        self.connection = None
        self.config_file = config_file
        # Setup logging
        self.setup_logging()

    def setup_logging(self) -> None:
        """Set up logging configuration."""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler(sys.stdout)],
        )
        self.logger = logging.getLogger(__name__)

    def connect_to_mysql(self) -> bool:
        """Establish connection to MySQL database.

        Returns:
            bool: True if connection successful, False otherwise

        """
        try:
            self.connection = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.schema,
                read_default_file=self.config_file,
                charset="utf8mb4",
            )
            self.logger.info("Successfully connected to MySQL at %s:%s", self.host, self.port)
            return True
        except PyMySQLError:
            self.logger.exception("Failed to connect to MySQL")
            return False

    def get_table_size_mb(self) -> Optional[float]:
        """Get the size of the table in MB.

        Returns:
            float: Table size in MB, or None if query fails

        """
        if not self.connection:
            self.logger.error("No MySQL connection available")
            return None

        query = """
        SELECT ROUND((data_length + index_length) / 1024 / 1024, 2)
        FROM information_schema.tables
        WHERE table_schema = %s AND table_name = %s
        """

        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query, (self.schema, self.table))
                result = cursor.fetchone()

                if result and result[0] is not None:
                    size_mb = float(result[0])
                    self.logger.info("Table %s.%s size: %s MB", self.schema, self.table, size_mb)
                    return size_mb
                self.logger.error("Table %s.%s not found or has no data", self.schema, self.table)
                return None

        except PyMySQLError:
            self.logger.exception("Failed to get table size")
            return None

    def get_mysql_datadir(self) -> Optional[str]:
        """Get the MySQL datadir path.

        Returns:
            str: MySQL datadir path, or None if query fails

        """
        if not self.connection:
            self.logger.error("No MySQL connection available")
            return None

        query = "SHOW VARIABLES LIKE 'datadir'"

        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query)
                result = cursor.fetchone()

                if result:
                    datadir = result[1]
                    self.logger.info("MySQL datadir: %s", datadir)
                    return datadir
                self.logger.error("Could not retrieve MySQL datadir")
                return None

        except PyMySQLError:
            self.logger.exception("Failed to get MySQL datadir")
            return None

    def get_disk_space_mb(self, path: str) -> Optional[Tuple[float, float]]:
        """Get free and total disk space for a given path.

        Args:
            path: Path to check disk space for

        Returns:
            tuple: (free_space_mb, total_space_mb) or None if failed

        """
        try:
            # Get disk usage statistics
            total, _, free = shutil.disk_usage(path)

            # Convert bytes to MB
            free_mb = free / (1024 * 1024)
            total_mb = total / (1024 * 1024)

            self.logger.info("Disk space for %s: %.2f MB free / %.2f MB total", path, free_mb, total_mb)
            return free_mb, total_mb

        except OSError:
            self.logger.exception("Failed to get disk space for %s", path)
            return None

    def check_disk_space(self) -> bool:
        """Check if there's enough free disk space in the MySQL datadir partition.

        Returns:
            bool: True if check passes, False otherwise

        """
        self.logger.info("=== Checking disk space ===")

        # Get table size
        table_size_mb = self.get_table_size_mb()
        if table_size_mb is None:
            return False

        # Get MySQL datadir
        datadir = self.get_mysql_datadir()
        if not datadir:
            return False

        # Get disk space
        disk_info = self.get_disk_space_mb(datadir)
        if not disk_info:
            return False

        free_space_mb, _ = disk_info

        # Check if free space is greater than table size
        if free_space_mb > table_size_mb:
            self.logger.info(
                "[PASS] Free disk space (%.2f MB) > table size (%.2f MB)",
                free_space_mb,
                table_size_mb,
            )
            return True
        self.logger.error(
            "[FAIL] Free disk space (%.2f MB) <= table size (%.2f MB)",
            free_space_mb,
            table_size_mb,
        )
        self.logger.error("Need at least %.2f MB free space for pt-online-schema-change", table_size_mb)
        return False

    def run_all_checks(self) -> bool:
        """Run all pre-checks.

        Returns:
            bool: True if all checks pass, False otherwise

        """
        self.logger.info("Starting pre-checks for %s.%s", self.schema, self.table)
        self.logger.info("=" * 50)

        all_passed = True

        # Check disk space
        if not self.check_disk_space():
            all_passed = False

        self.logger.info("=" * 50)
        if all_passed:
            self.logger.info("[PASS] All pre-checks PASSED - pt-online-schema-change can proceed")
        else:
            self.logger.error("[FAIL] Some pre-checks FAILED - pt-online-schema-change should NOT proceed")

        return all_passed

    def close_connection(self) -> None:
        """Close MySQL connection."""
        if self.connection:
            self.connection.close()
            self.logger.info("MySQL connection closed")

    def read_my_cnf(self, config_file: str = None) -> dict:
        """Read MySQL configuration from .my.cnf file.

        Args:
            config_file: Path to .my.cnf file. Defaults to ~/.my.cnf

        Returns:
            dict: Configuration parameters
        """
        if config_file is None:
            config_file = os.path.expanduser("~/.my.cnf")

        config = {}
        if os.path.exists(config_file):
            parser = ConfigParser()
            parser.read(config_file)

            # Read from [client] section
            if parser.has_section("client"):
                config.update(dict(parser.items("client")))

            # Read from [mysql] section
            if parser.has_section("mysql"):
                config.update(dict(parser.items("mysql")))

        return config


def main() -> None:
    """Run the pre-checks script."""
    parser = argparse.ArgumentParser(
        description="Pre-checks for pt-online-schema-change operations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pre_checks.py --schema mydb --table mytable
  python pre_checks.py --schema mydb --table mytable --host 192.168.1.100 --user myuser
  python pre_checks.py --schema mydb --table mytable --password mypass --port 3307
        """,
    )

    parser.add_argument("--schema", required=True, help="Database name")
    parser.add_argument("--table", required=True, help="Table name")
    parser.add_argument("--host", default="127.0.0.1", help="MySQL host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=3306, help="MySQL port (default: 3306)")
    parser.add_argument("--user", default="", help="MySQL username (default: root)")
    parser.add_argument("--password", default="", help="MySQL password (default: empty)")
    parser.add_argument("--config-file", default="~/.my.cnf", type=str, help="Path to .my.cnf file (default: ~/.my.cnf)")

    args = parser.parse_args()

    # Create pre-checks instance
    pre_checks = MySQLPreChecks(
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        schema=args.schema,
        table=args.table,
        config_file=args.config_file,
    )

    try:
        # Connect to MySQL
        if not pre_checks.connect_to_mysql():
            sys.exit(1)

        # Run all checks
        success = pre_checks.run_all_checks()

        # Exit with appropriate code
        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        logging.exception("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        logging.exception("Unexpected error: %s", e)
        sys.exit(1)
    finally:
        pre_checks.close_connection()


if __name__ == "__main__":
    main()
