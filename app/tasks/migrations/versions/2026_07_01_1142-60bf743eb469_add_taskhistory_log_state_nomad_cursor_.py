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

"""add taskhistory_log_state nomad cursor columns

Revision ID: 60bf743eb469
Revises: f028a195fbda
Create Date: 2026-07-01 11:42:45.769667

Persist the raw Nomad log fetch cursor (``nomad_offset``) and the allocation it
belongs to (``allocation_epoch``, the Nomad ``CreateIndex``) on
``taskhistory_log_state`` so a worker without the process-local in-memory cursor
resumes the fetch instead of re-reading the whole log file from offset 0.

The backfill seeds ``nomad_offset = producer_offset`` for in-flight rows so the
first post-deploy sync does not re-read from 0. ``allocation_epoch`` stays 0
(the legacy/unknown sentinel), which the seed guard trusts until the first
post-deploy write advances it to the live allocation's ``CreateIndex``. The
backfill is exact for non-anonymized streams (raw == producer) and a bounded
approximation for anonymized run-script/step1 streams.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "60bf743eb469"
down_revision: Union[str, None] = "f028a195fbda"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "taskhistory_log_state",
        sa.Column("nomad_offset", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "taskhistory_log_state",
        sa.Column(
            "allocation_epoch", sa.BigInteger(), nullable=False, server_default="0"
        ),
    )
    op.execute("UPDATE taskhistory_log_state SET nomad_offset = producer_offset")


def downgrade() -> None:
    op.drop_column("taskhistory_log_state", "allocation_epoch")
    op.drop_column("taskhistory_log_state", "nomad_offset")
