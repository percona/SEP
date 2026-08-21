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

"""extend setting_class enum with OM_INVENTORY_SETTINGS

The member list is kept converged across all three tracks even though
``OmInventorySettings`` is an app-owned class collected only on the SEP side
(``build_sep_override_proxies``), so its rows are only ever written to the SEP
database. Diverging constraints would make "which members are allowed" a question
about which database you happen to be looking at, and the same reasoning already
produced the ``ALERTS_SETTINGS`` and ``INVENTORY_SETTINGS`` migrations here.

Revision ID: e3f4a5b6c7d8
Revises: f3a4b5c6d7e8
Create Date: 2026-08-17 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

from app.core.db.utils import (
    acquire_pg_advisory_xact_lock,
    check_constraint_lists_members,
)
from app.core.settings_override.constants import SETTINGOVERRIDE_MIGRATION_LOCK_KEY

# revision identifiers, used by Alembic.
revision = "e3f4a5b6c7d8"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None

_EXISTING_MEMBERS = (
    "SEP_SETTINGS",
    "TASKS_SETTINGS",
    "SNIPPETS_SETTINGS",
    "SETTINGS",
    "ALERT_SETTINGS",
    "ANONYMIZER_SETTINGS",
    "ALERTS_SETTINGS",
    "INVENTORY_SETTINGS",
    "HEALTH_REPORT_SETTINGS",
)
_NEW_MEMBERS = (*_EXISTING_MEMBERS, "OM_INVENTORY_SETTINGS")


def upgrade() -> None:
    """Add ``OM_INVENTORY_SETTINGS`` to the setting_class constraint."""
    bind = op.get_bind()
    acquire_pg_advisory_xact_lock(bind, SETTINGOVERRIDE_MIGRATION_LOCK_KEY)
    if check_constraint_lists_members(
        bind, "settingoverride", "setting_class", ("OM_INVENTORY_SETTINGS",)
    ):
        return
    with op.batch_alter_table("settingoverride", schema=None) as batch_op:
        batch_op.alter_column(
            "setting_class",
            existing_type=sa.Enum(
                *_EXISTING_MEMBERS,
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
    """Remove ``OM_INVENTORY_SETTINGS`` from the setting_class constraint."""
    bind = op.get_bind()
    acquire_pg_advisory_xact_lock(bind, SETTINGOVERRIDE_MIGRATION_LOCK_KEY)
    if not check_constraint_lists_members(
        bind, "settingoverride", "setting_class", ("OM_INVENTORY_SETTINGS",)
    ):
        return
    # Discard override rows using the removed member first; otherwise the
    # narrowed CHECK constraint rejects the existing data and the ALTER fails.
    op.execute(
        "DELETE FROM settingoverride WHERE setting_class IN ('OM_INVENTORY_SETTINGS')"
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
                *_EXISTING_MEMBERS,
                name="settingclassenum",
                native_enum=False,
                create_constraint=True,
            ),
            existing_nullable=False,
        )
