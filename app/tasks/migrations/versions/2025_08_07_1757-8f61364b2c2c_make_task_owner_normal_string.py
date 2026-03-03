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

"""Make task owner normal string

Revision ID: 8f61364b2c2c
Revises: 19605d228fa3
Create Date: 2025-08-07 17:57:30.811801

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '8f61364b2c2c'
down_revision: Union[str, None] = '19605d228fa3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('task', schema=None) as batch_op:
        batch_op.alter_column('owner',
                   existing_type=sa.Enum('ANY', 'ALTERS', 'ARCHIVER', 'BACKUPS', 'CHECKSUMS', 'BACKUP_MONGO', name='taskowner', native_enum=False),
                   type_=sqlmodel.sql.sqltypes.AutoString(),
                   existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table('task', schema=None) as batch_op:
        batch_op.alter_column('owner',
                   existing_type=sqlmodel.sql.sqltypes.AutoString(),
                   type_=sa.Enum('ANY', 'ALTERS', 'ARCHIVER', 'BACKUPS', 'CHECKSUMS', 'BACKUP_MONGO', name='taskowner', native_enum=False),
                   existing_nullable=False)
