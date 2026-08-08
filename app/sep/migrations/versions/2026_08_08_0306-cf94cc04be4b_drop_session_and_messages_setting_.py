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

"""drop session and messages setting overrides

Revision ID: cf94cc04be4b
Revises: a2b3c4d5e6f7
Create Date: 2026-08-08 03:06:15.040695

"""

import sqlalchemy as sa
from alembic import op

from app.core.db.utils import (
    acquire_pg_advisory_xact_lock,
    check_constraint_lists_members,
)
from app.core.settings_override.constants import SETTINGOVERRIDE_MIGRATION_LOCK_KEY

# revision identifiers, used by Alembic.
revision = "cf94cc04be4b"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None

_OLD_MEMBERS = (
    "SEP_SETTINGS",
    "TASKS_SETTINGS",
    "SNIPPETS_SETTINGS",
    "MESSAGES_SETTINGS",
    "SETTINGS",
    "ALERT_SETTINGS",
    "ANONYMIZER_SETTINGS",
    "ALERTS_SETTINGS",
    "INVENTORY_SETTINGS",
)
_NEW_MEMBERS = tuple(m for m in _OLD_MEMBERS if m != "MESSAGES_SETTINGS")

# ``_`` is a LIKE wildcard, so the doubled underscore of the nested-leaf prefix
# must be escaped -- an unescaped ``SESSION__%`` also matches ``SESSION_REFRESH``
# leaves, which this ticket keeps.
_DELETE_SESSION_ROWS = (
    "DELETE FROM settingoverride WHERE setting_class = 'SEP_SETTINGS'"
    r" AND (key = 'SESSION' OR key LIKE 'SESSION\_\_%' ESCAPE '\')"
)
_DELETE_MESSAGES_ROWS = (
    "DELETE FROM settingoverride WHERE setting_class = 'MESSAGES_SETTINGS'"
)


def upgrade() -> None:
    """Drop the retired ``SESSION`` / ``MessagesSettings`` override rows."""
    bind = op.get_bind()
    acquire_pg_advisory_xact_lock(bind, SETTINGOVERRIDE_MIGRATION_LOCK_KEY)
    op.execute(_DELETE_SESSION_ROWS)
    if not check_constraint_lists_members(
        bind, "settingoverride", "setting_class", ("MESSAGES_SETTINGS",)
    ):
        return
    # The narrowed CHECK re-validates existing data, so the rows carrying the
    # removed member have to go first or the ALTER aborts.
    op.execute(_DELETE_MESSAGES_ROWS)
    with op.batch_alter_table("settingoverride", schema=None) as batch_op:
        batch_op.alter_column(
            "setting_class",
            existing_type=sa.Enum(
                *_OLD_MEMBERS,
                name="settingclassenum",
                native_enum=False,
                create_constraint=True,
            ),
            type_=sa.Enum(
                *_NEW_MEMBERS,
                name="settingclassenum",
                native_enum=False,
                create_constraint=True,
            ),
            existing_nullable=False,
        )


def downgrade() -> None:
    """Restore ``MESSAGES_SETTINGS`` in the setting_class constraint.

    The deleted rows are not recreated: they configured a session cookie and a
    flash-message level that no longer exist, so restoring them would carry no
    meaning.
    """
    bind = op.get_bind()
    acquire_pg_advisory_xact_lock(bind, SETTINGOVERRIDE_MIGRATION_LOCK_KEY)
    if check_constraint_lists_members(
        bind, "settingoverride", "setting_class", ("MESSAGES_SETTINGS",)
    ):
        return
    with op.batch_alter_table("settingoverride", schema=None) as batch_op:
        batch_op.alter_column(
            "setting_class",
            existing_type=sa.Enum(
                *_NEW_MEMBERS,
                name="settingclassenum",
                native_enum=False,
                create_constraint=True,
            ),
            type_=sa.Enum(
                *_OLD_MEMBERS,
                name="settingclassenum",
                native_enum=False,
                create_constraint=True,
            ),
            existing_nullable=False,
        )
