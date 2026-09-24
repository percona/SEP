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
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '867df844fe17'
down_revision: Union[str, None] = '74720aeda25b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Both columns are VARCHAR + CHECK, so neither touches the native PostgreSQL
# enum types ``syncitem`` still owns. The shared names land in pg_constraint
# rather than pg_type, so nothing collides with those types.
# ``create_constraint`` is False here and the CHECK is added explicitly below.
# The two dialects disagree about what ``add_column`` does with an implicit
# constraint: PostgreSQL emits it, SQLite warns and skips. Leaving it on would
# therefore produce the constraint twice on PostgreSQL -- once implicitly, once
# from the explicit call SQLite needs -- and abort the upgrade there while the
# SQLite suite stayed green.
sync_status_enum = sa.Enum(
    'PENDING',
    'RUNNING',
    'SUCCESS',
    'FAILED',
    name='syncstatusenum',
    native_enum=False,
    create_constraint=False,
)
entity_type_enum = sa.Enum(
    'INVENTORY',
    'NODE',
    'SERVICE',
    'SCHEMA',
    'TABLE',
    name='syncinventoryentitytypeenum',
    native_enum=False,
    create_constraint=True,
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
    # The server default backfills rows that predate the column, and then stays:
    # migrations run ahead of the code rollout, so a release still running the
    # previous code inserts a SyncInstance without ``status`` until it restarts.
    op.add_column(
        'syncinstance',
        sa.Column('status', sync_status_enum, nullable=False, server_default='PENDING'),
    )
    # Derive a terminal status for runs that predate the column, applying the same
    # rule finalize_run applies going forward. Without this every historical run
    # reads back as PENDING, and the sync-status endpoint reports finished runs as
    # still pending until enough new runs displace them.
    op.execute(
        """
        UPDATE syncinstance SET status = 'FAILED'
        WHERE id IN (
            SELECT sync_instance_id FROM syncitem WHERE status = 'FAILED'
        )
        """
    )
    op.execute(
        """
        UPDATE syncinstance SET status = 'SUCCESS'
        WHERE status = 'PENDING'
          AND id IN (SELECT sync_instance_id FROM syncitem)
          AND id NOT IN (
              SELECT sync_instance_id FROM syncitem
              WHERE status IN ('PENDING', 'RUNNING', 'FAILED')
          )
        """
    )
    # The single source of the CHECK on every dialect, run after the backfill so
    # SQLite's table rebuild validates rows that already satisfy it. The name
    # matches the one the model's metadata derives, so a create_all schema and a
    # migrated schema carry the same constraint.
    with op.batch_alter_table('syncinstance') as batch_op:
        batch_op.create_check_constraint(
            'syncstatusenum',
            "status IN ('PENDING', 'RUNNING', 'SUCCESS', 'FAILED')",
        )
    op.add_column('syncinstance', sa.Column('snapshot_complete', sa.Boolean(), nullable=True))
    op.create_index(op.f('ix_syncinstance_snapshot_complete'), 'syncinstance', ['snapshot_complete'], unique=False)
    op.create_index(op.f('ix_syncinstance_status'), 'syncinstance', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_syncinstance_status'), table_name='syncinstance')
    op.drop_index(op.f('ix_syncinstance_snapshot_complete'), table_name='syncinstance')
    op.drop_column('syncinstance', 'snapshot_complete')
    # The CHECK is dropped in the same batch as the column it constrains: SQLite
    # rebuilds the table from reflection, so a constraint left behind would be
    # re-emitted against a column that no longer exists.
    with op.batch_alter_table('syncinstance') as batch_op:
        batch_op.drop_constraint('syncstatusenum', type_='check')
        batch_op.drop_column('status')
    op.drop_index(op.f('ix_syncentityabsence_entity_type'), table_name='syncentityabsence')
    op.drop_index(op.f('ix_syncentityabsence_entity_id'), table_name='syncentityabsence')
    op.drop_table('syncentityabsence')
