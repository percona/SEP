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

"""Define the presentation bundle for the MySQL Restores app.

Section membership and order are declared on
:class:`~app.sep.apps.mysql_backups.restore.models.RestoreCreate` (via
``Ui(section=...)`` and field-declaration order); what lives here is the part the
model cannot express: the section titles, the per-``backup_type`` visibility
gates, and the list columns. The gates are declared here (not as field-level
``Forbidden`` markers) so the permissive create model keeps accepting the
mode-specific fields' non-``None`` defaults on a cross-mode restore.
"""

from app.sep.apps.framework.apps import Views
from app.sep.apps.framework.form_dsl import (
    FormLayout,
    SectionLayout,
    TASK_SECTION_LAYOUT,
)
from app.sep.apps.framework.rules import F, FieldGate
from app.sep.apps.framework.schema import (
    BACKUP_TYPE_COLUMN,
    Capabilities,
    default_columns,
    DetailField,
    DetailSection,
    DetailView,
    EXECUTION_HOST_LABEL,
    EXECUTOR_HOST_COLUMN,
    ListView,
)

restore_views = Views(
    layout=FormLayout(
        sections=(
            TASK_SECTION_LAYOUT,
            SectionLayout(
                key="General",
                title="General",
                collapsible=True,
                collapsed_by_default=True,
            ),
            SectionLayout(
                key="Mydumper",
                title="Mydumper",
                collapsible=True,
                forbidden=(FieldGate(when=F("backup_type") != "M"),),
            ),
            SectionLayout(
                key="XtraBackup",
                title="XtraBackup",
                collapsible=True,
                forbidden=(FieldGate(when=F("backup_type") != "X"),),
            ),
            SectionLayout(
                key="Binlog",
                title="Binlog",
                collapsible=True,
                forbidden=(FieldGate(when=F("backup_type") != "B"),),
            ),
        )
    ),
    list_view=ListView(
        columns=default_columns(
            BACKUP_TYPE_COLUMN,
            EXECUTOR_HOST_COLUMN,
        ),
    ),
    detail_view=DetailView(
        sections=[
            DetailSection(
                title="Restore Target",
                fields=[
                    DetailField(path="hostname", label=EXECUTION_HOST_LABEL),
                    DetailField(path="host", label="Destination Host"),
                    DetailField(path="port", label="Destination Port"),
                ],
            ),
        ],
    ),
    capabilities=Capabilities(chaining=True, alert_on_fail=True, scheduling=True),
)
