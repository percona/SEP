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
:class:`~app.sep.apps.mysql_backups.forms.BackupCreate` (via ``Ui(section=...)``
and field-declaration order); what lives here is the part the model cannot
express: the section titles, the collapse/whole-section-hide metadata, the
``Advanced`` grouping, the list columns, and the UI capability flags. These feed
the derived ``GET /schema``.

Two things here are not carried over from the previous hand-written
``AppSchema``: the Encryption section's group ``description``, which guides
operators from the explicit encryption format to the fields that parameterise
it, and ``group=ADVANCED_GROUP`` on General, Encryption and Upload, which
collapses the three into one row so the required fields fit one screen. The
renderer forms a group from an *adjacent* run of sections, and the derived order
comes from field declaration order on the model — which is why ``General``'s
fields sit below the mode sections in
:mod:`~app.sep.apps.mysql_backups.forms` rather than above them.
"""

from app.sep.apps.framework.apps import Views
from app.sep.apps.framework.form_dsl import (
    ADVANCED_GROUP,
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
from app.sep.apps.mysql_backups.models import BackupType
from app.sep.apps.shared.backups.columns import backup_type_column

mysql_backups_views = Views(
    layout=FormLayout(
        sections=(
            TASK_SECTION_LAYOUT,
            SectionLayout(
                key="General",
                title="General",
                group=ADVANCED_GROUP,
                collapsible=True,
                collapsed_by_default=True,
            ),
            SectionLayout(
                key="Mydumper",
                title="Mydumper",
                collapsible=True,
                collapsed_by_default=True,
                forbidden=(FieldGate(when=F("backup_type") != "M"),),
            ),
            SectionLayout(
                key="XtraBackup",
                title="XtraBackup",
                collapsible=True,
                collapsed_by_default=True,
                forbidden=(FieldGate(when=F("backup_type") != "X"),),
            ),
            SectionLayout(
                key="Binlog",
                title="Binlog",
                collapsible=True,
                collapsed_by_default=True,
                forbidden=(FieldGate(when=F("backup_type") != "B"),),
            ),
            SectionLayout(
                key="Encryption",
                title="Encryption",
                group=ADVANCED_GROUP,
                collapsible=True,
                collapsed_by_default=True,
                description=(
                    "Pick an 'Encryption format' first; the fields below are that "
                    "format's parameters."
                ),
            ),
            SectionLayout(
                key="Upload",
                title="Upload",
                group=ADVANCED_GROUP,
                collapsible=True,
                collapsed_by_default=True,
            ),
        )
    ),
    list_view=ListView(
        columns=default_columns(
            backup_type_column(BackupType.LABELS),
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
