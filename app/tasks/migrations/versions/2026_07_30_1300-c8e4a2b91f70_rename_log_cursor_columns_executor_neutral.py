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

"""rename Nomad-named log cursor columns to executor-neutral names

Revision ID: c8e4a2b91f70
Revises: 27a11549ef43
Create Date: 2026-07-30 13:00:00.000000

Rename the three Nomad-vocabulary log-cursor columns in place (metadata-only;
values preserved):

* ``taskhistory_log_state.nomad_offset`` → ``producer_fetch_offset``
* ``taskhistory_log_state.allocation_epoch`` → ``producer_epoch``
* ``taskhistory.log_allocation_epoch`` → ``log_producer_epoch``
"""
from typing import Sequence, Union

from alembic import op


revision: str = "c8e4a2b91f70"
down_revision: Union[str, None] = "27a11549ef43"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "taskhistory_log_state",
        "nomad_offset",
        new_column_name="producer_fetch_offset",
    )
    op.alter_column(
        "taskhistory_log_state",
        "allocation_epoch",
        new_column_name="producer_epoch",
    )
    op.alter_column(
        "taskhistory",
        "log_allocation_epoch",
        new_column_name="log_producer_epoch",
    )


def downgrade() -> None:
    op.alter_column(
        "taskhistory",
        "log_producer_epoch",
        new_column_name="log_allocation_epoch",
    )
    op.alter_column(
        "taskhistory_log_state",
        "producer_epoch",
        new_column_name="allocation_epoch",
    )
    op.alter_column(
        "taskhistory_log_state",
        "producer_fetch_offset",
        new_column_name="nomad_offset",
    )
