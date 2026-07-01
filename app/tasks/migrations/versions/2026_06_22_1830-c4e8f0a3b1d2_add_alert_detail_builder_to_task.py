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

"""Add alert_detail_builder to Task

Also merges the two pre-existing tasks-track heads (``6d4cfd37bd3a`` and
``7d1232c0e3ce``) that diverged at the ``e42ce8324da7`` branchpoint, converging
the track back to a single head.

Revision ID: c4e8f0a3b1d2
Revises: 6d4cfd37bd3a, 7d1232c0e3ce
Create Date: 2026-06-22 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'c4e8f0a3b1d2'
down_revision: Union[str, Sequence[str], None] = ('6d4cfd37bd3a', '7d1232c0e3ce')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Builder path stamped onto archiver tasks at creation. Backfilled here so
# archiver tasks created before this column existed keep their failure-alert
# enrichment without needing to be recreated.
_ARCHIVER_BUILDER = "app.sep.apps.archives.alerts:build_owner_alert_details"


def upgrade() -> None:
    op.add_column(
        'task',
        sa.Column('alert_detail_builder', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE task SET alert_detail_builder = :builder "
            "WHERE owner = 'ARCHIVER' AND alert_detail_builder IS NULL"
        ).bindparams(builder=_ARCHIVER_BUILDER)
    )


def downgrade() -> None:
    op.drop_column('task', 'alert_detail_builder')
