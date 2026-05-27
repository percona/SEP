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

"""CRUD manager for :class:`SettingOverride` rows."""

__all__ = ["SettingsOverrideManager"]

from app.core.db.crud import BaseSQLModelManager
from app.core.settings_override.models import SettingOverride


class SettingsOverrideManager(BaseSQLModelManager):
    """Manage CRUD operations on :class:`SettingOverride` rows.

    The same manager class is used in every service. The session passed to
    each method (created by the per-service ``get_async_session_maker()``)
    determines which physical database is queried, so per-service isolation
    is preserved without per-service manager subclasses.

    :cvar Model: The SQLModel class managed by this manager.
    :vartype Model: type[SettingOverride]
    """

    Model = SettingOverride
