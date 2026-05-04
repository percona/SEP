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

"""Define PluginSchema objects for the Dipper plugin."""

from typing import cast
from urllib.parse import urlencode

from app.inventory.models import ServiceTypeEnum
from app.sep.plugins.framework.schema import (
    AnyField,
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
    ScriptPreviewField,
    ServiceField,
)
from app.sep.plugins.snippets.schema import _field_for
from app.sep.snippets.config import SnippetSudoOption
from app.sep.snippets.models.snippet import BaseSnippet

_SERVICE_FIELD_NAME = "service_id"
_COLLECTOR_FIELD_NAME = "collector_type"
_EXECUTOR_HOST_FIELD_NAME = "executor_host"
_SUDO_FIELD_NAME = "sudo"
_SCRIPT_PREVIEW_FIELD_NAME = "script_preview"

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
                    name=_EXECUTOR_HOST_FIELD_NAME,
                    label="Executor Host",
                    required=True,
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
            Column(key="status", label="Status", format=ColumnFormat.STATUS),
        ],
    ),
)


def build_dipper_form_schema(
    script: BaseSnippet,
    service_id: int,
    collector_type: str,
    defaults: dict[str, str] | None = None,
) -> PluginSchema:
    """Build the Dipper execution form schema for a selected service/script."""
    parameter_sections: dict[str, list[AnyField]] = {}
    for parameter in script.validated_parameters.parameters:
        section_title = parameter.group or "Parameters"
        field = _field_for(parameter)
        if defaults and field.name in defaults and field.default in (None, ""):
            field.default = defaults[field.name]
        parameter_sections.setdefault(section_title, []).append(field)

    forms = [
        FormSection(title=title, fields=fields)
        for title, fields in parameter_sections.items()
    ]

    execution_fields: list[AnyField] = [
        cast(
            AnyField,
            HostField(
                name=_EXECUTOR_HOST_FIELD_NAME,
                label="Executor Host",
                required=True,
            ),
        ),
    ]
    if script.sudo.is_optional:
        execution_fields.append(
            cast(
                AnyField,
                BoolField(
                    name=_SUDO_FIELD_NAME,
                    label="Run with sudo",
                    default=script.sudo.sudo_default,
                    description="Prepend sudo to the interpreter when the script is executed.",
                ),
            )
        )
    elif script.sudo == SnippetSudoOption.ALWAYS:
        execution_fields.append(
            cast(
                AnyField,
                BoolField(
                    name=_SUDO_FIELD_NAME,
                    label="Run with sudo",
                    default=True,
                    description="This script is configured to always run with sudo.",
                ),
            )
        )
    preview_query = urlencode(
        {"service_id": service_id, "collector_type": collector_type}
    )
    execution_fields.append(
        cast(
            AnyField,
            ScriptPreviewField(
                name=_SCRIPT_PREVIEW_FIELD_NAME,
                label="Script preview",
                endpoint_url=f"/plugins/dipper/script-preview?{preview_query}",
            ),
        )
    )
    forms.append(FormSection(title="Execution", fields=execution_fields))

    return PluginSchema(
        name="dipper",
        display_name=script.title,
        description=script.description or dipper_schema.description,
        forms=forms,
        capabilities=dipper_schema.capabilities,
        list_view=dipper_schema.list_view,
    )
