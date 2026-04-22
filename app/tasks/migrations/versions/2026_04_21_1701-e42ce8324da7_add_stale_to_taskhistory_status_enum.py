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

"""add stale to taskhistory status enum

Revision ID: e42ce8324da7
Revises: 89e80a316a28
Create Date: 2026-04-21 17:01:47.283480

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e42ce8324da7'
down_revision: Union[str, None] = '89e80a316a28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('taskhistory', schema=None) as batch_op:
        batch_op.alter_column(
            'status',
            existing_type=sa.Enum(
                'FAILED', 'PENDING', 'RUNNING', 'SUCCESS', 'STOPPED', 'LOST',
                name='taskhistorystatusenum',
                native_enum=False,
            ),
            type_=sa.Enum(
                'FAILED', 'PENDING', 'RUNNING', 'SUCCESS', 'STOPPED', 'LOST', 'STALE',
                name='taskhistorystatusenum',
                native_enum=False,
            ),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table('taskhistory', schema=None) as batch_op:
        batch_op.alter_column(
            'status',
            existing_type=sa.Enum(
                'FAILED', 'PENDING', 'RUNNING', 'SUCCESS', 'STOPPED', 'LOST', 'STALE',
                name='taskhistorystatusenum',
                native_enum=False,
            ),
            type_=sa.Enum(
                'FAILED', 'PENDING', 'RUNNING', 'SUCCESS', 'STOPPED', 'LOST',
                name='taskhistorystatusenum',
                native_enum=False,
            ),
            existing_nullable=False,
        )
