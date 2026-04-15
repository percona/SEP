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

"""Add CELERY value to TaskBackendEnum.

Revision ID: bb3edb973603
Revises: add_filelock_to_backups
Create Date: 2026-03-04 21:49:12.341657

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "bb3edb973603"
down_revision: Union[str, None] = "add_filelock_to_backups"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("task") as batch_op:
        batch_op.alter_column(
            "backend",
            existing_type=sa.VARCHAR(length=5),
            type_=sa.Enum(
                "NOMAD",
                "PROXY",
                "CELERY",
                name="taskbackendenum",
                native_enum=False,
            ),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("task") as batch_op:
        batch_op.alter_column(
            "backend",
            existing_type=sa.Enum(
                "NOMAD",
                "PROXY",
                "CELERY",
                name="taskbackendenum",
                native_enum=False,
            ),
            type_=sa.VARCHAR(length=32),
            existing_nullable=False,
        )
