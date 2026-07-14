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

"""Define backup-family shared list-view columns."""

from app.sep.apps.framework.schema import Column, ColumnFormat

#: Read-only "Type" chip column shared by the backup-family task apps.
#: Never mutate it; pass through ``default_columns()``, which copies per call.
BACKUP_TYPE_COLUMN = Column(key="backup_type", label="Type", format=ColumnFormat.CHIP)
