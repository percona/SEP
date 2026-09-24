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

"""add source_transport to mysql_backup_run

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-09-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import Connection


# revision identifiers, used by Alembic.
revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "mysql_backup_run"
COLUMN = "source_transport"
# Member names (not wire values): matches EnumField(CataloguedSourceTransport)
# default persistence and the CHECK name SQLAlchemy metadata emits for the model.
_TRANSPORT_MEMBERS = ("S3", "GCS")
CHECK_NAME = "cataloguedsourcetransport"
CHECK_SQL = f"{COLUMN} IN ({', '.join(repr(member) for member in _TRANSPORT_MEMBERS)})"

# ``create_constraint`` is False here and the CHECK is added explicitly below.
# PostgreSQL would emit an implicit CHECK from ``add_column`` when True, while
# SQLite warns and skips — leaving it on would create the constraint twice on
# PostgreSQL once the explicit call SQLite needs also runs.
_source_transport_type = sa.Enum(
    *_TRANSPORT_MEMBERS,
    name=CHECK_NAME,
    native_enum=False,
    create_constraint=False,
)


def _table_state(bind: Connection) -> tuple[set[str], set[str]]:
    """Return the column names and check-constraint names on ``mysql_backup_run``.

    :param bind: The active migration connection.
    :return: The table's column names and check-constraint names, both empty when
        the table is absent.
    """
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        return set(), set()
    return (
        {column["name"] for column in inspector.get_columns(TABLE)},
        {constraint["name"] for constraint in inspector.get_check_constraints(TABLE)},
    )


def upgrade() -> None:
    columns, checks = _table_state(op.get_bind())
    if not columns and not checks:
        return
    # Column and CHECK are guarded separately: a schema created from the models,
    # or hand-patched with a bare ALTER, can carry one without the other.
    if COLUMN not in columns:
        op.add_column(
            TABLE, sa.Column(COLUMN, _source_transport_type, nullable=True)
        )
    if CHECK_NAME not in checks:
        with op.batch_alter_table(TABLE) as batch_op:
            batch_op.create_check_constraint(CHECK_NAME, CHECK_SQL)


def downgrade() -> None:
    columns, checks = _table_state(op.get_bind())
    if not columns and not checks:
        return
    # Drop the CHECK in the same batch as the column: SQLite rebuilds from
    # reflection, so a constraint left behind would be re-emitted against a
    # column that no longer exists.
    with op.batch_alter_table(TABLE) as batch_op:
        if CHECK_NAME in checks:
            batch_op.drop_constraint(CHECK_NAME, type_="check")
        if COLUMN in columns:
            batch_op.drop_column(COLUMN)
