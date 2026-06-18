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

The form section layout, list columns, detail layout, and UI capability flags
are not derivable from :class:`~app.sep.plugins.checksums.models.ChecksumsForm`,
so they live here and feed the derived ``GET /schema``. Section titles/order,
column set, detail fields, and capabilities are carried over verbatim from the
previous hand-written ``PluginSchema`` so the schema wire format is unchanged.
"""

from app.sep.plugins.framework.apps import Views
from app.sep.plugins.framework.form_dsl import FormLayout, SectionLayout
from app.sep.plugins.framework.schema import (
    Capabilities,
    Column,
    ColumnFormat,
    DetailField,
    DetailSection,
    DetailView,
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
                    DetailField(path="data.meta.command", label="Command"),
                    DetailField(path="data.meta.args", label="Args"),
                    DetailField(path="data.meta.target", label="Target"),
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
