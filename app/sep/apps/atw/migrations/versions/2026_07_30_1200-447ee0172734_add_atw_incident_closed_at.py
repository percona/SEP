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

"""add atw incident closed_at

Revision ID: 447ee0172734
Revises: c93998e0fa14
Create Date: 2026-07-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "447ee0172734"
down_revision: Union[str, None] = "c93998e0fa14"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()
    if "atw_incident" not in existing_tables:
        return
    existing_columns = {column["name"] for column in inspector.get_columns("atw_incident")}
    if "closed_at" not in existing_columns:
        op.add_column(
            "atw_incident",
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()
    if "atw_incident" not in existing_tables:
        return
    existing_columns = {column["name"] for column in inspector.get_columns("atw_incident")}
    if "closed_at" in existing_columns:
        op.drop_column("atw_incident", "closed_at")
