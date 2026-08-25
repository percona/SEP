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

"""add sync run state and entity absence ledger

Revision ID: 867df844fe17
Revises: 74720aeda25b
Create Date: 2026-08-25 19:02:13.519957

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '867df844fe17'
down_revision: Union[str, None] = '74720aeda25b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Both enum types already exist -- ``syncitem`` created them in 7f4dec8bc76a and
# still uses them. Autogenerate emits a plain ``sa.Enum``, which re-emits CREATE
# TYPE and fails with DuplicateObject, so both columns declare the existing type
# with ``create_type=False``. For the same reason ``downgrade`` drops neither
# type.
sync_status_enum = postgresql.ENUM(
    'PENDING',
    'RUNNING',
    'SUCCESS',
    'FAILED',
    name='syncstatusenum',
    create_type=False,
)
entity_type_enum = postgresql.ENUM(
    'INVENTORY',
    'NODE',
    'SERVICE',
    'SCHEMA',
    'TABLE',
    name='syncinventoryentitytypeenum',
    create_type=False,
)


def upgrade() -> None:
    op.create_table('syncentityabsence',
    sa.Column('syncer', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('entity_id', sa.Integer(), nullable=False),
    sa.Column('entity_type', entity_type_enum, nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('missing_generations', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('syncer', 'entity_type', 'entity_id', name='uq_syncentityabsence_entity')
    )
    op.create_index(op.f('ix_syncentityabsence_entity_id'), 'syncentityabsence', ['entity_id'], unique=False)
    op.create_index(op.f('ix_syncentityabsence_entity_type'), 'syncentityabsence', ['entity_type'], unique=False)
    op.create_index(op.f('ix_syncentityabsence_syncer'), 'syncentityabsence', ['syncer'], unique=False)
    # The server default backfills rows that predate the column; it is dropped
    # immediately afterwards so the model's Python-side default stays the only
    # source of the value. SQLite (tests, local dev) has no DROP DEFAULT, and
    # leaving the default in place there is harmless.
    op.add_column(
        'syncinstance',
        sa.Column('status', sync_status_enum, nullable=False, server_default='PENDING'),
    )
    if op.get_bind().dialect.name != 'sqlite':
        op.alter_column('syncinstance', 'status', server_default=None)
    op.add_column('syncinstance', sa.Column('snapshot_complete', sa.Boolean(), nullable=True))
    op.create_index(op.f('ix_syncinstance_snapshot_complete'), 'syncinstance', ['snapshot_complete'], unique=False)
    op.create_index(op.f('ix_syncinstance_status'), 'syncinstance', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_syncinstance_status'), table_name='syncinstance')
    op.drop_index(op.f('ix_syncinstance_snapshot_complete'), table_name='syncinstance')
    op.drop_column('syncinstance', 'snapshot_complete')
    op.drop_column('syncinstance', 'status')
    op.drop_index(op.f('ix_syncentityabsence_syncer'), table_name='syncentityabsence')
    op.drop_index(op.f('ix_syncentityabsence_entity_type'), table_name='syncentityabsence')
    op.drop_index(op.f('ix_syncentityabsence_entity_id'), table_name='syncentityabsence')
    op.drop_table('syncentityabsence')
