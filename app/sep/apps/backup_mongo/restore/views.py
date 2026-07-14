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

"""Define the presentation bundle for the MongoDB Restores app.

Section *membership* and *order* are declared on
:class:`~app.sep.apps.backup_mongo.restore.models.RestoreForm` (via
``Ui(section=...)`` and field-declaration order); what lives here is the part the
model cannot express: the section titles, the list columns, and the UI capability
flags. These feed the derived ``GET /schema`` and are carried over from the previous
hand-written ``AppSchema`` so the schema wire format is preserved.
"""

from app.sep.apps.framework.apps import Views
from app.sep.apps.framework.form_dsl import (
    FormLayout,
    SectionLayout,
    TASK_SECTION_LAYOUT,
)
from app.sep.apps.framework.schema import (
    Capabilities,
    Column,
    default_columns,
    EXECUTOR_HOST_COLUMN,
    ListView,
)
from app.sep.apps.shared.backups.columns import BACKUP_TYPE_COLUMN

restore_views = Views(
    layout=FormLayout(
        sections=(
            TASK_SECTION_LAYOUT,
            SectionLayout(key="RestoreOptions", title="Restore Options"),
        )
    ),
    list_view=ListView(
        columns=default_columns(
            EXECUTOR_HOST_COLUMN,
            BACKUP_TYPE_COLUMN,
            Column(key="backup_source", label="Backup Source"),
        ),
        default_sort="name",
    ),
    capabilities=Capabilities(chaining=True, scheduling=True),
)
