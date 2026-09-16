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


# revision identifiers, used by Alembic.
revision: str = "488c8bfe0382"
down_revision: Union[str, Sequence[str], None] = "447ee0172734"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "atw_incident_execution"
_INDEX = "ix_atw_incident_execution_terminal_status"
#: Name SQLAlchemy derives for the status enum's CHECK from the model side, so a
#: database built by this revision and one built from the metadata agree and
#: autogenerate reports no drift between them.
_STATUS_CONSTRAINT = "taskhistorystatusenum"
#: The enum's member *names*, which are what the column stores.
_STATUS_NAMES = (
    "FAILED",
    "PENDING",
    "RUNNING",
    "SUCCESS",
    "STOPPED",
    "LOST",
    "STALE",
    "UNLAUNCHABLE",
)


def _new_columns() -> tuple[sa.Column, ...]:
    """Build the columns this revision adds, fresh on every call.

    ``op.add_column`` binds the ``Column`` it is handed to a table, so a
    module-level tuple could only ever be added once per process.

    :return: The four outcome columns, in the order they are added.
    """
    return (
        sa.Column(
            "terminal_status",
            # create_constraint is off here and the CHECK is added once, explicitly,
            # in upgrade(). Leaving it on emits the constraint from the column *and*
            # again from the table rebuild batch mode performs, which lands two
            # identically-named CHECKs on SQLite.
            sa.Enum(
                *_STATUS_NAMES,
                name=_STATUS_CONSTRAINT,
                native_enum=False,
                create_constraint=False,
            ),
            nullable=True,
        ),
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
    pending = [c for c in _new_columns() if c.name not in existing_columns]
    if pending:
        # Batch mode, not a bare add_column: SQLite cannot ALTER a table to attach a
        # CHECK constraint and merely warns that it skipped it, which would leave the
        # status column unconstrained on the default engine while PostgreSQL got the
        # constraint. Batch mode recreates the table, so both engines end up with it.
        with op.batch_alter_table(_TABLE) as batch_op:
            for column in pending:
                batch_op.add_column(column)
            batch_op.create_check_constraint(
                _STATUS_CONSTRAINT,
                sa.column("terminal_status").in_(_STATUS_NAMES),
            )
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
    doomed = [c for c in reversed(_new_columns()) if c.name in existing_columns]
    if doomed:
        # One batch block for the constraint and the columns: on SQLite each block is
        # a full table rebuild, and dropping the CHECK first keeps the rebuilt table
        # from carrying a constraint over a column that no longer exists.
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.drop_constraint(_STATUS_CONSTRAINT, type_="check")
            for column in doomed:
                batch_op.drop_column(column.name)
