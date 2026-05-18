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

"""Define the PluginSchema for the Gascan plugin."""

from app.sep.plugins.framework.schema import (
    Capabilities,
    Column,
    ColumnFormat,
    FormSection,
    HostField,
    ListView,
    PluginSchema,
    StringField,
)

gascan_schema = PluginSchema(
    name="gascan",
    display_name="Gascan Management",
    description="Run gascan playbooks on executor hosts.",
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
            ],
        ),
        FormSection(
            title="Gascan",
            fields=[
                StringField(
                    name="playbook",
                    label="Playbook",
                    required=True,
                    description="Playbook to execute",
                ),
                StringField(
                    name="limit",
                    label="Limit",
                    description="Optional limit expression",
                ),
                StringField(
                    name="override",
                    label="Override",
                    description="Optional override values",
                ),
            ],
        ),
    ],
    capabilities=Capabilities(chaining=True, alert_on_fail=True, scheduling=True),
    list_view=ListView(
        columns=[
            Column(key="name", label="Name", sortable=True),
            Column(key="status", label="Status", format=ColumnFormat.STATUS),
            Column(key="created_at", label="Created", format=ColumnFormat.RELATIVE),
            Column(key="created_by", label="Created By"),
        ],
    ),
)
