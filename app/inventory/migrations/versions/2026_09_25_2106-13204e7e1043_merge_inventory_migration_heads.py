"""merge inventory migration heads

Revision ID: 13204e7e1043
Revises: 0553c4e5a34a, c5a72c6cdbf4
Create Date: 2026-09-25 21:06:55.968997

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '13204e7e1043'
down_revision: Union[str, Sequence[str], None] = ('0553c4e5a34a', 'c5a72c6cdbf4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
