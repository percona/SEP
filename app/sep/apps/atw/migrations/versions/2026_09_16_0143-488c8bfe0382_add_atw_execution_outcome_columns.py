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

"""add atw execution outcome columns

Adds the four columns that denormalize a run's outcome onto the SEP-side
execution row. Existing rows start unresolved: this migration performs no
upstream lookup and no backfill, because it runs synchronous SQL and has no
business issuing HTTP calls to the tasks service. The reconciliation sweep
fills them instead.

Revision ID: 488c8bfe0382
Revises: 447ee0172734
Create Date: 2026-09-16 01:43:24.804487

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision: str = "488c8bfe0382"
down_revision: Union[str, Sequence[str], None] = "447ee0172734"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "atw_incident_execution"
_INDEX = "ix_atw_incident_execution_terminal_status"
_COLUMN_NAMES = (
    "terminal_status",
    "finished_at",
    "outcome_unrecoverable",
    "reconcile_attempted_at",
)


def _new_columns() -> tuple[sa.Column, ...]:
    """Build the columns this revision adds, fresh on every call.

    ``op.add_column`` binds the ``Column`` it is handed to a table, so a
    module-level tuple could only ever be added once per process.

    :return: The four outcome columns, in the order they are added.
    """
    return (
        sa.Column("terminal_status", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        # The server_default outlives this revision deliberately: migrations run
        # ahead of the code rollout, so a release still on the previous code
        # inserts without the column until it restarts.
        sa.Column(
            "outcome_unrecoverable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("reconcile_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns(_TABLE)}
    for column in _new_columns():
        if column.name not in existing_columns:
            op.add_column(_TABLE, column)
    existing_indexes = {index["name"] for index in inspector.get_indexes(_TABLE)}
    if _INDEX not in existing_indexes:
        op.create_index(op.f(_INDEX), _TABLE, ["terminal_status"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    existing_indexes = {index["name"] for index in inspector.get_indexes(_TABLE)}
    if _INDEX in existing_indexes:
        op.drop_index(op.f(_INDEX), table_name=_TABLE)
    existing_columns = {column["name"] for column in inspector.get_columns(_TABLE)}
    for name in reversed(_COLUMN_NAMES):
        if name in existing_columns:
            op.drop_column(_TABLE, name)
