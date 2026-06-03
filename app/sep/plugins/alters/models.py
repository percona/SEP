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

"""Define models for the Alters plugin."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, FutureDatetime, model_validator

from app.core.utils.fields import NonEmptyStr
from app.inventory.models import ServiceTypeEnum
from app.sep.plugins.alters.schema import alters_schema
from app.sep.plugins.framework import ConnectivityWarning
from app.sep.plugins.framework.rules import (
    apply_conditional_rules,
    ConditionalRulesModel,
)
from app.tasks.models import TaskBackendEnum, TaskHistoryStatusEnum, TaskOwner

DEFAULT_ALTERS_DSN_TABLE = "D=percona,t=dsns"


def _coerce_optional_int(value: Any) -> int | None:
    """Coerce HTML form / JSON optional int fields to ``int | None``."""
    if value is None or value == "":
        return None
    return int(value)


def normalize_alters_target_fields(data: Any) -> Any:
    """Resolve inventory vs manual schema/table targets before conditional rules.

    Legacy Jinja create/edit forms keep ``schema_name`` / ``table_name`` inputs
    in the DOM (hidden, still submitted) while inventory selectors populate
    ``schema_id`` / ``table_id``. Prefer the ID pair when both are present so
    mutual-exclusion rules do not reject otherwise valid edits.

    :param data: Raw model input (typically a form mapping).
    :type data: Any
    :return: Normalized input with exactly one target mode represented.
    :rtype: Any
    """
    if not isinstance(data, dict):
        return data
    normalized = dict(data)
    schema_id = _coerce_optional_int(normalized.get("schema_id"))
    table_id = _coerce_optional_int(normalized.get("table_id"))
    schema_name = str(normalized.get("schema_name") or "").strip()
    table_name = str(normalized.get("table_name") or "").strip()
    normalized["schema_id"] = schema_id
    normalized["table_id"] = table_id
    if schema_id is not None and table_id is not None:
        normalized["schema_name"] = ""
        normalized["table_name"] = ""
    elif schema_name and table_name:
        normalized["schema_id"] = None
        normalized["table_id"] = None
    return normalized


class _AltersTargetFieldsMixin:
    """Normalize target fields shared across Jinja form and JSON write payloads."""

    @model_validator(mode="before")
    @classmethod
    def _normalize_target_fields(cls, data: Any) -> Any:
        return normalize_alters_target_fields(data)


@apply_conditional_rules(alters_schema)
class AltersCreate(_AltersTargetFieldsMixin, ConditionalRulesModel):
    """Represent an Alters creation form.

    :param task_name: The name of the task to be created.
    :type task_name: NonEmptyStr
    :param hostname: The target hostname for the task execution.
    :type hostname: NonEmptyStr
    :param service_id: The Inventory ID of the database service to connect to.
    :type service_id: int
    :param schema_id: The database schema ID on which the task will operate.
    :type schema_id: int | None
    :param table_id: The table ID within the schema to be altered.
    :type table_id: int | None
    :param schema_name: Manual schema name when ``schema_id`` is not set.
    :type schema_name: str
    :param table_name: Manual table name when ``table_id`` is not set.
    :type table_name: str
    :param recursion_method: The method for handling recursion.
    :type recursion_method: NonEmptyStr
    :param alter: The specific alter command to be executed.
    :type alter: NonEmptyStr
    :param dsn_table: The DSN table for recursion method when using ``dsn``. When empty,
        the command builder uses ``D=percona,t=dsns`` (Percona Toolkit convention).
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
    :param max_flow_ctl: Pause when PXC flow control exceeds this value.
    :type max_flow_ctl: str
    :param extra_args: Additional command-line arguments to append to the pt-online-schema-change command.
    :type extra_args: str
    :param alert_on_fail: If True, send an alert if the task fails. Defaults to False.
    :type alert_on_fail: bool
    :param pre_checks_mysql_config_file: Path to MySQL client defaults file on the executor
        (user/password): pre-checks always use this path; execute/dry-run use pt-osc's
        default ~/.my.cnf unless this is set to another path, then --defaults-file is added.
    :type pre_checks_mysql_config_file: str
    :param continue_on_pre_check_failure: When True, continue to the run task even if
        pre-checks fail (overrides the schema's default ``on_failure="halt"`` policy).
    :type continue_on_pre_check_failure: bool
    """

    task_name: NonEmptyStr
    hostname: NonEmptyStr
    service_id: int
    schema_id: int | None = None
    table_id: int | None = None
    schema_name: str = ""
    table_name: str = ""
    recursion_method: NonEmptyStr
    alter: NonEmptyStr
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
    extra_args: str = ""
    alert_on_fail: bool = False
    pre_checks_mysql_config_file: str = "~/.my.cnf"
    continue_on_pre_check_failure: bool = False


@apply_conditional_rules(alters_schema)
class AltersTaskWrite(_AltersTargetFieldsMixin, ConditionalRulesModel):
    """Represent a JSON request body for creating or updating an alters task group.

    Mirrors :class:`AltersCreate` and is validated against ``alters_schema``
    conditional rules (for example, ``dsn_table`` required when
    ``recursion_method`` is ``"dsn"``).

    :param task_name: The name of the task to be created.
    :type task_name: NonEmptyStr
    :param hostname: The target hostname for the task execution.
    :type hostname: NonEmptyStr
    :param service_id: The Inventory ID of the MySQL service to connect to.
    :type service_id: int
    :param schema_id: The inventory schema ID, when not using manual names.
    :type schema_id: int | None
    :param table_id: The inventory table ID, when not using manual names.
    :type table_id: int | None
    :param schema_name: Manual schema name when ``schema_id`` is not set.
    :type schema_name: str
    :param table_name: Manual table name when ``table_id`` is not set.
    :type table_name: str
    :param recursion_method: The method for handling replica discovery.
    :type recursion_method: NonEmptyStr
    :param alter: The specific alter command to be executed.
    :type alter: NonEmptyStr
    :param dsn_table: The DSN table when ``recursion_method`` is ``"dsn"``. When
        recursion is ``"dsn"`` and this field is omitted or empty, it defaults to
        ``D=percona,t=dsns`` (Percona Toolkit convention), matching ``alters_schema``.
    :type dsn_table: str
    :param pause_file: Execution pauses while this file exists.
    :type pause_file: str
    :param new_table_name: New table name before swap.
    :type new_table_name: str
    :param print_arg: Print SQL statements to STDOUT.
    :type print_arg: bool
    :param progress: Print progress reports to STDERR.
    :type progress: str
    :param no_swap_tables: Simulate without swapping tables.
    :type no_swap_tables: bool
    :param no_drop_old_table: Keep the original table after rename.
    :type no_drop_old_table: bool
    :param no_drop_new_table: Keep the new table if copy fails.
    :type no_drop_new_table: bool
    :param no_drop_triggers: Do not drop triggers on the old table.
    :type no_drop_triggers: bool
    :param tries: Retries and wait times for critical operations.
    :type tries: str
    :param set_vars: MySQL variables to set (comma-separated key=value pairs).
    :type set_vars: str
    :param critical_load: Abort when GLOBAL STATUS exceeds thresholds.
    :type critical_load: str
    :param max_load: Pause when GLOBAL STATUS exceeds thresholds.
    :type max_load: str
    :param chunk_time: Target execution time per chunk.
    :type chunk_time: str
    :param max_lag: Pause until replica lag falls below this value.
    :type max_lag: str
    :param max_flow_ctl: Pause when PXC flow control exceeds this value.
    :type max_flow_ctl: str
    :param extra_args: Additional pt-online-schema-change arguments.
    :type extra_args: str
    :param alert_on_fail: Send an alert if the task fails.
    :type alert_on_fail: bool
    :param pre_checks_mysql_config_file: Path to MySQL client defaults file on the executor
        (user/password): pre-checks always use this path; execute/dry-run use pt-osc's
        default ~/.my.cnf unless this is set to another path, then --defaults-file is added.
    :type pre_checks_mysql_config_file: str
    :param continue_on_pre_check_failure: When True, continue to the run task even if
        pre-checks fail (overrides the schema's default ``on_failure="halt"`` policy).
    :type continue_on_pre_check_failure: bool
    """

    @model_validator(mode="before")
    @classmethod
    def _default_dsn_table_for_dsn_recursion(cls, data: Any) -> Any:
        """Apply the schema DSN table default only when ``recursion_method`` is ``dsn``."""
        if not isinstance(data, dict):
            return data
        if (
            data.get("recursion_method") == "dsn"
            and not str(data.get("dsn_table") or "").strip()
        ):
            return {**data, "dsn_table": DEFAULT_ALTERS_DSN_TABLE}
        return data

    task_name: NonEmptyStr
    hostname: NonEmptyStr
    service_id: int
    schema_id: int | None = None
    table_id: int | None = None
    schema_name: str = ""
    table_name: str = ""
    recursion_method: NonEmptyStr = "processlist"
    alter: NonEmptyStr
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
    extra_args: str = ""
    alert_on_fail: bool = False
    pre_checks_mysql_config_file: str = "~/.my.cnf"
    continue_on_pre_check_failure: bool = False


class AltersTaskBase(BaseModel):
    """Define the common fields shared across alters task API responses.

    :param name: The name of the alters task.
    :type name: str
    :param owner: The entity or user that owns the task.
    :type owner: TaskOwner
    :param service_type: The type of database service (always MySQL for alters).
    :type service_type: ServiceTypeEnum | None
    :param status: The current execution status of the task.
    :type status: TaskHistoryStatusEnum | None
    """

    name: str
    owner: TaskOwner
    service_type: ServiceTypeEnum | None = None
    status: TaskHistoryStatusEnum | None = None


class AltersTaskResponse(AltersTaskBase):
    """Represent an alters task API response.

    :param id: The unique identifier for the alters task.
    :type id: int | None
    :param backend: The backend worker/engine executing the task.
    :type backend: TaskBackendEnum
    :param data: The raw configuration and parameters used for the alter execution.
    :type data: dict[str, Any]
    :param protected: Whether the task is protected from deletion or modification.
    :type protected: bool
    :param alert_on_fail: If True, notifications are sent upon task failure.
    :type alert_on_fail: bool
    :param created_at: The timestamp when the task was first created.
    :type created_at: datetime | None
    :param updated_at: The timestamp of the last modification to the task.
    :type updated_at: datetime | None
    :param created_by: The user who initiated the task.
    :type created_by: str | None
    :param last_updated_by: The user who last modified the task record.
    :type last_updated_by: str | None
    :param connectivity_warning: A warning surfaced when the post-creation
        database connectivity check fails. ``None`` when the check passes,
        is opted out, or the task meta lacks the connectivity keys.
    :type connectivity_warning: ConnectivityWarning | None
    :param pre_checks_auto_fire_warning: A warning when the task group was
        created but the automatic pre-checks execute call failed.
    :type pre_checks_auto_fire_warning: str | None
    """

    id: int | None = None
    backend: TaskBackendEnum
    data: dict[str, Any]
    protected: bool
    alert_on_fail: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: str | None = None
    last_updated_by: str | None = None
    connectivity_warning: ConnectivityWarning | None = None
    pre_checks_auto_fire_warning: str | None = None


class AltersExecuteWrite(BaseModel):
    """Represent a JSON request body for executing an alters task.

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


class AltersExecutionResponse(BaseModel):
    """Represent the response from POST /api/plugins/alters/{task_name}/execute.

    :param task_name: The name of the task that was executed.
    :type task_name: str
    :param task_id: The id of the task-history row created by the tasks API.
    :type task_id: int | None
    """

    task_name: str
    task_id: int | None = None
