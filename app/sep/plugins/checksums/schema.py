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

"""Define the PluginSchema for the Checksums plugin."""

from app.inventory.models import ServiceTypeEnum
from app.sep.plugins.framework.schema import (
    BoolField,
    Capabilities,
    Choice,
    ChoiceField,
    Column,
    ColumnFormat,
    FormSection,
    HostField,
    ListView,
    PluginSchema,
    ServiceField,
    StringField,
)

checksums_schema = PluginSchema(
    name="checksums",
    display_name="Checksums",
    description="Run pt-table-checksum to verify MySQL replication consistency.",
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
            ],
        ),
        FormSection(
            title="Data",
            fields=[
                StringField(
                    name="databases",
                    label="Databases",
                    description="Comma-separated database names",
                ),
                StringField(
                    name="tables",
                    label="Tables",
                    description="Comma-separated table names (schema.table format)",
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
                        Choice(label="Default", value="default"),
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
                    description="Only used when recursion method is 'dsn'",
                ),
            ],
        ),
        FormSection(
            title="Flags",
            fields=[
                BoolField(
                    name="binary_index",
                    label="Binary Index",
                    description="Use BLOB type for replicate-table boundary columns",
                    default=False,
                ),
                BoolField(
                    name="explain_arg",
                    label="Explain (dry run)",
                    description="Show but do not execute checksum queries",
                    default=False,
                ),
                BoolField(
                    name="fail_on_stopped_replication",
                    label="Fail on Stopped Replication",
                    description="Fail with an error if replication is stopped",
                    default=False,
                ),
                BoolField(
                    name="truncate_replicate_table",
                    label="Truncate Replicate Table",
                    description="Truncate the replicate table before starting",
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
                    name="progress",
                    label="Progress",
                    default="time,10",
                    description="Print progress reports to STDERR (e.g. time,10)",
                ),
                StringField(
                    name="set_vars",
                    label="Set Vars",
                    default="transaction_isolation='READ-COMMITTED',lock_wait_timeout=5",
                    description="MySQL variables to set (comma-separated key=value pairs)",
                ),
                StringField(
                    name="max_load",
                    label="Max Load",
                    default="Threads_running=50",
                    description="Pause when any GLOBAL STATUS variable exceeds this threshold",
                ),
                StringField(
                    name="chunk_time",
                    label="Chunk Time",
                    default="0.5",
                    description="Target execution time per chunk in seconds",
                ),
                StringField(
                    name="max_lag",
                    label="Max Lag",
                    default="150",
                    description="Pause until replica lag falls below this value (seconds)",
                ),
            ],
        ),
    ],
    capabilities=Capabilities(
        chaining=True, alert_on_fail=True, scheduling=True, stats=True
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
)
