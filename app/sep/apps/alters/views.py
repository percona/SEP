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

"""Define the presentation bundle for the Alters (Schema Change) app.

Section *membership* and *order* are declared on
:class:`~app.sep.apps.alters.models.AltersCreate` (via ``Ui(section=...)`` and
field-declaration order); what lives here is the part the model cannot express:
the section titles, the list columns, the detail layout, and the UI capability
flags. These feed the derived ``GET /schema`` and are carried over from the
previous hand-written ``AppSchema`` so the schema wire format is preserved.
"""

from app.sep.apps.framework.apps import Views
from app.sep.apps.framework.form_dsl import (
    FormLayout,
    SectionLayout,
    TASK_SECTION_LAYOUT,
)
from app.sep.apps.framework.schema import (
    Capabilities,
    default_columns,
    DetailField,
    DetailHighlightLanguage,
    DetailSection,
    DetailView,
    EXECUTION_HOST_LABEL,
    ListView,
    SERVICE_TYPE_COLUMN,
)

alters_views = Views(
    layout=FormLayout(
        sections=(
            TASK_SECTION_LAYOUT,
            SectionLayout(key="data", title="Data"),
            SectionLayout(key="alter", title="Alter"),
            SectionLayout(key="recursion", title="Recursion"),
            SectionLayout(key="flags", title="Flags"),
            SectionLayout(key="advanced", title="Advanced"),
        )
    ),
    list_view=ListView(
        columns=default_columns(
            SERVICE_TYPE_COLUMN,
        ),
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
                    DetailField(path="data.meta.target", label=EXECUTION_HOST_LABEL),
                    DetailField(path="data.meta._service_host", label="Database Host"),
                    DetailField(path="data.meta._schema_name", label="Schema"),
                    DetailField(path="data.meta._table_name", label="Table"),
                ],
            ),
        ],
    ),
    capabilities=Capabilities(
        chaining=True,
        alert_on_fail=True,
        scheduling=True,
        stats=True,
    ),
)
