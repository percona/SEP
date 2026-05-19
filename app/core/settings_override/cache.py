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
from typing import Annotated, Any

from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic.fields import FieldInfo
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.settings_override.manager import SettingsOverrideManager
from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.registry import is_hot_reloadable
from app.core.utils.pydantic import CustomFieldMetadata

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
    :raises sqlalchemy.exc.SQLAlchemyError: If the database query fails
        (connection lost, schema mismatch, transaction aborted, ...). This
        family is not caught here; the caller is expected to log-and-skip
        or swallow at a higher level (e.g. the background refresher's
        per-cycle ``except``).
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

    Constraint metadata attached to the field's annotation (e.g. ``Gt(0)`` from
    ``PositiveInt``) is preserved by re-assembling an ``Annotated`` type from
    ``field_info.annotation`` plus every non-:class:`CustomFieldMetadata` item
    in ``field_info.metadata``. Without this, ``TypeAdapter(field_info.annotation)``
    would accept values the original settings model rejects -- e.g. a negative
    integer override for a ``PositiveInt`` field would silently load.

    :param field_info: The Pydantic field metadata for the target attribute.
    :type field_info: FieldInfo
    :param raw: The JSON-decoded value as stored on the override row.
    :type raw: Any
    :return: The validated Python value matching ``field_info.annotation``
        plus its preserved constraint metadata.
    :rtype: Any
    :raises ValidationError: If ``raw`` cannot be coerced to the declared
        type or violates a preserved constraint. Callers handle and log.
    """
    constraints = tuple(
        item
        for item in field_info.metadata
        if not isinstance(item, CustomFieldMetadata)
    )
    annotated_type: Any
    if constraints:
        annotated_type = Annotated[(field_info.annotation, *constraints)]
    else:
        annotated_type = field_info.annotation
    return TypeAdapter(annotated_type).validate_python(raw)
