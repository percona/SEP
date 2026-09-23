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

"""add bootstrap_run's data_path/log_path/port/bind_ip

Revision ID: 2773844e362d
Revises: 130e97b1c430
Create Date: 2026-09-09 10:00:00.000000

Hand-written, matching ``130e97b1c430``'s own note on why: autogenerate proposes
a wrong diff against this table.

PMM-15347/plan.md §6 Phase A: these were fixed module constants in
``strategies/packages.py`` (``/var/lib/mongo``, ``/var/log/mongodb/mongod.log``,
``27017``, ``0.0.0.0``) until the Configure step grew fields for them. The
``server_default`` values here are exactly those constants, so every row a
pre-Phase-A run already wrote keeps reading back as the paths/port it actually
used.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.sep.apps.shared.om.config import om_schema
from app.sep.config import sep_settings


# revision identifiers, used by Alembic.
revision: str = "2773844e362d"
down_revision: Union[str, None] = "130e97b1c430"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    schema = om_schema(sep_settings.DATABASE)
    op.add_column(
        "bootstrap_run",
        sa.Column(
            "data_path", sa.Text(), nullable=False, server_default="/var/lib/mongo"
        ),
        schema=schema,
    )
    op.add_column(
        "bootstrap_run",
        sa.Column(
            "log_path",
            sa.Text(),
            nullable=False,
            server_default="/var/log/mongodb/mongod.log",
        ),
        schema=schema,
    )
    op.add_column(
        "bootstrap_run",
        sa.Column(
            "port", sa.Integer(), nullable=False, server_default="27017"
        ),
        schema=schema,
    )
    op.add_column(
        "bootstrap_run",
        sa.Column("bind_ip", sa.Text(), nullable=False, server_default="0.0.0.0"),  # nosec B104 - matches the fixed pre-Phase-A constant
        schema=schema,
    )


def downgrade() -> None:
    schema = om_schema(sep_settings.DATABASE)
    op.drop_column("bootstrap_run", "bind_ip", schema=schema)
    op.drop_column("bootstrap_run", "port", schema=schema)
    op.drop_column("bootstrap_run", "log_path", schema=schema)
    op.drop_column("bootstrap_run", "data_path", schema=schema)
