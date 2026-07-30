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

"""add taskhistory log_allocation_epoch high-water column

Revision ID: a1f4c9e2b7d8
Revises: 8657d05d27da
Create Date: 2026-07-03 12:00:00.000000

Add a task-level current-allocation-epoch high-water mark (``log_allocation_epoch``,
the Nomad ``CreateIndex``) on ``taskhistory``. The log writer stamps it whenever the
allocation frontier is reset and consults it on the first-insert path — before any
per-stream ``taskhistory_log_state`` row exists — so a lagging sync from a superseded
allocation is discarded instead of persisting a stale prefix at the old epoch.

The column defaults to ``0`` (the legacy/unknown sentinel already trusted by the
per-stream seed and write guards); no backfill is required because a first-insert write
carrying a real ``CreateIndex`` is never older than ``0``.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a1f4c9e2b7d8"
down_revision: Union[str, None] = "8657d05d27da"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "taskhistory",
        sa.Column(
            "log_allocation_epoch",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("taskhistory", "log_allocation_epoch")
