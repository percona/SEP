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

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, computed_field, FutureDatetime

from app.core.utils.fields import NonEmptyStr
from app.inventory.models import ServiceTypeEnum
from app.sep.plugins.framework import ConnectivityWarning
from app.sep.plugins.framework.form_dsl import (
    AppFormModel,
    Choices,
    Hidden,
    HostRef,
    ServiceRef,
    Ui,
)
from app.tasks.anonymizer.config import anonymizer_settings
from app.tasks.anonymizer.entities import PIIEntity
from app.tasks.models import TaskBackendEnum, TaskHistoryStatusEnum, TaskOwner


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


class ChecksumsForm(AppFormModel):
    """Define the model-first create/update body and schema source for Checksums.

    The single source of the JSON request body (the field types and defaults the
    server validates) *and* the derived ``GET /schema`` form (driven by the
    :class:`Ui` / reference / :class:`Choices` markers). Field set, types, and
    model defaults match the previous hand-written request body so the OpenAPI
    request body stays a no-op; the form-display defaults that differ from the
    model default are carried on ``Ui(default=...)``.

    Fields are declared in request-body order; the form section order is set by
    the layout in ``views.py`` (Task, Data, Recursion, Flags, Advanced).
    """

    task_name: Annotated[NonEmptyStr, Ui(label="Task Name", section="Task")]
    hostname: Annotated[
        NonEmptyStr, HostRef(), Ui(label="Executor Host", section="Task")
    ]
    service_id: Annotated[
        int,
        ServiceRef(service_types=(ServiceTypeEnum.MYSQL,)),
        Ui(label="Database Host", section="Task"),
    ]
    databases: Annotated[
        str,
        Ui(
            label="Databases",
            section="Data",
            default=None,
            description="Comma-separated database names",
        ),
    ] = ""
    tables: Annotated[
        str,
        Ui(
            label="Tables",
            section="Data",
            default=None,
            description="Comma-separated table names (schema.table format)",
        ),
    ] = ""
    recursion_method: Annotated[
        str,
        Choices(
            (
                ("default", "Default"),
                ("processlist", "Processlist"),
                ("hosts", "Hosts"),
                ("dsn", "DSN"),
                ("none", "None"),
            )
        ),
        Ui(label="Recursion Method", section="Recursion", required=True),
    ] = "processlist"
    dsn_table: Annotated[
        str,
        Ui(
            label="DSN Table",
            section="Recursion",
            default="D=percona,t=dsns",
            description="Only used when recursion method is 'dsn'",
        ),
    ] = ""
    pause_file: Annotated[
        str,
        Ui(
            label="Pause File",
            section="Advanced",
            default=None,
            description="Execution pauses while this file exists",
        ),
    ] = ""
    binary_index: Annotated[
        bool,
        Ui(
            label="Binary Index",
            section="Flags",
            description="Use BLOB type for replicate-table boundary columns",
        ),
    ] = False
    explain_arg: Annotated[
        bool,
        Ui(
            label="Explain (dry run)",
            section="Flags",
            description="Show but do not execute checksum queries",
        ),
    ] = False
    fail_on_stopped_replication: Annotated[
        bool,
        Ui(
            label="Fail on Stopped Replication",
            section="Flags",
            description="Fail with an error if replication is stopped",
        ),
    ] = False
    truncate_replicate_table: Annotated[
        bool,
        Ui(
            label="Truncate Replicate Table",
            section="Flags",
            description="Truncate the replicate table before starting",
        ),
    ] = False
    progress: Annotated[
        str,
        Ui(
            label="Progress",
            section="Advanced",
            default="time,10",
            description="Print progress reports to STDERR (e.g. time,10)",
        ),
    ] = ""
    set_vars: Annotated[
        str,
        Ui(
            label="Set Vars",
            section="Advanced",
            default="transaction_isolation='READ-COMMITTED',lock_wait_timeout=5",
            description="MySQL variables to set (comma-separated key=value pairs)",
        ),
    ] = ""
    max_load: Annotated[
        str,
        Ui(
            label="Max Load",
            section="Advanced",
            default="Threads_running=50",
            description="Pause when any GLOBAL STATUS variable exceeds this threshold",
        ),
    ] = ""
    chunk_time: Annotated[
        str,
        Ui(
            label="Chunk Time",
            section="Advanced",
            default="0.5",
            description="Target execution time per chunk in seconds",
        ),
    ] = ""
    max_lag: Annotated[
        str,
        Ui(
            label="Max Lag",
            section="Advanced",
            default="150",
            description="Pause until replica lag falls below this value (seconds)",
        ),
    ] = ""
    alert_on_fail: Annotated[bool, Hidden()] = False


class ChecksumTaskBase(BaseModel):
    """Define the common fields shared across checksum task API responses.

    :param name: The name of the checksum task.
    :type name: str
    :param owner: The entity or user that owns the task.
    :type owner: TaskOwner
    :param service_type: The type of database service (e.g., MySQL, PostgreSQL).
    :type service_type: ServiceTypeEnum | None
    :param status: The current execution status of the task.
    :type status: TaskHistoryStatusEnum | None
    """

    name: str
    owner: TaskOwner
    service_type: ServiceTypeEnum | None = None
    status: TaskHistoryStatusEnum | None = None


class ChecksumTaskResponse(ChecksumTaskBase):
    """Represent a checksum task API response.

    :param id: The unique identifier for the checksum task.
    :type id: int | None
    :param backend: The backend worker/engine executing the task.
    :type backend: TaskBackendEnum
    :param data: The raw configuration and parameters used for the checksum execution.
    :type data: dict[str, Any]
    :param protected: Whether the task is protected from deletion or modification.
    :type protected: bool
    :param alert_on_fail: If True, notifications are sent upon task failure.
    :type alert_on_fail: bool
    :param anonymize_mask: Bitmask of PII entities to anonymize. Defaults to None.
    :type anonymize_mask: int | None
    :param created_at: The timestamp when the task was first created.
    :type created_at: datetime | None
    :param updated_at: The timestamp of the last modification to the task.
    :type updated_at: datetime | None
    :param created_by: Display name for the user who initiated the task
        (Casdoor username when resolvable, otherwise the stored user id).
    :type created_by: str | None
    :param last_updated_by: Display name for the user who last modified the task record
        (Casdoor username when resolvable, otherwise the stored user id).
    :type last_updated_by: str | None
    :param connectivity_warning: A warning surfaced when the post-creation
        database connectivity check fails. ``None`` when the check passes,
        is opted out, or the task meta lacks the connectivity keys.
    :type connectivity_warning: ConnectivityWarning | None
    :param anonymized_entities: Sorted list of PII entity names derived from
        ``anonymize_mask`` (or from the owner's configured defaults when the
        mask is ``None``). Read-only; computed on serialisation.
    :type anonymized_entities: list[str]
    """

    id: int | None = None
    backend: TaskBackendEnum
    data: dict[str, Any]
    protected: bool
    alert_on_fail: bool
    anonymize_mask: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: str | None = None
    last_updated_by: str | None = None
    connectivity_warning: ConnectivityWarning | None = None

    @computed_field
    @property
    def anonymized_entities(self) -> list[str]:
        """Return sorted PII entity names decoded from ``anonymize_mask``."""
        entities = (
            PIIEntity.decode_selection(self.anonymize_mask)
            if self.anonymize_mask is not None
            else anonymizer_settings.DEFAULT_ENTITIES[self.owner]
        )
        return sorted(entity.name for entity in entities)


class ChecksumExecuteWrite(BaseModel):
    """Represent a JSON request body for executing a checksum task.

    :param eta: Optional future datetime to schedule execution.
    :type eta: FutureDatetime | None
    :param chain_task_names: Optional list of task names to chain after this one.
    :type chain_task_names: list[str] | None
    :param chain_on_failure: Whether to run chained tasks even on failure.
    :type chain_on_failure: bool | None
    """

    eta: FutureDatetime | None = None
    chain_task_names: list[str] | None = None
    chain_on_failure: bool | None = None


class ChecksumExecutionResponse(BaseModel):
    """Represent the response from POST /api/plugins/checksums/{task_name}/execute.

    :param task_name: The name of the task that was executed.
    :type task_name: str
    :param task_id: The id of the task-history row created by the tasks API.
    :type task_id: int | None
    """

    task_name: str
    task_id: int | None = None
