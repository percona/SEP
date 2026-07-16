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

"""Define the presentation bundle for the MongoDB Backups app.

Section *membership* and *order* are declared on
:class:`~app.sep.apps.backup_mongo.models.BackupForm` (via ``Ui(section=...)``
and field-declaration order); what lives here is the part the model cannot
express: the section titles, the collapse metadata, the read-only Task-section
note about derived backup types, the list columns, and the UI capability flags.
These feed the derived ``GET /schema``.
"""

from app.sep.apps.framework.apps import Views
from app.sep.apps.framework.form_dsl import (
    FormLayout,
    SectionLayout,
)
from app.sep.apps.framework.schema import (
    Capabilities,
    default_columns,
    EXECUTOR_HOST_COLUMN,
    ListView,
)
from app.sep.apps.shared.backups.columns import BACKUP_TYPE_COLUMN

#: Task section stays expanded; description surfaces the derived sibling types
#: (logical, physical, status) produced by one create — cascade behavior is
#: unchanged.
_TASK_SECTION_LAYOUT = SectionLayout(
    key="Task",
    title="Task",
    description=(
        "Creating this backup produces three sibling tasks: logical, physical, "
        "and status."
    ),
)

backup_mongo_views = Views(
    layout=FormLayout(
        sections=(
            _TASK_SECTION_LAYOUT,
            SectionLayout(
                key="Storage",
                title="Storage",
                collapsible=True,
                collapsed_by_default=True,
            ),
            SectionLayout(
                key="PITR",
                title="Point-in-Time Recovery",
                collapsible=True,
                collapsed_by_default=True,
            ),
            SectionLayout(
                key="BackupOptions",
                title="Backup Options",
                collapsible=True,
                collapsed_by_default=True,
            ),
        )
    ),
    list_view=ListView(
        columns=default_columns(
            EXECUTOR_HOST_COLUMN,
            BACKUP_TYPE_COLUMN,
        ),
        default_sort="name",
    ),
    capabilities=Capabilities(chaining=True, alert_on_fail=True, scheduling=True),
)
