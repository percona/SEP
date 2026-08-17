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

"""Pin the ``settingoverride.setting_class`` storage-token derivation."""

from typing import ClassVar

import pytest

from app.core.alerts.config import AlertSettings
from app.core.config import BaseYamlSettings, Settings
from app.core.settings_override.models import setting_class_token
from app.inventory.config import InventorySettings
from app.sep.apps.alerts.config import AlertsSettings
from app.sep.apps.report.config import HealthReportSettings
from app.sep.config import SEPSettings
from app.sep.snippets.config import SnippetsSettings
from app.tasks.anonymizer.config import AnonymizerSettings
from app.tasks.config import TasksSettings

#: Historical ``SettingClassEnum`` member names the database already stores.
#: Includes the two app-owned classes this ticket removes from the enum, so a
#: future class rename cannot silently orphan their override rows.
_HISTORICAL_TOKENS: tuple[tuple[type[BaseYamlSettings], str], ...] = (
    (AlertSettings, "ALERT_SETTINGS"),
    (AlertsSettings, "ALERTS_SETTINGS"),
    (AnonymizerSettings, "ANONYMIZER_SETTINGS"),
    (HealthReportSettings, "HEALTH_REPORT_SETTINGS"),
    (InventorySettings, "INVENTORY_SETTINGS"),
    (SEPSettings, "SEP_SETTINGS"),
    (Settings, "SETTINGS"),
    (SnippetsSettings, "SNIPPETS_SETTINGS"),
    (TasksSettings, "TASKS_SETTINGS"),
)


@pytest.mark.parametrize(
    ("settings_cls", "expected"),
    _HISTORICAL_TOKENS,
    ids=[cls.__name__ for cls, _ in _HISTORICAL_TOKENS],
)
def test_derivation_matches_historical_member_name(
    settings_cls: type[BaseYamlSettings],
    expected: str,
) -> None:
    """Derive the same storage token every existing override row already uses."""
    assert setting_class_token(settings_cls) == expected


def test_classvar_override_pins_the_storage_token() -> None:
    """A class declaring ``__setting_class_token__`` stores that token instead."""

    class CustomTokenSettings(BaseYamlSettings):
        __setting_class_token__: ClassVar[str] = "CUSTOM_TOKEN"

    assert setting_class_token(CustomTokenSettings) == "CUSTOM_TOKEN"
    assert setting_class_token(CustomTokenSettings) != "CUSTOM_TOKEN_SETTINGS"
