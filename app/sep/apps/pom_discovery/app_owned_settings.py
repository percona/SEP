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

"""Declare the pom_discovery app's own settings class.

Owning the class here rather than mounting it on ``SEPSettings`` is what keeps
``POM_DISCOVERY_SETTINGS`` out of a deployment that never activates the app: the
registry collects only activated apps, so a SEP without POM has no such section
to be confused by.
"""

from app.core.settings_override.api.routes import AppOwnedClassEntry
from app.core.settings_override.models import SettingClassEnum
from app.sep.apps.pom_discovery.config import (
    pom_discovery_settings,
    PomDiscoverySettings,
)

APP_OWNED_SETTINGS_CLASSES: list[AppOwnedClassEntry] = [
    AppOwnedClassEntry(
        setting_class=SettingClassEnum.POM_DISCOVERY_SETTINGS,
        settings_cls=PomDiscoverySettings,
        proxy=pom_discovery_settings,
        app_key="pom_discovery",
    ),
]
