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

from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    field_validator,
    model_validator,
)

from app.core.utils.fields import NonEmptyStr, StrippedNonEmptyStr
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework import BaseTaskResponse, derive_create_response_model
from app.sep.apps.framework.form_dsl import (
    AppFormModel,
    Choices,
    DSN_TABLE_DEFAULT,
    Forbidden,
    HostRef,
    Requires,
    SchemaRef,
    ServiceRef,
    TableRef,
    Ui,
)
from app.sep.apps.framework.rules import (
    F,
)
from app.sep.apps.framework.schema import EXECUTION_HOST_LABEL


def _dsn_safe(value: str | None) -> str | None:
    """Reject DSN delimiters (``,`` / ``=``) that could split a pt-osc DSN.

    A free-typed schema or table name is interpolated into the
    ``D={schema},t={table}`` DSN the spec builder emits, so a ``,`` or ``=`` in
    the value could inject extra DSN parts.

    :param value: The free-typed schema or table name to validate.
    :return: The value unchanged when it carries no delimiter.
    :raises ValueError: When the value contains a ``,`` or ``=`` character.
    """
    if value and ("," in value or "=" in value):
        raise ValueError(
            "Values cannot contain ',' or '=' characters (DSN delimiters)."
        )
    return value


def reject_multiline_alter(value: str) -> str:
    """Reject newline characters in an alter command.

    The value is interpolated into a single ``--alter=`` command-line flag, so a
    newline would split it across argv entries and corrupt the generated command.

    :param value: The submitted alter command.
    :return: The validated value, unchanged.
    :raises ValueError: When ``value`` contains a line feed or carriage return.
    """
    if "\n" in value or "\r" in value:
        raise ValueError("alter must not contain newline characters")
    return value


class AltersCreate(AppFormModel):
    """Represent the single model-first declaration of the Alters create form.

    This one declaration drives the JSON create/update request body, the Jinja
    ``Form()`` body, and — via
    :func:`~app.sep.apps.framework.form_dsl.derive_app_schema` — the
    ``GET /schema`` source. The mutual-exclusion and ``dsn`` conditional rules are
    enforced by ``AppFormModel`` inheritance (the field-level ``Requires`` /
    ``Forbidden`` gates plus ``__form_rules__``), not by a decorator.

    The schema-display defaults for ``dsn_table`` and ``progress`` diverge from the
    request-body defaults: the body defaults both to the empty string (so the
    ``dsn_table`` forbidden gate passes for non-``dsn`` recursion, and an omitted
    ``progress`` emits no value), while the form renders the Percona-Toolkit DSN
    table and ``time,10`` via ``Ui(default=...)``.

    :param task_name: The name of the task to be created.
    :param hostname: The target hostname for the task execution.
    :param service_id: The Inventory ID of the database service to connect to.
    :param db_schema: The schema to alter — an inventory id or a free-typed name.
    :param db_table: The table to alter — an inventory id or a free-typed name.
    :param recursion_method: The method for handling recursion.
    :param alter: The specific alter command to be executed.
    :param dsn_table: The DSN table for recursion method when using ``dsn``. When
        recursion is ``dsn`` and this field is omitted or empty, it defaults to
        ``D=percona,t=dsns`` (Percona Toolkit convention).
    :param pause_file: Execution will be paused while the file specified by this param exists.
    :param new_table_name: New table name before it is swapped.
    :param print_arg: Print SQL statements to STDOUT.
    :param progress: Print progress reports to STDERR while copying rows.
    :param no_swap_tables: Swap the original table and the new, altered table.
    :param no_drop_old_table: Drop the original table after renaming it.
    :param no_drop_new_table: Drop the new table if copying the original table fails.
    :param no_drop_triggers: Drop triggers on the old table.
    :param tries: How many times to try critical operations.
    :param set_vars: Set the MySQL variables in this comma-separated list of variable=value pairs.
    :param critical_load: Examine SHOW GLOBAL STATUS after every chunk, and abort if the load is too high.
    :param max_load: Examine SHOW GLOBAL STATUS after every chunk, and pause if any status variables are
        higher than their thresholds.
    :param chunk_time: Adjust the chunk size dynamically so each data-copy query takes this long to execute.
    :param max_lag: Pause the data copy until all replicas lag is less than this value.
    :param max_flow_ctl: Pause when PXC flow control exceeds this value.
    :param extra_args: Additional command-line arguments to append to the pt-online-schema-change command.
    :param pre_checks_mysql_config_file: Path to MySQL client defaults file on the executor
        (user/password): pre-checks always use this path; execute/dry-run use pt-osc's
        default ~/.my.cnf unless this is set to another path, then --defaults-file is added.
    :param continue_on_pre_check_failure: When True, continue to the run task even if
        pre-checks fail (overrides the schema's default ``on_failure="halt"`` policy).
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
            return {**data, "dsn_table": DSN_TABLE_DEFAULT}
        return data

    task_name: Annotated[NonEmptyStr, Ui(label="Task Name", section="task")]
    hostname: Annotated[
        NonEmptyStr, HostRef(), Ui(label=EXECUTION_HOST_LABEL, section="task")
    ]
    service_id: Annotated[
        int,
        ServiceRef(service_types=[ServiceTypeEnum.MYSQL]),
        Ui(label="Database Host", section="task"),
    ]
    pre_checks_mysql_config_file: Annotated[
        str,
        Ui(
            label="MySQL Defaults File",
            section="task",
            description=(
                "Path on the executor with [client] user/password. Pre-checks "
                "always use this path. Execute/dry-run use the same path only "
                "when not ~/.my.cnf."
            ),
        ),
    ] = "~/.my.cnf"

    db_schema: Annotated[
        int | StrippedNonEmptyStr,
        SchemaRef(allow_custom=True),
        Ui(
            label="Schema",
            section="data",
            depends_on="service_id",
            description="Schema to alter; pick from inventory or type a name.",
        ),
    ]
    db_table: Annotated[
        int | StrippedNonEmptyStr,
        TableRef(allow_custom=True),
        Ui(
            label="Table",
            section="data",
            depends_on="db_schema",
            description="Table to alter; pick from inventory or type a name.",
        ),
    ]

    @field_validator("db_schema", "db_table")
    @classmethod
    def _target_dsn_safe(cls, value: int | str) -> int | str:
        """Reject DSN delimiters in a free-typed schema or table name.

        :param value: The submitted schema or table value (inventory id or name).
        :return: The value unchanged when it carries no DSN delimiter.
        """
        return _dsn_safe(value) if isinstance(value, str) else value

    alter: Annotated[
        NonEmptyStr,
        AfterValidator(reject_multiline_alter),
        Ui(
            label="Alter",
            section="alter",
            description=(
                "Schema modifications excluding ALTER TABLE keywords "
                "(e.g. ADD COLUMN new_col INT, DROP COLUMN old_col)"
            ),
        ),
    ]

    recursion_method: Annotated[
        NonEmptyStr,
        Choices(
            (
                ("processlist", "Processlist"),
                ("hosts", "Hosts"),
                ("dsn", "DSN"),
                ("none", "None"),
            )
        ),
        Ui(label="Recursion Method", section="recursion", required=True),
    ] = "processlist"
    dsn_table: Annotated[
        str,
        Requires(when=F("recursion_method") == "dsn"),
        Forbidden(when=F("recursion_method") != "dsn"),
        Ui(
            label="DSN Table",
            section="recursion",
            default=DSN_TABLE_DEFAULT,
            description="Required when recursion method is 'dsn'",
        ),
    ] = ""

    print_arg: Annotated[
        bool,
        Ui(
            label="Print", section="flags", description="Print SQL statements to STDOUT"
        ),
    ] = False
    progress: Annotated[
        str,
        Ui(
            label="Progress",
            section="flags",
            default="time,10",
            description="Print progress reports to STDERR (e.g. time,10)",
        ),
    ] = ""
    no_swap_tables: Annotated[
        bool,
        Ui(
            label="No Swap Tables",
            section="flags",
            description="Simulate without swapping the original and new table",
        ),
    ] = False
    no_drop_old_table: Annotated[
        bool,
        Ui(
            label="No Drop Old Table",
            section="flags",
            description="Keep the original table after rename",
        ),
    ] = False
    no_drop_new_table: Annotated[
        bool,
        Ui(
            label="No Drop New Table",
            section="flags",
            description="Keep the new table if copying the original fails",
        ),
    ] = False
    no_drop_triggers: Annotated[
        bool,
        Ui(
            label="No Drop Triggers",
            section="flags",
            description="Do not drop triggers on the old table",
        ),
    ] = False

    pause_file: Annotated[
        str | None,
        Ui(
            label="Pause File",
            section="advanced",
            description="Execution pauses while this file exists",
        ),
    ] = None
    new_table_name: Annotated[
        str | None,
        Ui(
            label="New Table Name",
            section="advanced",
            description="New table name before swap (%T includes original name)",
        ),
    ] = None
    tries: Annotated[
        str | None,
        Ui(
            label="Tries",
            section="advanced",
            description=(
                "Retries and wait times for critical operations "
                "(operation:tries:wait, comma-separated)"
            ),
        ),
    ] = None
    set_vars: Annotated[
        str | None,
        Ui(
            label="Set Vars",
            section="advanced",
            description="MySQL variables to set (comma-separated key=value pairs)",
        ),
    ] = None
    critical_load: Annotated[
        str | None,
        Ui(
            label="Critical Load",
            section="advanced",
            description="Abort when GLOBAL STATUS variables exceed thresholds",
        ),
    ] = None
    max_load: Annotated[
        str | None,
        Ui(
            label="Max Load",
            section="advanced",
            description="Pause when GLOBAL STATUS variables exceed thresholds",
        ),
    ] = None
    chunk_time: Annotated[
        str | None,
        Ui(
            label="Chunk Time",
            section="advanced",
            description="Target execution time per chunk in seconds",
        ),
    ] = None
    max_lag: Annotated[
        str | None,
        Ui(
            label="Max Lag",
            section="advanced",
            description="Pause until replica lag falls below this value (seconds)",
        ),
    ] = None
    max_flow_ctl: Annotated[
        str | None,
        Ui(
            label="Max Flow Control",
            section="advanced",
            description="Pause when PXC flow control exceeds this value",
        ),
    ] = None
    extra_args: Annotated[
        str | None,
        Ui(
            label="Extra Args",
            section="advanced",
            description="Additional pt-online-schema-change arguments",
        ),
    ] = None
    continue_on_pre_check_failure: Annotated[
        bool,
        Ui(
            label="Continue on Pre-Check Failure",
            section="advanced",
            description=(
                "When enabled, continue to the run task even if pre-checks fail "
                "(overrides the default halt policy)"
            ),
        ),
    ] = False


class AltersTaskResponse(BaseTaskResponse):
    """Represent an alters task API response for list and detail surfaces.

    Add no fields of its own — the alters list/detail surface is exactly the
    shared task-response surface. The create/update routes return the
    :data:`AltersTaskResponseCreate` / :data:`AltersTaskResponseUpdate` models
    derived from this base, which add ``connectivity_warning`` per the
    framework's derived create-response standard.
    """


AltersTaskResponseCreate = derive_create_response_model(
    AltersTaskResponse,
    name="AltersTaskResponseCreate",
    doc=(
        "Represent the create response for an alters task group, carrying the "
        "post-creation connectivity warning."
    ),
)

AltersTaskResponseUpdate = derive_create_response_model(
    AltersTaskResponse,
    name="AltersTaskResponseUpdate",
    doc=(
        "Represent the update response for an alters task group, carrying the "
        "post-update connectivity warning."
    ),
)
