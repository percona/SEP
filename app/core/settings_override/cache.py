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

"""Build immutable override snapshots for a settings class."""

__all__ = ["build_snapshot"]

import logging
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic.fields import FieldInfo
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.settings_override.manager import SettingsOverrideManager
from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.registry import is_hot_reloadable

logger = logging.getLogger(__name__)


async def build_snapshot(
    session: AsyncSession,
    settings_cls: type[BaseModel],
    setting_class: SettingClassEnum,
) -> MappingProxyType[str, Any]:
    """Build a frozen snapshot of active HOT overrides for a settings class.

    Only rows whose ``is_active`` flag is ``True`` AND whose ``key`` is
    declared HOT on ``settings_cls`` are considered. Rows with values that
    fail Pydantic type coercion are logged and skipped; the rest of the
    snapshot is unaffected. Rows for unknown or NOT_OVERRIDABLE fields are
    also logged and skipped.

    :param session: The async SQLModel session used to query overrides. Must
        be bound to the engine of the service that owns ``settings_cls``.
    :type session: AsyncSession
    :param settings_cls: The Pydantic settings class being snapshotted.
    :type settings_cls: type[BaseModel]
    :param setting_class: The enum identifier used to filter override rows.
    :type setting_class: SettingClassEnum
    :return: An immutable mapping of field name to coerced typed value.
    :rtype: MappingProxyType[str, Any]
    """
    rows = await SettingsOverrideManager.list(
        session, setting_class=setting_class, is_active=True
    )
    snapshot: dict[str, Any] = {}
    for row in rows:
        field_info = settings_cls.model_fields.get(row.key)
        if field_info is None:
            logger.warning(
                "Override for unknown field ignored: %s.%s",
                setting_class.value,
                row.key,
            )
            continue
        if not is_hot_reloadable(settings_cls, row.key):
            logger.warning(
                "Override for non-HOT field ignored: %s.%s",
                setting_class.value,
                row.key,
            )
            continue
        try:
            snapshot[row.key] = _coerce_value(field_info, row.value)
        except ValidationError as exc:
            logger.warning(
                "Override for %s.%s failed type coercion: %s",
                setting_class.value,
                row.key,
                exc,
            )
    return MappingProxyType(snapshot)


def _coerce_value(field_info: FieldInfo, raw: Any) -> Any:
    """Coerce a raw JSON-decoded value to the field's declared Python type.

    :param field_info: The Pydantic field metadata for the target attribute.
    :type field_info: FieldInfo
    :param raw: The JSON-decoded value as stored on the override row.
    :type raw: Any
    :return: The validated Python value matching ``field_info.annotation``.
    :rtype: Any
    :raises ValidationError: If ``raw`` cannot be coerced to the declared
        type. Callers handle and log.
    """
    return TypeAdapter(field_info.annotation).validate_python(raw)
