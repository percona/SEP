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

"""add service_id to mysql_backup_run

Revision ID: b7c8d9e0f1a2
Revises: f0a1b2c3d4e5
Create Date: 2026-08-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import Connection


# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "mysql_backup_run"
COLUMN = "service_id"
INDEX = "ix_mysql_backup_run_service_id"


def _table_state(bind: Connection) -> tuple[set[str], set[str]]:
    """Return the column names and index names on ``mysql_backup_run``.

    :param bind: The active migration connection.
    :return: The table's column names and index names, both empty when the table
        is absent.
    """
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        return set(), set()
    return (
        {column["name"] for column in inspector.get_columns(TABLE)},
        {index["name"] for index in inspector.get_indexes(TABLE)},
    )


def upgrade() -> None:
    columns, indexes = _table_state(op.get_bind())
    # The column and the index are guarded separately: a schema created from the
    # models, or hand-patched with a bare ALTER, can carry one without the other.
    if COLUMN not in columns:
        op.add_column(TABLE, sa.Column(COLUMN, sa.Integer(), nullable=True))
    if INDEX not in indexes:
        op.create_index(op.f(INDEX), TABLE, [COLUMN], unique=False)


def downgrade() -> None:
    columns, indexes = _table_state(op.get_bind())
    if INDEX in indexes:
        op.drop_index(op.f(INDEX), table_name=TABLE)
    if COLUMN in columns:
        op.drop_column(TABLE, COLUMN)
