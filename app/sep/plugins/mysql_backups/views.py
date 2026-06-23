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
:class:`~app.sep.plugins.mysql_backups.models.BackupCreate` (via ``Ui(section=...)``
and field-declaration order); what lives here is the part the model cannot
express: the section titles, the collapse/whole-section-hide metadata, the list
columns, and the UI capability flags. These feed the derived ``GET /schema`` and
are carried over verbatim from the previous hand-written ``PluginSchema`` so the
schema wire format is unchanged.
"""

from app.sep.plugins.framework.apps import Views
from app.sep.plugins.framework.form_dsl import FormLayout, SectionLayout
from app.sep.plugins.framework.rules import F, FieldGate
from app.sep.plugins.framework.schema import (
    Capabilities,
    Column,
    ColumnFormat,
    ListView,
)

mysql_backups_views = Views(
    layout=FormLayout(
        sections=(
            SectionLayout(key="Task", title="Task"),
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
            SectionLayout(key="Encryption", title="Encryption", collapsible=True),
            SectionLayout(key="Upload", title="Upload", collapsible=True),
        )
    ),
    list_view=ListView(
        columns=[
            Column(key="name", label="Name", sortable=True),
            Column(key="status", label="Status", format=ColumnFormat.STATUS),
            Column(key="backup_type", label="Type", format=ColumnFormat.CHIP),
            Column(key="hostname", label="Host"),
            Column(key="created_at", label="Created", format=ColumnFormat.RELATIVE),
            Column(key="created_by", label="Created By"),
        ],
    ),
    capabilities=Capabilities(chaining=True, alert_on_fail=True, scheduling=True),
)
