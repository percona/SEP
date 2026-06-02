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

"""extend setting_class enum with SETTINGS and ALERT_SETTINGS

Revision ID: 6d4cfd37bd3a
Revises: fafdb0445092
Create Date: 2026-06-02 15:12:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "6d4cfd37bd3a"
down_revision = "fafdb0445092"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add ``SETTINGS`` and ``ALERT_SETTINGS`` to the setting_class constraint."""
    with op.batch_alter_table("settingoverride", schema=None) as batch_op:
        batch_op.alter_column(
            "setting_class",
            existing_type=sa.Enum(
                "SEP_SETTINGS",
                "TASKS_SETTINGS",
                "SNIPPETS_SETTINGS",
                "MESSAGES_SETTINGS",
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


def downgrade() -> None:
    """Remove ``SETTINGS`` and ``ALERT_SETTINGS`` from the setting_class constraint."""
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
                name="settingclassenum",
                native_enum=False,
                create_constraint=True,
            ),
            existing_nullable=False,
        )
