"""Define models for the Alters plugin."""

from pydantic import BaseModel

from app.core.fields import RequiredStr


class AltersCreate(BaseModel):
    """Represent an Alters creation form.

    :param task_name: The name of the task to be created.
    :type task_name: RequiredStr
    :param hostname: The target hostname for the task execution.
    :type hostname: RequiredStr
    :param connect_to: The connection type, which could be a hostname or `localhost`.
    :type connect_to: RequiredStr
    :param schema_name: The database schema name on which the task will operate.
    :type schema_name: RequiredStr
    :param table_name: The table name within the schema to be altered.
    :type table_name: RequiredStr
    :param recursion_method: The method for handling recursion.
    :type recursion_method: RequiredStr
    :param alter: The specific alter command to be executed.
    :type alter: RequiredStr
    :param dsn_table: The DSN table for recursion method when using `dsn`. Defaults to
        an empty string.
    :type dsn_table: str
    """

    task_name: RequiredStr
    hostname: RequiredStr
    connect_to: RequiredStr
    schema_name: RequiredStr
    table_name: RequiredStr
    recursion_method: RequiredStr
    alter: RequiredStr
    dsn_table: str = ""
