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

"""extend setting_class enum with HEALTH_REPORT_SETTINGS

Revision ID: d1e2f3a4b5c6
Revises: cf94cc04be4b
Create Date: 2026-08-12 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

from app.core.db.utils import (
    acquire_pg_advisory_xact_lock,
    check_constraint_lists_members,
    check_constraint_name,
)
from app.core.settings_override.constants import SETTINGOVERRIDE_MIGRATION_LOCK_KEY

# revision identifiers, used by Alembic.
revision = "d1e2f3a4b5c6"
down_revision = "cf94cc04be4b"
branch_labels = None
depends_on = None

_OLD_MEMBERS = (
    "SEP_SETTINGS",
    "TASKS_SETTINGS",
    "SNIPPETS_SETTINGS",
    "SETTINGS",
    "ALERT_SETTINGS",
    "ANONYMIZER_SETTINGS",
    "ALERTS_SETTINGS",
    "INVENTORY_SETTINGS",
)
_NEW_MEMBERS = (*_OLD_MEMBERS, "HEALTH_REPORT_SETTINGS")


def upgrade() -> None:
    """Add ``HEALTH_REPORT_SETTINGS`` to the setting_class constraint."""
    bind = op.get_bind()
    acquire_pg_advisory_xact_lock(bind, SETTINGOVERRIDE_MIGRATION_LOCK_KEY)
    if check_constraint_name(bind, "settingoverride", "setting_class") is None:
        return
    if check_constraint_lists_members(
        bind, "settingoverride", "setting_class", ("HEALTH_REPORT_SETTINGS",)
    ):
        return
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
    """Remove ``HEALTH_REPORT_SETTINGS`` from the setting_class constraint."""
    bind = op.get_bind()
    acquire_pg_advisory_xact_lock(bind, SETTINGOVERRIDE_MIGRATION_LOCK_KEY)
    if not check_constraint_lists_members(
        bind, "settingoverride", "setting_class", ("HEALTH_REPORT_SETTINGS",)
    ):
        return
    op.execute(
        "DELETE FROM settingoverride WHERE setting_class IN ('HEALTH_REPORT_SETTINGS')"
    )
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
