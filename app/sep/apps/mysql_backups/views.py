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

"""Define the presentation bundle for the MySQL Backups app.

Section *membership* and *order* are declared on
:class:`~app.sep.apps.mysql_backups.models.BackupCreate` (via ``Ui(section=...)``
and field-declaration order); what lives here is the part the model cannot
express: the section titles, the collapse/whole-section-hide metadata, the list
columns, and the UI capability flags. These feed the derived ``GET /schema`` and
are carried over from the previous hand-written ``AppSchema``; the one addition
is the Encryption section's group ``description`` that guides operators through
the master-switch encryption options.
"""

from app.sep.apps.framework.apps import Views
from app.sep.apps.framework.form_dsl import (
    FormLayout,
    SectionLayout,
    TASK_SECTION_LAYOUT,
)
from app.sep.apps.framework.rules import F, FieldGate
from app.sep.apps.framework.schema import (
    Capabilities,
    default_columns,
    DetailField,
    DetailHighlightLanguage,
    DetailSection,
    DetailView,
    EXECUTION_HOST_LABEL,
    EXECUTOR_HOST_COLUMN,
    ListView,
)
from app.sep.apps.shared.backups.columns import BACKUP_TYPE_COLUMN

mysql_backups_views = Views(
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
            SectionLayout(
                key="Encryption",
                title="Encryption",
                collapsible=True,
                description=(
                    "GPG-encrypt the backup. Enable 'Encrypt backup' first, then "
                    "optionally pick 'Encrypt using tmpdir' or 'Encrypt after backup "
                    "completes' (mutually exclusive). A recipient is required when "
                    "encryption is enabled."
                ),
            ),
            SectionLayout(key="Upload", title="Upload", collapsible=True),
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
                title="Backup Configuration",
                fields=[
                    DetailField(path="data.meta.target", label=EXECUTION_HOST_LABEL),
                    DetailField(
                        path="data.meta.config",
                        label="Config (YAML)",
                        highlight=DetailHighlightLanguage.YAML,
                    ),
                ],
            ),
        ],
    ),
    capabilities=Capabilities(chaining=True, alert_on_fail=True, scheduling=True),
)
