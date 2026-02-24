"""Add index on syncinstance.syncer

Revision ID: a1b2c3d4e5f6
Revises: 9307f0f5ee54
Create Date: 2025-02-24 18:01:00

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '9307f0f5ee54'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        op.f('ix_syncinstance_syncer'),
        'syncinstance',
        ['syncer'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_syncinstance_syncer'), table_name='syncinstance')
