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

"""extend setting_class enum with ANONYMIZER_SETTINGS

Revision ID: abc65df0318a
Revises: 6d4cfd37bd3a
Create Date: 2026-06-22 14:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

from app.core.db.utils import (
    acquire_pg_advisory_xact_lock,
    check_constraint_lists_members,
)
from app.core.settings_override.constants import SETTINGOVERRIDE_MIGRATION_LOCK_KEY

# revision identifiers, used by Alembic.
revision = "abc65df0318a"
down_revision = "6d4cfd37bd3a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add ``ANONYMIZER_SETTINGS`` to the setting_class constraint."""
    bind = op.get_bind()
    acquire_pg_advisory_xact_lock(bind, SETTINGOVERRIDE_MIGRATION_LOCK_KEY)
    if check_constraint_lists_members(
        bind, "settingoverride", "setting_class", ("ANONYMIZER_SETTINGS",)
    ):
        return
    with op.batch_alter_table("settingoverride", schema=None) as batch_op:
        batch_op.alter_column(
            "setting_class",
            existing_type=sa.Enum(
                "SEP_SETTINGS",
                "TASKS_SETTINGS",
                "SNIPPETS_SETTINGS",
                "MESSAGES_SETTINGS",
                "SETTINGS",
                "ALERT_SETTINGS",
                name="settingclassenum",
                native_enum=False,
                create_constraint=True,
            ),
            type_=sa.Enum(
                "SEP_SETTINGS",
                "TASKS_SETTINGS",
                "SNIPPETS_SETTINGS",
                "MESSAGES_SETTINGS",
                "SETTINGS",
                "ALERT_SETTINGS",
                "ANONYMIZER_SETTINGS",
                name="settingclassenum",
                native_enum=False,
                create_constraint=True,
            ),
            existing_nullable=False,
        )


def downgrade() -> None:
    """Remove ``ANONYMIZER_SETTINGS`` from the setting_class constraint."""
    bind = op.get_bind()
    acquire_pg_advisory_xact_lock(bind, SETTINGOVERRIDE_MIGRATION_LOCK_KEY)
    if not check_constraint_lists_members(
        bind, "settingoverride", "setting_class", ("ANONYMIZER_SETTINGS",)
    ):
        return
    # Discard override rows using the removed member first; otherwise the
    # narrowed CHECK constraint rejects the existing data and the ALTER fails.
    # Rolling this migration back intentionally drops the overrides it enabled.
    op.execute(
        "DELETE FROM settingoverride WHERE setting_class IN ('ANONYMIZER_SETTINGS')"
    )
    with op.batch_alter_table("settingoverride", schema=None) as batch_op:
        batch_op.alter_column(
            "setting_class",
            existing_type=sa.Enum(
                "SEP_SETTINGS",
                "TASKS_SETTINGS",
                "SNIPPETS_SETTINGS",
                "MESSAGES_SETTINGS",
                "SETTINGS",
                "ALERT_SETTINGS",
                "ANONYMIZER_SETTINGS",
                name="settingclassenum",
                native_enum=False,
                create_constraint=True,
            ),
            type_=sa.Enum(
                "SEP_SETTINGS",
                "TASKS_SETTINGS",
                "SNIPPETS_SETTINGS",
                "MESSAGES_SETTINGS",
                "SETTINGS",
                "ALERT_SETTINGS",
                name="settingclassenum",
                native_enum=False,
                create_constraint=True,
            ),
            existing_nullable=False,
        )
