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
Revises: a19da5cf0bca
Create Date: 2026-07-30 13:00:00.000000

Rename the three Nomad-vocabulary log-cursor columns in place (metadata-only;
values preserved):

* ``taskhistory_log_state.nomad_offset`` → ``producer_fetch_offset``
* ``taskhistory_log_state.allocation_epoch`` → ``producer_epoch``
* ``taskhistory.log_allocation_epoch`` → ``log_producer_epoch``
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c8e4a2b91f70"
down_revision: Union[str, None] = "a19da5cf0bca"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LOG_STATE_RENAMES: tuple[tuple[str, str], ...] = (
    ("nomad_offset", "producer_fetch_offset"),
    ("allocation_epoch", "producer_epoch"),
)
_HISTORY_RENAMES: tuple[tuple[str, str], ...] = (
    ("log_allocation_epoch", "log_producer_epoch"),
)


def _apply_renames(table: str, pairs: tuple[tuple[str, str], ...]) -> None:
    """Apply each pending ``(old, new)`` column rename on ``table``.

    A pair is skipped when ``old`` is absent or ``new`` is already present, so a
    retry converges instead of erroring on the column it already renamed. That
    matters on a backend without transactional DDL, where a batch interrupted
    part-way can leave one column of a pair-set renamed and the other not.

    :param table: The table whose columns are renamed.
    :param pairs: The ``(old_name, new_name)`` pairs to apply.
    """
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns(table)}
    pending = [(old, new) for old, new in pairs if old in columns and new not in columns]
    if not pending:
        return
    with op.batch_alter_table(table, schema=None) as batch_op:
        for old, new in pending:
            batch_op.alter_column(old, new_column_name=new)


def upgrade() -> None:
    _apply_renames("taskhistory_log_state", _LOG_STATE_RENAMES)
    _apply_renames("taskhistory", _HISTORY_RENAMES)


def downgrade() -> None:
    _apply_renames(
        "taskhistory",
        tuple((new, old) for old, new in _HISTORY_RENAMES),
    )
    _apply_renames(
        "taskhistory_log_state",
        tuple((new, old) for old, new in _LOG_STATE_RENAMES),
    )
