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

"""Shared backup response base for the backup task apps.

Lives alongside (not inside) :mod:`app.sep.apps.framework` so the backup apps
(``backup_mongo``, ``backup_pg``, ``mysql_backups``) can share this
backup-family-specific response layer without importing ``framework.__init__``
and unrelated SQLModel tables into scope. The framework package stays
domain-neutral; the executor ``hostname`` surface that this base carries belongs
to the backup family, not the framework.
"""

from app.sep.apps.framework import BaseTaskResponse


class BackupTaskBase(BaseTaskResponse):
    """Carry the backup-family fields shared across its API responses.

    :param hostname: The Nomad executor target the task runs on.
    :type hostname: str | None
    """

    hostname: str | None = None
