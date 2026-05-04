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

"""Define the PluginSchema for the Dipper plugin."""

from app.inventory.models import ServiceTypeEnum
from app.sep.plugins.framework.schema import (
    Capabilities,
    Choice,
    ChoiceField,
    Column,
    FormSection,
    HostField,
    ListView,
    PluginSchema,
    ScriptPreviewField,
    ServiceField,
)

dipper_schema = PluginSchema(
    name="dipper",
    display_name="Collect Diagnostic Data",
    description="Run diagnostic data collection scripts on managed database hosts.",
    forms=[
        FormSection(
            title="Execution",
            fields=[
                ServiceField(
                    name="service_id",
                    label="Database Service",
                    required=True,
                    service_types=[
                        ServiceTypeEnum.MYSQL,
                        ServiceTypeEnum.MONGODB,
                        ServiceTypeEnum.POSTGRESQL,
                    ],
                ),
                ChoiceField(
                    name="collector_type",
                    label="Collector Type",
                    required=True,
                    default="environment",
                    choices=[
                        Choice(value="environment", label="Environment"),
                        Choice(value="pmm", label="PMM"),
                    ],
                ),
                HostField(
                    name="executor_host",
                    label="Executor Host",
                    required=True,
                ),
                ScriptPreviewField(
                    name="script_preview",
                    label="Script Preview",
                    endpoint_url="/plugins/dipper/script-preview",
                    depends_on=["service_id", "collector_type"],
                ),
            ],
        ),
    ],
    capabilities=Capabilities(scheduling=False, alert_on_fail=False, chaining=False),
    list_view=ListView(
        columns=[
            Column(key="snippet_filename", label="Script", sortable=True),
            Column(key="collector_type", label="Collector", sortable=True),
            Column(key="task_name", label="Task"),
            Column(key="task_id", label="Task ID"),
        ],
    ),
)
