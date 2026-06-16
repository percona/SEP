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

"""Define the PluginSchema for the Alters plugin."""

from app.inventory.models import ServiceTypeEnum
from app.sep.plugins.framework.rules import (
    all_,
    all_present,
    F,
    FailRule,
    FieldGate,
    not_,
    truthy,
)
from app.sep.plugins.framework.schema import (
    BoolField,
    Capabilities,
    ChainedPredecessor,
    Choice,
    ChoiceField,
    Column,
    ColumnFormat,
    DerivedTask,
    DetailField,
    DetailHighlightLanguage,
    DetailSection,
    DetailView,
    FormSection,
    HostField,
    ListView,
    PluginSchema,
    SchemaField,
    ServiceField,
    StringField,
    TableField,
    TextAreaField,
)

_INVENTORY_TARGET_SET = FieldGate(when=all_present("schema_id", "table_id"))
_MANUAL_TARGET_SET = FieldGate(
    when=all_(truthy("schema_name"), truthy("table_name")),
)

alters_schema = PluginSchema(
    name="alters",
    display_name="Alters",
    description=(
        "Run pt-online-schema-change to perform online MySQL schema modifications."
    ),
    forms=[
        FormSection(
            title="Task",
            fields=[
                StringField(
                    name="task_name",
                    label="Task Name",
                    required=True,
                ),
                HostField(
                    name="hostname",
                    label="Executor Host",
                    required=True,
                ),
                ServiceField(
                    name="service_id",
                    label="Database Host",
                    required=True,
                    service_types=[ServiceTypeEnum.MYSQL],
                ),
                StringField(
                    name="pre_checks_mysql_config_file",
                    label="MySQL Defaults File",
                    default="~/.my.cnf",
                    description=(
                        "Path on the executor with [client] user/password. "
                        "Pre-checks always use this path. Execute/dry-run use "
                        "the same path only when not ~/.my.cnf."
                    ),
                ),
            ],
        ),
        FormSection(
            title="Data",
            fields=[
                SchemaField(
                    name="schema_id",
                    label="Schema",
                    depends_on="service_id",
                    forbidden=[_MANUAL_TARGET_SET],
                ),
                TableField(
                    name="table_id",
                    label="Table",
                    depends_on="schema_id",
                    forbidden=[_MANUAL_TARGET_SET],
                ),
                StringField(
                    name="schema_name",
                    label="Schema Name",
                    description="Manual schema name when not selecting from inventory",
                    forbidden=[_INVENTORY_TARGET_SET],
                ),
                StringField(
                    name="table_name",
                    label="Table Name",
                    description="Manual table name when not selecting from inventory",
                    forbidden=[_INVENTORY_TARGET_SET],
                ),
            ],
            fail_when=[
                FailRule(
                    fail_when=all_(
                        not_(all_present("schema_id", "table_id")),
                        not_(all_(truthy("schema_name"), truthy("table_name"))),
                    ),
                    error_fields=[
                        "schema_id",
                        "table_id",
                        "schema_name",
                        "table_name",
                    ],
                    message=(
                        "Either both schema_id and table_id or both "
                        "schema_name and table_name must be provided."
                    ),
                ),
                FailRule(
                    fail_when=all_(
                        all_present("schema_id", "table_id"),
                        all_(truthy("schema_name"), truthy("table_name")),
                    ),
                    error_fields=[
                        "schema_id",
                        "table_id",
                        "schema_name",
                        "table_name",
                    ],
                    message=(
                        "Cannot use both schema_id/table_id and "
                        "schema_name/table_name at the same time."
                    ),
                ),
            ],
        ),
        FormSection(
            title="Alter",
            fields=[
                TextAreaField(
                    name="alter",
                    label="Alter",
                    required=True,
                    description=(
                        "Schema modifications excluding ALTER TABLE keywords "
                        "(e.g. ADD COLUMN new_col INT, DROP COLUMN old_col)"
                    ),
                ),
            ],
        ),
        FormSection(
            title="Recursion",
            fields=[
                ChoiceField(
                    name="recursion_method",
                    label="Recursion Method",
                    required=True,
                    default="processlist",
                    choices=[
                        Choice(label="Processlist", value="processlist"),
                        Choice(label="Hosts", value="hosts"),
                        Choice(label="DSN", value="dsn"),
                        Choice(label="None", value="none"),
                    ],
                ),
                StringField(
                    name="dsn_table",
                    label="DSN Table",
                    default="D=percona,t=dsns",
                    description="Required when recursion method is 'dsn'",
                    requires=[FieldGate(when=F("recursion_method") == "dsn")],
                    forbidden=[FieldGate(when=F("recursion_method") != "dsn")],
                ),
            ],
        ),
        FormSection(
            title="Flags",
            fields=[
                BoolField(
                    name="print_arg",
                    label="Print",
                    description="Print SQL statements to STDOUT",
                    default=False,
                ),
                StringField(
                    name="progress",
                    label="Progress",
                    default="time,10",
                    description="Print progress reports to STDERR (e.g. time,10)",
                ),
                BoolField(
                    name="no_swap_tables",
                    label="No Swap Tables",
                    description="Simulate without swapping the original and new table",
                    default=False,
                ),
                BoolField(
                    name="no_drop_old_table",
                    label="No Drop Old Table",
                    description="Keep the original table after rename",
                    default=False,
                ),
                BoolField(
                    name="no_drop_new_table",
                    label="No Drop New Table",
                    description="Keep the new table if copying the original fails",
                    default=False,
                ),
                BoolField(
                    name="no_drop_triggers",
                    label="No Drop Triggers",
                    description="Do not drop triggers on the old table",
                    default=False,
                ),
            ],
        ),
        FormSection(
            title="Advanced",
            fields=[
                StringField(
                    name="pause_file",
                    label="Pause File",
                    description="Execution pauses while this file exists",
                ),
                StringField(
                    name="new_table_name",
                    label="New Table Name",
                    description="New table name before swap (%T includes original name)",
                ),
                StringField(
                    name="tries",
                    label="Tries",
                    description=(
                        "Retries and wait times for critical operations "
                        "(operation:tries:wait, comma-separated)"
                    ),
                ),
                StringField(
                    name="set_vars",
                    label="Set Vars",
                    description="MySQL variables to set (comma-separated key=value pairs)",
                ),
                StringField(
                    name="critical_load",
                    label="Critical Load",
                    description="Abort when GLOBAL STATUS variables exceed thresholds",
                ),
                StringField(
                    name="max_load",
                    label="Max Load",
                    description="Pause when GLOBAL STATUS variables exceed thresholds",
                ),
                StringField(
                    name="chunk_time",
                    label="Chunk Time",
                    description="Target execution time per chunk in seconds",
                ),
                StringField(
                    name="max_lag",
                    label="Max Lag",
                    description="Pause until replica lag falls below this value (seconds)",
                ),
                StringField(
                    name="max_flow_ctl",
                    label="Max Flow Control",
                    description="Pause when PXC flow control exceeds this value",
                ),
                StringField(
                    name="extra_args",
                    label="Extra Args",
                    description="Additional pt-online-schema-change arguments",
                ),
                BoolField(
                    name="continue_on_pre_check_failure",
                    label="Continue on Pre-Check Failure",
                    description=(
                        "When enabled, continue to the run task even if "
                        "pre-checks fail (overrides the default halt policy)"
                    ),
                    default=False,
                ),
            ],
        ),
    ],
    capabilities=Capabilities(
        chaining=True,
        alert_on_fail=True,
        scheduling=True,
        stats=True,
    ),
    list_view=ListView(
        columns=[
            Column(key="name", label="Name", sortable=True),
            Column(key="status", label="Status", format=ColumnFormat.STATUS),
            Column(key="service_type", label="Service Type", format=ColumnFormat.CHIP),
            Column(key="created_at", label="Created", format=ColumnFormat.RELATIVE),
            Column(key="created_by", label="Created By"),
        ],
    ),
    detail_view=DetailView(
        sections=[
            DetailSection(
                title="Execution",
                fields=[
                    DetailField(
                        path="data.meta._command_line",
                        label="Command line",
                        highlight=DetailHighlightLanguage.BASH,
                    ),
                    DetailField(path="data.meta.target", label="Target"),
                    DetailField(path="data.meta._schema_name", label="Schema"),
                    DetailField(path="data.meta._table_name", label="Table"),
                ],
            ),
        ],
    ),
    derived=[
        DerivedTask(
            name_suffix="-dry-run",
            arg_substitutions={"--execute": "--dry-run"},
        ),
    ],
    predecessors=[
        ChainedPredecessor(
            name_suffix="-pre-checks",
            on_failure="halt",
        ),
    ],
)
