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

"""Define the PluginSchema for the backup_pg plugin."""

from app.inventory.models import ServiceTypeEnum
from app.sep.plugins.backup_pg.models import PgBackRestBackupType
from app.sep.plugins.framework.schema import (
    BoolField,
    Capabilities,
    Choice,
    ChoiceField,
    Column,
    ColumnFormat,
    DetailField,
    DetailSection,
    DetailView,
    FormSection,
    HostField,
    IntegerField,
    ListView,
    PluginSchema,
    ServiceField,
    StringField,
)

backup_pg_schema = PluginSchema(
    name="backup_pg",
    display_name="PostgreSQL Backups",
    description=(
        "Configure pgBackRest-based PostgreSQL backups and run incremental "
        "or differential backup tasks against a Percona-managed Postgres host."
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
                    label="Database Service",
                    required=True,
                    service_types=[ServiceTypeEnum.POSTGRESQL],
                ),
                BoolField(
                    name="alert_on_fail",
                    label="Alert on Failure",
                    default=False,
                ),
            ],
        ),
        FormSection(
            title="pgBackRest",
            fields=[
                ChoiceField(
                    name="pgbackrest_backup_type",
                    label="pgBackRest Backup Type",
                    default=PgBackRestBackupType.INCR.value,
                    choices=[
                        Choice(
                            label="Incremental",
                            value=PgBackRestBackupType.INCR.value,
                        ),
                        Choice(
                            label="Differential",
                            value=PgBackRestBackupType.DIFF.value,
                        ),
                    ],
                ),
                StringField(
                    name="pgbackrest_bin",
                    label="pgBackRest Binary",
                    description="Absolute path to the pgbackrest binary on the host.",
                    default="/usr/bin/pgbackrest",
                ),
                StringField(
                    name="pgbackrest_config_file",
                    label="pgBackRest Config File",
                    description="Path to the pgbackrest.conf used by the task.",
                    default="/etc/pgbackrest.conf",
                ),
                StringField(
                    name="pgbackrest_datadir",
                    label="Postgres Data Directory",
                ),
                IntegerField(
                    name="pgbackrest_retention_full",
                    label="Full Backup Retention",
                    ge=0,
                ),
                IntegerField(
                    name="pgbackrest_retention_archive",
                    label="Archive Retention",
                    ge=0,
                ),
                StringField(
                    name="pgbackrest_incremental_cycle",
                    label="Incremental Cycle",
                    description=(
                        "Number of days, ``daily``, or a weekday name controlling "
                        "the FULL/INCR cycle window."
                    ),
                ),
                StringField(
                    name="logging_dir",
                    label="Logging Directory",
                ),
                StringField(
                    name="backup_dir",
                    label="Backup Directory",
                    required=True,
                ),
            ],
        ),
    ],
    capabilities=Capabilities(
        chaining=True,
        alert_on_fail=True,
        scheduling=True,
    ),
    list_view=ListView(
        columns=[
            Column(key="name", label="Name", sortable=True),
            Column(key="status", label="Status", format=ColumnFormat.STATUS),
            Column(key="hostname", label="Executor Host"),
            Column(key="backup_type", label="Type", format=ColumnFormat.CHIP),
            Column(key="created_at", label="Created", format=ColumnFormat.RELATIVE),
            Column(key="created_by", label="Created By"),
        ],
        default_sort="name",
    ),
    detail_view=DetailView(
        sections=[
            DetailSection(
                title="Overview",
                fields=[
                    DetailField(path="hostname", label="Target"),
                    DetailField(path="host", label="Host"),
                    DetailField(path="port", label="Port"),
                    DetailField(path="backup_type", label="Type"),
                    DetailField(path="created_at", label="Created at"),
                    DetailField(path="updated_at", label="Updated at"),
                ],
            ),
        ],
    ),
)
