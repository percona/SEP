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

from pathlib import Path
from typing import ClassVar

import pytest
from alembic.migration import MigrationContext
from sqlalchemy import Column, VARCHAR

from app.core.alerts.config import AlertSettings
from app.core.config import BaseYamlSettings, Settings
from app.core.settings_override.constants import SETTING_CLASS_MAX_LENGTH
from app.core.settings_override.models import (
    setting_class_token,
    SettingClassEnum,
    SettingOverride,
)
from app.inventory.config import InventorySettings
from app.sep import apps
from app.sep.apps.alerts.config import AlertsSettings
from app.sep.apps.framework.registry import collect_app_owned_settings_classes
from app.sep.apps.inventory.config import InventoryAppSettings
from app.sep.apps.report.config import HealthReportSettings
from app.sep.config import App, SEPSettings
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
    (InventoryAppSettings, "INVENTORY_APP_SETTINGS"),
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
    """Store the pinned token when a class declares ``__setting_class_token__``."""

    class CustomTokenSettings(BaseYamlSettings):
        __setting_class_token__: ClassVar[str] = "CUSTOM_TOKEN"

    assert setting_class_token(CustomTokenSettings) == "CUSTOM_TOKEN"
    assert setting_class_token(CustomTokenSettings) != "CUSTOM_TOKEN_SETTINGS"


def test_every_reachable_settings_class_pins_its_token() -> None:
    """Fail when a settings class is added without pinning its storage token.

    ``_HISTORICAL_TOKENS`` cannot fail for a class it was never told about, so
    a class added after the pins were written would be free to be renamed,
    orphaning its override rows, which is the failure the pins exist to catch.
    App-owned classes are collected from every app that ships the declaration
    module, not from the activation list, so an inactive app is still covered.
    """
    declaring_apps = [
        App(module_name=path.parent.name)
        for path in Path(apps.__file__).parent.glob("*/app_owned_settings.py")
    ]
    pinned = {cls.__name__ for cls, _ in _HISTORICAL_TOKENS}
    reachable = {member.value for member in SettingClassEnum} | {
        entry.settings_cls.__name__
        for entry in collect_app_owned_settings_classes(declaring_apps)
    }
    assert not reachable - pinned


@pytest.mark.parametrize("dialect_name", ["postgresql", "sqlite"])
def test_column_type_matches_inspected_varchar_by_default(dialect_name: str) -> None:
    """Leave autogenerate no diff between the column's type and the stored VARCHAR.

    ``_SettingClassString`` is a ``TypeDecorator``; Alembic's default type
    comparison unwraps it to its ``impl`` before comparing, so no project-level
    ``compare_type`` branch is needed to keep autogenerate quiet.
    """
    impl = MigrationContext.configure(dialect_name=dialect_name).impl
    verdict = impl.compare_type(
        Column("setting_class", VARCHAR(SETTING_CLASS_MAX_LENGTH)),
        Column("setting_class", SettingOverride.__table__.c.setting_class.type),
    )
    assert verdict is False
