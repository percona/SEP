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

"""add unlaunchable to taskhistory status enum

Revision ID: 3a4dfc2a2be8
Revises: 7d2e869ac188
Create Date: 2026-09-01 13:29:15.648532

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3a4dfc2a2be8'
down_revision: Union[str, Sequence[str], None] = '7d2e869ac188'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_MEMBERS = ('FAILED', 'PENDING', 'RUNNING', 'SUCCESS', 'STOPPED', 'LOST', 'STALE')
_NEW_MEMBERS = (*_OLD_MEMBERS, 'UNLAUNCHABLE')


def _status_enum(*members: str) -> sa.Enum:
    return sa.Enum(*members, name='taskhistorystatusenum', native_enum=False)


def upgrade() -> None:
    """Widen ``taskhistory.status`` so it can hold the new member's name.

    The column stores the enum member *name*, and ``UNLAUNCHABLE`` is twelve
    characters against the existing ``VARCHAR(7)``, so PostgreSQL rejects the
    write without this widening. SQLite ignores ``VARCHAR`` length, so the test
    suite cannot surface the failure.
    """
    with op.batch_alter_table('taskhistory', schema=None) as batch_op:
        batch_op.alter_column(
            'status',
            existing_type=_status_enum(*_OLD_MEMBERS),
            type_=_status_enum(*_NEW_MEMBERS),
            existing_nullable=False,
        )


def downgrade() -> None:
    """Re-label ``UNLAUNCHABLE`` rows, then narrow the column back.

    Narrowing to ``VARCHAR(7)`` aborts on PostgreSQL while any twelve-character
    ``UNLAUNCHABLE`` value remains, so those rows are remapped to ``FAILED``
    first -- the status they carried before this feature existed. Without the
    remap the downgrade is unrunnable exactly once the feature has been used.
    """
    op.execute(
        sa.text(
            "UPDATE taskhistory SET status = 'FAILED' WHERE status = 'UNLAUNCHABLE'"
        )
    )
    with op.batch_alter_table('taskhistory', schema=None) as batch_op:
        batch_op.alter_column(
            'status',
            existing_type=_status_enum(*_NEW_MEMBERS),
            type_=_status_enum(*_OLD_MEMBERS),
            existing_nullable=False,
        )
