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

"""add can_elevate to host system observation

Revision ID: b351dd0aaed8
Revises: 168ac77b6775
Create Date: 2026-09-16 02:12:17.872100

Add ``can_elevate`` to the host system observation, recording whether a node can
run privileged work.

Nullable with no server default: the column is a tri-state, and an existing row
means "never observed" rather than "unable". A ``False`` here is a measurement,
so the absence has to stay distinguishable from it.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b351dd0aaed8"
down_revision = "168ac77b6775"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the nullable ``can_elevate`` column."""
    op.add_column(
        "hostsystemobservation",
        sa.Column("can_elevate", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    """Drop the ``can_elevate`` column."""
    op.drop_column("hostsystemobservation", "can_elevate")
