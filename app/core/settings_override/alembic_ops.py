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

"""Idempotent Alembic helpers shared by the three ``settingoverride`` tracks."""

from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op

from app.core.db.utils import (
    acquire_pg_advisory_xact_lock,
    check_constraint_name,
    table_exists,
)
from app.core.settings_override.constants import (
    SETTING_CLASS_CHECK_MEMBERS_PRE_SEP_1825,
    SETTINGOVERRIDE_MIGRATION_LOCK_KEY,
)

logger = logging.getLogger(__name__)

_TABLE = "settingoverride"
_COLUMN = "setting_class"
_ENUM_NAME = "settingclassenum"
_STRING_LENGTH = 255
_PRE_TICKET_MEMBERS = SETTING_CLASS_CHECK_MEMBERS_PRE_SEP_1825
_PRE_TICKET_VARCHAR_LENGTH = max(len(member) for member in _PRE_TICKET_MEMBERS)


def upgrade_drop_setting_class_check() -> None:
    """Drop the ``setting_class`` CHECK and widen the column to ``VARCHAR(255)``.

    Idempotent on a shared PostgreSQL database: the second track no-ops once
    the first has already dropped the constraint. A missing table is also a
    no-op, matching the other ``settingoverride`` guards.
    """
    bind = op.get_bind()
    acquire_pg_advisory_xact_lock(bind, SETTINGOVERRIDE_MIGRATION_LOCK_KEY)
    if not table_exists(bind, _TABLE):
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
            existing_type=sa.String(length=_PRE_TICKET_VARCHAR_LENGTH),
            type_=sa.String(length=_STRING_LENGTH),
            existing_nullable=False,
        )


def downgrade_restore_setting_class_check() -> None:
    """Re-add the pre-SEP-1825 CHECK, deleting rows that would violate it.

    Deletes every ``settingoverride`` row whose ``setting_class`` is not in
    :data:`SETTING_CLASS_CHECK_MEMBERS_PRE_SEP_1825` and logs how many rows
    it removed. Re-enabling an app after this downgrade will not restore
    those overrides.
    """
    bind = op.get_bind()
    acquire_pg_advisory_xact_lock(bind, SETTINGOVERRIDE_MIGRATION_LOCK_KEY)
    if not table_exists(bind, _TABLE):
        return
    if check_constraint_name(bind, _TABLE, _COLUMN) is not None:
        return
    settingoverride = sa.table(_TABLE, sa.column(_COLUMN))
    result = bind.execute(
        settingoverride.delete().where(
            settingoverride.c[_COLUMN].notin_(_PRE_TICKET_MEMBERS)
        )
    )
    logger.info(
        "Deleted %s settingoverride row(s) whose setting_class is outside "
        "the CHECK member list in force before SEP-1825.",
        result.rowcount,
    )
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.alter_column(
            _COLUMN,
            existing_type=sa.String(length=_STRING_LENGTH),
            type_=sa.Enum(
                *_PRE_TICKET_MEMBERS,
                name=_ENUM_NAME,
                native_enum=False,
                create_constraint=True,
            ),
            existing_nullable=False,
        )
