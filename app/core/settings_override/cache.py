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

from __future__ import annotations

__all__ = ["build_snapshot"]

import logging
from types import MappingProxyType
from typing import Any, TYPE_CHECKING

from app.core.settings_override.manager import SettingsOverrideManager
from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.registry import (
    is_hot_reloadable,
    materialize_override_value,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    # Annotations only -- see app/core/settings_override/registry.py for the
    # circular-import rationale.
    from app.core.config import BaseYamlSettings

logger = logging.getLogger(__name__)


async def build_snapshot(
    session: AsyncSession,
    settings_cls: type[BaseYamlSettings],
) -> MappingProxyType[str, Any]:
    """Build a frozen snapshot of active HOT overrides for a settings class.

    Only rows whose ``is_active`` flag is ``True`` AND whose ``key`` is
    declared HOT on ``settings_cls`` are considered. Rows with values that
    fail Pydantic type coercion are logged and skipped; the rest of the
    snapshot is unaffected. Rows for unknown or NOT_OVERRIDABLE fields are
    also logged and skipped.

    The :class:`SettingClassEnum` member used to filter override rows is
    derived from ``settings_cls`` -- each member's value equals the Pydantic
    class ``__name__``, so the pair is recoverable from the class alone.

    :param session: The async SQLModel session used to query overrides. Must
        be bound to the engine of the service that owns ``settings_cls``.
    :type session: AsyncSession
    :param settings_cls: The Pydantic settings class being snapshotted.
    :type settings_cls: type[BaseYamlSettings]
    :return: An immutable mapping of field name to coerced typed value.
    :rtype: MappingProxyType[str, Any]
    :raises sqlalchemy.exc.SQLAlchemyError: If the database query fails
        (connection lost, schema mismatch, transaction aborted, ...). This
        family is not caught here; the caller is expected to log-and-skip
        or swallow at a higher level (e.g. the background refresher's
        per-cycle ``except``).
    """
    setting_class = SettingClassEnum(settings_cls.__name__)
    rows = await SettingsOverrideManager.list(
        session, setting_class=setting_class, is_active=True
    )
    snapshot = {}
    for row in rows:
        field_info = settings_cls.model_fields.get(row.key)
        if field_info is None:
            logger.warning(
                "Override for unknown field ignored: %s.%s",
                setting_class.name,
                row.key,
            )
            continue
        if not is_hot_reloadable(settings_cls, row.key):
            logger.warning(
                "Override for non-HOT field ignored: %s.%s",
                setting_class.name,
                row.key,
            )
            continue
        try:
            snapshot[row.key] = materialize_override_value(
                settings_cls, row.key, field_info, row.value
            )
        except ValueError as exc:
            logger.warning(
                "Override for %s.%s failed type coercion: %s",
                setting_class.name,
                row.key,
                exc,
            )
    return MappingProxyType(snapshot)
