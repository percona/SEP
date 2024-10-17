"""Define models for the Archives plugin."""

from pydantic import BaseModel

from app.core.fields import RequiredStr


class ArchivesCreate(BaseModel):
    """Represent an Archives creation form.

    :param archive_type: The type of archive operation (currently supports 'where').
    :type archive_type: RequiredStr
    :param task_name: The alias name for the task being created. This name is used for identifying
        the task in the backend.
    :type task_name: RequiredStr
    :param hostname: The source hostname where the task will be executed.
    :type hostname: RequiredStr
    :param connect_to: The connection type, which could be a hostname or `localhost`.
    :type connect_to: RequiredStr
    :param sourcedb: The source database schema from which data will be purged.
    :type sourcedb: RequiredStr
    :param sourcetbl: The source table within the specified schema from which data will be purged.
    :type sourcetbl: RequiredStr    
    :param where: The WHERE condition that defines which data will be purged from the source table.
    :type where: RequiredStr
    :param dest_name: The destination table where purged data can be archived.
    :type dest_name: RequiredStr
    """

    archive_type: RequiredStr
    task_name: RequiredStr
    connect_to: RequiredStr
    hostname: RequiredStr
    sourcedb: RequiredStr
    sourcetbl: RequiredStr
    where: RequiredStr
    dest_name: RequiredStr
