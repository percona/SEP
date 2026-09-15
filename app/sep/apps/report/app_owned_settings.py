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

"""Declare the report app's own settings class."""

from app.core.settings_override.api.routes import AppOwnedClassEntry
from app.sep.apps.report.config import health_report_settings, HealthReportSettings

APP_OWNED_SETTINGS_CLASSES: list[AppOwnedClassEntry] = [
    AppOwnedClassEntry(
        setting_class=HealthReportSettings.__name__,
        settings_cls=HealthReportSettings,
        proxy=health_report_settings,
        app_key="report",
    ),
]
