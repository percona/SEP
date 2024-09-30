"""Define models for the Alters plugin."""

from pydantic import BaseModel

from app.core.fields import RequiredStr


class AltersCreate(BaseModel):
    """Represent an Alters creation form.

    Attributes
    ----------
    task_name : str
        The name of the task to be created.
    hostname : str
        The target hostname for the task execution.
    connect_to : str
        The connection type, which could be a hostname or `localhost`.
    schema_name : str
        The database schema name on which the task will operate.
    table_name : str
        The table name within the schema to be altered.
    recursion_method : str
        The method for handling recursion.
    alter : str
        The specific alter command to be executed.
    dsn_table : str, optional
        The DSN table for recursion method when using `dsn`.
        Defaults to an empty string.

    """

    task_name: RequiredStr
    hostname: RequiredStr
    connect_to: RequiredStr
    schema_name: RequiredStr
    table_name: RequiredStr
    recursion_method: RequiredStr
    alter: RequiredStr
    dsn_table: str = ""
