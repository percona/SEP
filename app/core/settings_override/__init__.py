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

"""DB-backed settings override layer (HOT-only)."""

__all__ = [
    "OverridableSettingsProxy",
    "ReloadClassification",
    "SettingClassEnum",
    "SettingOverride",
    "SettingsOverrideManager",
    "build_snapshot",
    "hot_field",
    "hot_field_names",
    "is_hot_reloadable",
    "refresh_all",
    "settings_override_refresher",
    "start_refresh_task",
]

from app.core.settings_override.cache import build_snapshot
from app.core.settings_override.lifecycle import (
    refresh_all,
    settings_override_refresher,
    start_refresh_task,
)
from app.core.settings_override.manager import SettingsOverrideManager
from app.core.settings_override.models import SettingClassEnum, SettingOverride
from app.core.settings_override.proxy import OverridableSettingsProxy
from app.core.settings_override.registry import (
    hot_field,
    hot_field_names,
    is_hot_reloadable,
    ReloadClassification,
)
