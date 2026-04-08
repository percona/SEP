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

"""Define models for the Checksums plugin."""

from pydantic import BaseModel

from app.core.utils.fields import NonEmptyStr


class ChecksumsCreate(BaseModel):
    """Represent a Checksums creation form.

    :param task_name: The name of the task to be created.
    :type task_name: NonEmptyStr
    :param hostname: The target hostname for the task execution.
    :type hostname: NonEmptyStr
    :param service_id: The Inventory ID of the database service to connect to.
    :type service_id: int
    :param schema_id: The database schema IDs on which the task will operate.
    :type schema_id: set[int]
    :param databases: The database schemas on which the task will operate.
    :type databases: str
    :param table_id: The table IDs within the schema to be checksummed.
    :type table_id: set[int]
    :param tables: The tables within the schema to be checksummed.
    :type tables: str
    :param recursion_method: The method for handling recursion.
    :type recursion_method: NonEmptyStr
    :param dsn_table: The DSN table for recursion method when using ``dsn``. When empty,
        the command builder uses ``D=percona,t=dsns`` (Percona Toolkit convention).
    :type dsn_table: str
    :param pause_file: Execution will be paused while the file specified by this param exists.
    :type pause_file: str
    :param progress: Print progress reports to STDERR while copying rows.
    :type progress: str
    :param binary_index: Modify the behavior of --create-replicate-table such that the replicate
        table's upper and lower boundary columns are created with the BLOB data type.
    :type binary_index: bool
    :param explain_arg: Show, but do not execute, checksum queries.
    :type explain_arg: bool
    :param fail_on_stopped_replication: If replication is stopped, fail with an error.
    :type fail_on_stopped_replication: bool
    :param truncate_replicate_table: Truncate the replicate table before starting the checksum.
    :type truncate_replicate_table: bool
    :param set_vars: Set the MySQL variables in this comma-separated list of variable=value pairs.
    :type set_vars: str
    :param max_load: Examine SHOW GLOBAL STATUS after every chunk, and pause if any status variables are
        higher than their thresholds.
    :type max_load: str
    :param chunk_time: Adjust the chunk size dynamically so each data-copy query takes this long to execute.
    :type chunk_time: str
    :param max_lag: Pause the data copy until all replicas lag is less than this value.
    :type max_lag: str
    :param alert_on_fail: If True, send an alert if the task fails. Defaults to False.
    :type alert_on_fail: bool
    """

    task_name: NonEmptyStr
    hostname: NonEmptyStr
    service_id: int
    schema_id: set[int] = None
    databases: str = ""
    table_id: set[int] = None
    tables: str = ""
    recursion_method: str
    dsn_table: str = ""
    pause_file: str = ""
    binary_index: bool = False
    explain_arg: bool = False
    fail_on_stopped_replication: bool = False
    truncate_replicate_table: bool = False
    progress: str = ""
    set_vars: str = ""
    max_load: str = ""
    chunk_time: str = ""
    max_lag: str = ""
    extra_args: str = ""
    alert_on_fail: bool = False
