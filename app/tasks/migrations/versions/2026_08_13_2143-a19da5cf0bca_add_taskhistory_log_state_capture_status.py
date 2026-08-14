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

"""add taskhistory_log_state capture_status

Revision ID: a19da5cf0bca
Revises: 6a19d56d7985
Create Date: 2026-08-13 21:43:58.711511

Add a per-``(source, stream)`` capture verdict on ``taskhistory_log_state`` so a
reader can tell a stream that genuinely produced nothing from one whose bytes
were lost before SEP read them. The stored offsets cannot distinguish the two:
both leave the cursors at zero.

Existing rows — including every row stranded at ``producer_offset = 0`` by the
lost-log defect — take ``unknown`` from the server default. That is deliberate
and there is no backfill: the source bytes are already garbage-collected, so
which of the two populations a given row belongs to is unrecoverable, and
``unknown`` is the only honest classification.

The server default is ``UNKNOWN`` while the model default is ``INCOMPLETE``, and
the difference is load-bearing. SQLAlchemy always sends the column on INSERT, so
the server default governs only these pre-existing rows; rows written after the
upgrade start ``INCOMPLETE`` and are upgraded once their stream drains to EOF.

Both are spelled as enum *member names*, not member values: ``sa.Enum`` persists
``.name``, so a server default of ``"unknown"`` would write a string the mapped
type cannot read back, and every backfilled row would raise ``LookupError`` on
the first ORM read.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a19da5cf0bca"
down_revision: Union[str, None] = "6a19d56d7985"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "taskhistory_log_state",
        sa.Column(
            "capture_status",
            sa.Enum(
                "COMPLETE",
                "INCOMPLETE",
                "UNKNOWN",
                name="logcapturestatusenum",
                native_enum=False,
            ),
            nullable=False,
            server_default="UNKNOWN",
        ),
    )


def downgrade() -> None:
    op.drop_column("taskhistory_log_state", "capture_status")
