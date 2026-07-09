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

"""Helpers for exporting wired settings classes as flat key/value maps."""

__all__ = ["build_settings_class_values"]

from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import BaseYamlSettings
from app.core.settings_override.api.routes import collect_class_setting_responses
from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.proxy import OverridableSettingsProxy


async def build_settings_class_values(
    *,
    session: AsyncSession,
    setting_class: SettingClassEnum,
    settings_cls: type[BaseYamlSettings],
    proxy: OverridableSettingsProxy,
) -> dict[str, Any]:
    """Build a flat ``{key: value}`` map for one settings class.

    Uses the same field iteration and :func:`dump_field_value` path as the
    LIST endpoint, including nested-leaf expansion, so export keys match what
    admins see in the settings UI.

    :param session: The sub-app's database session.
    :type session: AsyncSession
    :param setting_class: The settings class identifier (enum member).
    :type setting_class: SettingClassEnum
    :param settings_cls: The Pydantic settings class to introspect.
    :type settings_cls: type[BaseYamlSettings]
    :param proxy: The proxy whose attribute access yields current values.
    :type proxy: OverridableSettingsProxy
    :return: Dumped values keyed by the canonical LIST field name.
    :rtype: dict[str, Any]
    """
    responses = await collect_class_setting_responses(
        session=session,
        setting_class=setting_class,
        settings_cls=settings_cls,
        proxy=proxy,
    )
    return {response.key: response.value for response in responses}
