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

"""Presentation bundle for the Example plugin (titles, columns, detail, flags)."""

from app.sep.plugins.framework.apps import Views
from app.sep.plugins.framework.form_dsl import FormLayout, SectionLayout
from app.sep.plugins.framework.schema import (
    Capabilities,
    Column,
    ColumnFormat,
    DetailField,
    DetailHighlightLanguage,
    DetailSection,
    DetailView,
    ListView,
)

example_views = Views(
    layout=FormLayout(
        sections=(
            SectionLayout(key="task", title="Task"),
            SectionLayout(key="options", title="Options"),
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
                    DetailField(
                        path="data.meta._command_line",
                        label="Command line",
                        highlight=DetailHighlightLanguage.BASH,
                    ),
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
