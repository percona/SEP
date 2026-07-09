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

"""Define the presentation bundle for the Checksums app.

Section *membership* and *order* are declared on
:class:`~app.sep.apps.checksums.models.ChecksumsForm` (via ``Ui(section=...)``
and field-declaration order); what lives here is the part the model cannot
express: the section titles and metadata, the list columns, the detail layout,
and the UI capability flags. These feed the derived ``GET /schema`` and are
carried over verbatim from the previous hand-written ``AppSchema`` so the
schema wire format is unchanged.
"""

from app.sep.apps.framework.apps import Views
from app.sep.apps.framework.form_dsl import FormLayout, SectionLayout
from app.sep.apps.framework.schema import (
    Capabilities,
    Column,
    ColumnFormat,
    default_columns,
    DetailField,
    DetailSection,
    DetailView,
    EXECUTION_HOST_LABEL,
    ListView,
)

checksums_views = Views(
    layout=FormLayout(
        sections=(
            SectionLayout(key="Task", title="Task"),
            SectionLayout(key="Data", title="Data"),
            SectionLayout(key="Recursion", title="Recursion"),
            SectionLayout(key="Flags", title="Flags"),
            SectionLayout(key="Advanced", title="Advanced"),
        )
    ),
    list_view=ListView(
        columns=default_columns(
            Column(key="service_type", label="Service Type", format=ColumnFormat.CHIP),
        ),
    ),
    detail_view=DetailView(
        sections=[
            DetailSection(
                title="Execution",
                fields=[
                    DetailField(path="data.meta.command", label="Command"),
                    DetailField(path="data.meta.args", label="Args"),
                    DetailField(path="data.meta.target", label=EXECUTION_HOST_LABEL),
                ],
            ),
        ],
    ),
    capabilities=Capabilities(
        chaining=True,
        alert_on_fail=True,
        scheduling=True,
        stats=True,
        pii_anonymization=True,
    ),
)
