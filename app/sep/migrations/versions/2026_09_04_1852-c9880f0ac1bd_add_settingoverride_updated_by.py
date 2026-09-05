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

"""add settingoverride updated_by

Revision ID: c9880f0ac1bd
Revises: 867df844fe17
Create Date: 2026-09-04 18:52:49.537386

Add the nullable ``settingoverride.updated_by`` column recording which admin
last saved each override. Deployed rows have no actor and cannot be backfilled,
so the column is nullable with no server default.

The table is shared with the Tasks and Inventory tracks, which add the same
column, so the helper guards on the column already being present and whichever
track runs first wins.

Downgrade drops the column, discarding every recorded actor; the rows and their
values survive.
"""

from app.core.settings_override.alembic_ops import (
    downgrade_drop_updated_by,
    upgrade_add_updated_by,
)

# revision identifiers, used by Alembic.
revision = "c9880f0ac1bd"
down_revision = "867df844fe17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the nullable ``updated_by`` column."""
    upgrade_add_updated_by()


def downgrade() -> None:
    """Drop ``updated_by``, discarding the recorded actors."""
    downgrade_drop_updated_by()
