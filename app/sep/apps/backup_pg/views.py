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

"""Define the presentation bundle for the PostgreSQL Backups app.

Section *membership* and *order* are declared on
:class:`~app.sep.apps.backup_pg.models.BackupPgForm` (via ``Ui(section=...)``
and field-declaration order); what lives here is the part the model cannot
express: the section titles, the list columns, the detail layout, and the UI
capability flags. These feed the derived ``GET /schema`` and are carried over
verbatim from the previous hand-written ``AppSchema`` so the schema wire
format is unchanged.
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
    DetailSection,
    DetailView,
    EXECUTION_HOST_LABEL,
    EXECUTOR_HOST_COLUMN,
    ListView,
)
from app.sep.apps.shared.backups.columns import BACKUP_TYPE_COLUMN

backup_pg_views = Views(
    layout=FormLayout(
        sections=(
            TASK_SECTION_LAYOUT,
            SectionLayout(key="pgBackRest", title="pgBackRest"),
        )
    ),
    list_view=ListView(
        columns=default_columns(
            EXECUTOR_HOST_COLUMN,
            BACKUP_TYPE_COLUMN,
        ),
        default_sort="name",
    ),
    detail_view=DetailView(
        sections=[
            DetailSection(
                title="Overview",
                fields=[
                    DetailField(path="hostname", label=EXECUTION_HOST_LABEL),
                    DetailField(path="host", label="Host"),
                    DetailField(path="port", label="Port"),
                    DetailField(path="backup_type", label="Type"),
                    DetailField(path="created_at", label="Created at"),
                    DetailField(path="updated_at", label="Updated at"),
                ],
            ),
        ],
    ),
    capabilities=Capabilities(
        chaining=True,
        alert_on_fail=True,
        scheduling=True,
    ),
)
