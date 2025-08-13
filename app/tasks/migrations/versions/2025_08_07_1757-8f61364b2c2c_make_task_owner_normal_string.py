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
