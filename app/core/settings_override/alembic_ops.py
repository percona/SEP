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

"""Provide idempotent Alembic helpers for the three ``settingoverride`` tracks."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

from app.core.db.sql_types import AutoJSON
from app.core.db.utils import (
    acquire_pg_advisory_xact_lock,
    check_constraint_name,
    table_exists,
)
from app.core.encryption import DecryptionError
from app.core.settings_override.constants import (
    SETTING_CLASS_CHECK_MEMBERS_LEGACY,
    SETTING_CLASS_MAX_LENGTH,
    SETTINGOVERRIDE_MIGRATION_LOCK_KEY,
)
from app.core.settings_override.models import setting_class_token
from app.core.settings_override.secret_storage import (
    decrypt_secret_leaves,
    reencrypt_secret_leaves,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from sqlalchemy.engine import Connection

    from app.core.config import BaseYamlSettings

logger = logging.getLogger(__name__)

_TABLE = "settingoverride"
_COLUMN = "setting_class"
_ENUM_NAME = "settingclassenum"
_STRING_LENGTH = SETTING_CLASS_MAX_LENGTH
_LEGACY_MEMBERS = SETTING_CLASS_CHECK_MEMBERS_LEGACY
_LEGACY_VARCHAR_LENGTH = max(len(member) for member in _LEGACY_MEMBERS)


def _locked_bind() -> Connection | None:
    """Return the bound connection holding the shared lock, or ``None`` if unusable.

    Every ``settingoverride`` migration opens the same way: take the advisory
    lock so two service tracks running ``upgrade heads`` against one physical
    database cannot execute the same work simultaneously, then no-op when the
    other track has already dropped the table.

    :return: The bound connection, or ``None`` when the table is absent.
    """
    bind = op.get_bind()
    acquire_pg_advisory_xact_lock(bind, SETTINGOVERRIDE_MIGRATION_LOCK_KEY)
    return bind if table_exists(bind, _TABLE) else None


def upgrade_drop_setting_class_check() -> None:
    """Drop the ``setting_class`` CHECK and widen the column to ``VARCHAR(255)``.

    Idempotent on a shared PostgreSQL database: the second track no-ops once
    the first has already dropped the constraint. A missing table is also a
    no-op, matching the other ``settingoverride`` guards.
    """
    bind = _locked_bind()
    if bind is None:
        return
    name = check_constraint_name(bind, _TABLE, _COLUMN)
    if name is None:
        return
    if bind.dialect.name == "postgresql":
        op.execute(sa.text(f'ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS "{name}"'))
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        if bind.dialect.name != "postgresql":
            batch_op.drop_constraint(name, type_="check")
        batch_op.alter_column(
            _COLUMN,
            existing_type=sa.String(length=_LEGACY_VARCHAR_LENGTH),
            type_=sa.String(length=_STRING_LENGTH),
            existing_nullable=False,
        )


def downgrade_restore_setting_class_check() -> None:
    """Restore the legacy CHECK, deleting rows that would violate it.

    Deletes every ``settingoverride`` row whose ``setting_class`` is not in
    :data:`SETTING_CLASS_CHECK_MEMBERS_LEGACY` and logs how many rows
    it removed. Re-enabling an app after this downgrade will not restore
    those overrides.
    """
    bind = _locked_bind()
    if bind is None:
        return
    if check_constraint_name(bind, _TABLE, _COLUMN) is not None:
        return
    settingoverride = sa.table(_TABLE, sa.column(_COLUMN))
    result = bind.execute(
        settingoverride.delete().where(
            settingoverride.c[_COLUMN].notin_(_LEGACY_MEMBERS)
        )
    )
    logger.info(
        "Deleted %s settingoverride row(s) whose setting_class is outside "
        "the CHECK member list the restored constraint enumerates.",
        result.rowcount,
    )
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.alter_column(
            _COLUMN,
            existing_type=sa.String(length=_STRING_LENGTH),
            type_=sa.Enum(
                *_LEGACY_MEMBERS,
                name=_ENUM_NAME,
                native_enum=False,
                create_constraint=True,
            ),
            existing_nullable=False,
        )


def upgrade_encrypt_secret_override_values(
    settings_classes: Iterable[type[BaseYamlSettings]],
) -> None:
    """Encrypt every not-yet-encrypted secret leaf stored in ``settingoverride``.

    Idempotent in two directions: ``is_encrypted`` short-circuits a leaf an
    earlier run already rewrote, and a row whose ``setting_class`` none of
    ``settings_classes`` owns is left untouched, so a track sharing one physical
    database with another never rewrites the other's rows.

    :param settings_classes: The settings classes this track can resolve.
    """
    bind = _locked_bind()
    if bind is None:
        return
    _rewrite_secret_leaves(bind, settings_classes, reencrypt_secret_leaves)


def downgrade_decrypt_secret_override_values(
    settings_classes: Iterable[type[BaseYamlSettings]],
) -> None:
    """Restore every encrypted secret leaf to the plaintext the previous code reads.

    A row the configured ``ENCRYPTION_KEY`` cannot decrypt is logged and left as
    it stands rather than aborting: it was already unreadable before the
    downgrade, and refusing to complete would block the rollback the operator is
    performing.

    :param settings_classes: The settings classes this track can resolve.
    """
    bind = _locked_bind()
    if bind is None:
        return
    _rewrite_secret_leaves(bind, settings_classes, decrypt_secret_leaves)


def _settingoverride_value_table() -> sa.TableClause:
    """Return a lightweight ``settingoverride`` table carrying the JSON value type.

    Declaring ``value`` as :class:`AutoJSON` is what makes the rewrite
    dialect-correct: the column resolves to ``JSONB`` on PostgreSQL and ``JSON``
    elsewhere, so the walker sees decoded JSON rather than a dialect-dependent
    raw string.

    :return: The table clause the rewrite selects from and updates.
    """
    return sa.table(
        _TABLE,
        sa.column("id", sa.Integer),
        sa.column(_COLUMN, sa.String),
        sa.column("key", sa.String),
        sa.column("value", AutoJSON),
    )


def _rewrite_secret_leaves(
    bind: Connection,
    settings_classes: Iterable[type[BaseYamlSettings]],
    rewrite: Callable[[type[BaseYamlSettings], str, Any], Any],
) -> None:
    """Apply ``rewrite`` to every resolvable row's value, updating only what changed.

    :param bind: The migration's bound connection.
    :param settings_classes: The settings classes this track can resolve.
    :param rewrite: The per-row transformation, taking the owning settings class,
        the row key and the stored value.
    """
    classes_by_token = {
        setting_class_token(settings_cls): settings_cls
        for settings_cls in settings_classes
    }
    table = _settingoverride_value_table()
    rows = bind.execute(
        sa.select(table.c.id, table.c[_COLUMN], table.c.key, table.c.value)
    ).all()
    rewritten = 0
    unresolved = 0
    undecryptable = 0
    for row in rows:
        settings_cls = classes_by_token.get(getattr(row, _COLUMN))
        if settings_cls is None:
            unresolved += 1
            continue
        try:
            value = rewrite(settings_cls, row.key, row.value)
        except DecryptionError as exc:
            # Only reachable on the downgrade: the encrypt direction decides
            # with is_encrypted and never attempts a decrypt.
            undecryptable += 1
            logger.warning(
                "Left %s.%s as it stands, it could not be decrypted: %s",
                getattr(row, _COLUMN),
                row.key,
                exc,
            )
            continue
        if value == row.value:
            continue
        bind.execute(table.update().where(table.c.id == row.id).values(value=value))
        rewritten += 1
    logger.info(
        "Rewrote %s settingoverride row(s); left %s untouched for a setting_class "
        "this track cannot resolve and %s that could not be decrypted.",
        rewritten,
        unresolved,
        undecryptable,
    )
