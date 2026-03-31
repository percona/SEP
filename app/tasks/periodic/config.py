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

"""Define settings for periodic tasks in the Tasks app."""

from enum import auto, StrEnum
from typing import ClassVar

from app.core.config import BaseYamlSettings
from app.core.utils.fields import EnumFieldMixin
from app.core.utils.lazy import LazyProxy


class PeriodicTaskAction(EnumFieldMixin, StrEnum):
    """Control the choice of actions to perform to expired and orphaned periodic tasks.

    :cvar NOTHING: Do nothing.
    :vartype NOTHING: str
    :cvar DISABLE: Disable the matching periodic tasks.
    :vartype DISABLE: str
    :cvar DELETE: Delete the matching periodic tasks.
    :vartype DELETE: str
    """

    NOTHING = auto()
    DISABLE = auto()
    DELETE = auto()


class PeriodicTasksSettings(BaseYamlSettings):
    """Define settings for tasks configuration.

    :cvar SETTINGS_PREFIXES: The prefixes for periodic tasks related settings in the
        configuration file. Set to `["TASKS", "PERIODIC"]`.
    :vartype SETTINGS_PREFIXES: ClassVar[list[str]]
    """

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["TASKS", "PERIODIC"]


periodic_tasks_settings: PeriodicTasksSettings = LazyProxy(PeriodicTasksSettings)
