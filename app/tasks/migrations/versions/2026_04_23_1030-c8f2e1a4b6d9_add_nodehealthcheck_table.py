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

"""Create NodeHealthCheck table

Revision ID: c8f2e1a4b6d9
Revises: e42ce8324da7
Create Date: 2026-04-23 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'c8f2e1a4b6d9'
down_revision: Union[str, None] = 'e42ce8324da7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'nodehealthcheck',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'node_name',
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column('healthy', sa.Boolean(), nullable=False),
        sa.Column('last_checked', sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            'error_message',
            sqlmodel.sql.sqltypes.AutoString(length=1024),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_nodehealthcheck_node_name'),
        'nodehealthcheck',
        ['node_name'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_nodehealthcheck_node_name'),
        table_name='nodehealthcheck',
    )
    op.drop_table('nodehealthcheck')
