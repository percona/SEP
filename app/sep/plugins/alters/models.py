"""Define models for the Alters plugin."""

from pydantic import BaseModel

from app.core.utils.fields import RequiredStr


class AltersCreate(BaseModel):
    """Represent an Alters creation form.

    :param task_name: The name of the task to be created.
    :type task_name: RequiredStr
    :param hostname: The target hostname for the task execution.
    :type hostname: RequiredStr
    :param service_id: The Inventory ID of the database service to connect to.
    :type service_id: int
    :param schema_id: The database schema ID on which the task will operate.
    :type schema_id: int
    :param table_id: The table ID within the schema to be altered.
    :type table_id: int
    :param recursion_method: The method for handling recursion.
    :type recursion_method: RequiredStr
    :param alter: The specific alter command to be executed.
    :type alter: RequiredStr
    :param dsn_table: The DSN table for recursion method when using `dsn`. Defaults to
        an empty string.
    :type dsn_table: str
    :param pause_file: Execution will be paused while the file specified by this param exists.
    :type pause_file: str
    :param new_table_name: New table name before it is swapped.
    :type new_table_name: str
    :param print_arg: Print SQL statements to STDOUT.
    :type print_arg: bool
    :param progress: Print progress reports to STDERR while copying rows.
    :type progress: str
    :param no_swap_tables: Swap the original table and the new, altered table.
    :type no_swap_tables: bool
    :param no_drop_old_table: Drop the original table after renaming it.
    :type no_drop_old_table: bool
    :param no_drop_new_table: Drop the new table if copying the original table fails.
    :type no_drop_new_table: bool
    :param no_drop_triggers: Drop triggers on the old table.
    :type no_drop_triggers: bool
    :param tries: How many times to try critical operations.
    :type tries: str
    :param set_vars: Set the MySQL variables in this comma-separated list of variable=value pairs.
    :type set_vars: str
    :param critical_load: Examine SHOW GLOBAL STATUS after every chunk, and abort if the load is too high.
    :type critical_load: str
    :param max_load: Examine SHOW GLOBAL STATUS after every chunk, and pause if any status variables are
        higher than their thresholds.
    :type max_load: str
    :param chunk_time: Adjust the chunk size dynamically so each data-copy query takes this long to execute.
    :type chunk_time: str
    :param max_lag: Pause the data copy until all replicas lag is less than this value.
    :type max_lag: str
    """

    task_name: RequiredStr
    hostname: RequiredStr
    service_id: int
    schema_id: int
    table_id: int
    recursion_method: RequiredStr
    alter: RequiredStr
    dsn_table: str = ""
    pause_file: str = ""
    new_table_name: str = ""
    print_arg: bool = False
    progress: str = ""
    no_swap_tables: bool = False
    no_drop_old_table: bool = False
    no_drop_new_table: bool = False
    no_drop_triggers: bool = False
    tries: str = ""
    set_vars: str = ""
    critical_load: str = ""
    max_load: str = ""
    chunk_time: str = ""
    max_lag: str = ""
    max_flow_ctl: str = ""
