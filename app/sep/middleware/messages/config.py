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

"""Define settings for the messages middleware."""

from typing import ClassVar

from pydantic import NonNegativeInt

from app.core.config import BaseYamlSettings
from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.proxy import OverridableSettingsProxy
from app.core.settings_override.registry import ReloadClassification
from app.core.utils.pydantic import field_with_metadata
from app.sep.middleware.messages.models import MessageLevel

MESSAGE_NOTSET_LEVEL = 0


class MessagesSettings(BaseYamlSettings):
    """Define configuration options for the messages middleware.

    Wrapped in :class:`OverridableSettingsProxy` below, which defers
    validation to first attribute access. ``app.sep.main.sep_lifespan``
    calls ``messages_settings._resolve()`` at startup to restore the
    fail-fast validation the pre-proxy eager ``MessagesSettings()``
    construction provided -- removing or relocating that call regresses to
    lazy validation, surfacing config errors at first request instead of
    startup.

    :cvar SETTINGS_PREFIXES: The prefixes for snippets related settings in the
        configuration file. Set to `["SEP", "MESSAGES"]`.
    :vartype SETTINGS_PREFIXES: ClassVar[list[str]]
    :param LEVEL: The minimum level of messages to be stored and displayed.
        Messages with a level lower than this will be ignored. Set to
        `MESSAGE_NOTSET_LEVEL` (0) by default, which means all messages are stored.
    :type LEVEL: MessageLevel | NonNegativeInt
    """

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["SEP", "MESSAGES"]
    LEVEL: MessageLevel | NonNegativeInt = field_with_metadata(
        MESSAGE_NOTSET_LEVEL, metadata={"reload": ReloadClassification.HOT}
    )


messages_settings: MessagesSettings = OverridableSettingsProxy(
    MessagesSettings, setting_class=SettingClassEnum.MESSAGES_SETTINGS
)
