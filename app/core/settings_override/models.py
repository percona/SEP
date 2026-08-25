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

"""Define the persistent ``SettingOverride`` model and class identifier enum."""

__all__ = ["SettingClassEnum", "SettingOverride", "setting_class_token"]

import re
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import field_validator, JsonValue
from sqlalchemy import Column, Index, String
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field as SQLField

from app.core.db.models import BaseSQLModel
from app.core.db.sql_types import AutoJSON

if TYPE_CHECKING:
    from app.core.config import BaseYamlSettings

#: Acronym-aware CamelCase split: ``SEPSettings`` -> ``SEP_Settings``,
#: ``HealthReportSettings`` -> ``Health_Report_Settings``.
_CAMEL_SPLIT = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def setting_class_token(settings_cls: type["BaseYamlSettings"]) -> str:
    """Return the storage token written to ``settingoverride.setting_class``.

    The token is the SCREAMING_SNAKE form of the class ``__name__``, derived by
    an acronym-aware CamelCase split so ``SEPSettings`` stores as
    ``SEP_SETTINGS`` -- the spelling every existing override row already uses.
    A class may pin a different token by declaring ``__setting_class_token__``,
    the same escape hatch shape as SQLAlchemy's ``__tablename__``.

    :param settings_cls: The settings class whose override rows are stored.
    :return: The token written to ``settingoverride.setting_class``.
    """
    override = getattr(settings_cls, "__setting_class_token__", None)
    if isinstance(override, str) and override:
        return override
    return _CAMEL_SPLIT.sub("_", settings_cls.__name__).upper()


class SettingClassEnum(StrEnum):
    """Enumerate settings classes that may have HOT override rows.

    The wired core classes are ``SEPSettings``, ``TasksSettings``,
    ``SnippetsSettings``, the global ``Settings``, ``AlertSettings``,
    ``AnonymizerSettings``, and ``InventorySettings``. App-owned classes
    (``AlertsSettings``, ``HealthReportSettings``) declare themselves under
    ``app/sep/apps/<app>/`` and do not need a member here.

    Members are in-process constants. The ``settingoverride.setting_class``
    column is a plain string whose stored token is derived by
    :func:`setting_class_token`; adding a member no longer requires a
    migration.

    To wire a new core settings class:

    1. Add a member here whose value matches the Pydantic class ``__name__``.
    2. Wire a ``ProxyEntry`` for the new class in the relevant service's
       lifespan (``app/sep/main.py`` or ``app/tasks/main.py``).
    """

    SEP_SETTINGS = "SEPSettings"
    TASKS_SETTINGS = "TasksSettings"
    SNIPPETS_SETTINGS = "SnippetsSettings"
    SETTINGS = "Settings"
    ALERT_SETTINGS = "AlertSettings"
    ANONYMIZER_SETTINGS = "AnonymizerSettings"
    INVENTORY_SETTINGS = "InventorySettings"


class _SettingClassString(TypeDecorator):
    """Store the settings-class token as VARCHAR, binding enum members by name.

    SQLAlchemy's ``Enum`` type persisted members by *name* (``SEP_SETTINGS``).
    A bare ``String`` would bind the *value* (``SEPSettings``) and orphan
    every existing row. This decorator keeps the historical spelling for any
    leftover enum argument while the column itself remains an unconstrained
    string.

    :cvar impl: The underlying SQLAlchemy column type.
    :vartype impl: type[String]
    :cvar cache_ok: Allow SQLAlchemy to cache compiled statements using this type.
    :vartype cache_ok: bool
    """

    impl = String(255)
    cache_ok = True

    def process_bind_param(
        self,
        value: object,
        dialect: Dialect,  # noqa: ARG002
    ) -> str | None:
        """Persist enum members by name and every other value as a string.

        :param value: The Python value being bound.
        :param dialect: The active SQLAlchemy dialect (unused).
        :return: The storage token, or ``None``.
        """
        if value is None:
            return None
        if isinstance(value, SettingClassEnum):
            return value.name
        return str(value)


class SettingOverride(BaseSQLModel, table=True):
    """Represent an admin-managed runtime override of a single settings field.

    The same concrete class is shared across services. Each service's Alembic
    ``migrations/env.py`` imports the model directly (via
    ``from app.core.settings_override.models import *``) so it is registered
    on the shared metadata, and creates the same DDL in its own logical
    database. Rows live in whichever service writes them and are never
    accessed cross-service -- each service queries its own engine for its own
    snapshot.

    :param setting_class: The storage token of the wrapped settings class
        (the SCREAMING_SNAKE form derived by :func:`setting_class_token`).
    :type setting_class: str
    :param key: The field name on the target settings class to override.
    :type key: str
    :param value: The JSON-encoded raw value to apply at runtime.
    :type value: JsonValue
    :param is_active: Whether this override row should be considered by the
        cache loader. Inactive rows are skipped.
    :type is_active: bool
    """

    __table_args__ = (
        Index(
            "ix_settingoverride_setting_class_key",
            "setting_class",
            "key",
            unique=True,
        ),
    )

    setting_class: str = SQLField(
        sa_column=Column(_SettingClassString(), nullable=False),
        max_length=255,
    )
    key: str = SQLField(index=True, nullable=False, max_length=255)
    value: JsonValue = SQLField(
        sa_column=Column(AutoJSON, nullable=False),
    )
    is_active: bool = SQLField(default=True, nullable=False, index=True)

    @field_validator("setting_class", mode="before")
    @classmethod
    def _enum_member_to_token(cls, value: object) -> object:
        """Persist ``SettingClassEnum`` members by name, not value.

        A ``StrEnum`` is a ``str`` whose content is the member *value*
        (``SEPSettings``). Without this coercion, constructing
        ``SettingOverride(setting_class=SettingClassEnum.SEP_SETTINGS)``
        would store that value and orphan every existing row, which stores
        the member *name* (``SEP_SETTINGS``).

        :param value: The raw ``setting_class`` being assigned.
        :return: The storage token when ``value`` is an enum member, otherwise
            ``value`` unchanged.
        """
        if isinstance(value, SettingClassEnum):
            return value.name
        return value
