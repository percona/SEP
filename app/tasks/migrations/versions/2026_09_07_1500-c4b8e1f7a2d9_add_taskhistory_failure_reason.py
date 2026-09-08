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

"""add taskhistory failure_reason

Revision ID: c4b8e1f7a2d9
Revises: 8fdfa7869662
Create Date: 2026-09-07 15:00:00.000000

Add the nullable ``taskhistory.failure_reason`` column carrying a single-line,
operator-facing reason for a run's outcome. Existing rows read ``NULL`` and no
backfill is performed: the reasons are composed at failure time from state the
writers hold, which a historic row no longer has.

A ``NULL`` on a ``failed`` row therefore means "unknown", not "did not fail".

Downgrade drops the column, discarding every recorded reason; the rows and their
statuses survive.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c4b8e1f7a2d9"
down_revision = "8fdfa7869662"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the nullable ``taskhistory.failure_reason`` column."""
    op.add_column(
        "taskhistory",
        sa.Column("failure_reason", sa.String(), nullable=True),
    )


def downgrade() -> None:
    """Drop ``failure_reason``, discarding every recorded reason."""
    op.drop_column("taskhistory", "failure_reason")
