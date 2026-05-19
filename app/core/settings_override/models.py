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

from enum import StrEnum

from pydantic import JsonValue
from sqlalchemy import Column, Index
from sqlalchemy import Enum as EnumField
from sqlmodel import Field as SQLField

from app.core.db.models import BaseSQLModel
from app.core.db.sql_types import AutoJSON


class SettingClassEnum(StrEnum):
    """Enumerate settings classes that may have HOT override rows.

    Only classes whose proxy is actually wired in this ticket are listed:
    ``SEPSettings``, ``TasksSettings``, ``SnippetsSettings`` and
    ``MessagesSettings``. ``Settings``, ``InventorySettings``,
    ``AlertSettings`` and ``AnonymizerSettings`` are intentionally NOT here
    -- wrapping them is deferred to follow-up tickets.

    To wire a new settings class:

    1. Add a member here whose value matches the Pydantic class ``__name__``.
    2. Generate an Alembic migration on every consumer track that extends the
       ``CHECK`` constraint on ``settingoverride.setting_class``. The column
       uses ``native_enum=False`` so the value list lives in a constraint,
       not a PostgreSQL ``TYPE`` -- the migration ``ALTER``s the constraint.
    3. Wire a ``ProxyEntry`` for the new class in the relevant service's
       lifespan (``app/sep/main.py`` or ``app/tasks/main.py``).

    :cvar SEP_SETTINGS: ``SEPSettings`` class identifier.
    :vartype SEP_SETTINGS: str
    :cvar TASKS_SETTINGS: ``TasksSettings`` class identifier.
    :vartype TASKS_SETTINGS: str
    :cvar SNIPPETS_SETTINGS: ``SnippetsSettings`` class identifier.
    :vartype SNIPPETS_SETTINGS: str
    :cvar MESSAGES_SETTINGS: ``MessagesSettings`` class identifier.
    :vartype MESSAGES_SETTINGS: str
    """

    SEP_SETTINGS = "SEPSettings"
    TASKS_SETTINGS = "TasksSettings"
    SNIPPETS_SETTINGS = "SnippetsSettings"
    MESSAGES_SETTINGS = "MessagesSettings"


class SettingOverride(BaseSQLModel, table=True):
    """Represent an admin-managed runtime override of a single settings field.

    The same concrete class is shared across services. Each service's Alembic
    env re-imports the class via ``from app.<svc>.models import *`` (the
    service ``models.py`` re-exports it) and creates the same DDL in its own
    logical database. Rows live in whichever service writes them and are
    never accessed cross-service -- each service queries its own engine for
    its own snapshot.

    :param setting_class: The class identifier of the wrapped settings class
        whose field is being overridden.
    :type setting_class: SettingClassEnum
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

    setting_class: SettingClassEnum = SQLField(
        sa_column=Column(
            EnumField(SettingClassEnum, native_enum=False, create_constraint=True),
            nullable=False,
            index=True,
        ),
    )
    key: str = SQLField(index=True, nullable=False, max_length=255)
    value: JsonValue = SQLField(
        sa_column=Column(AutoJSON, nullable=False),
    )
    is_active: bool = SQLField(default=True, nullable=False, index=True)
