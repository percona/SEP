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

"""add bootstrap_run.cancel_requested

Revision ID: 9b1f4a6e5c3d
Revises: 2773844e362d
Create Date: 2026-09-09 11:00:00.000000

Hand-written, matching this table's own prior migrations' note on why:
autogenerate proposes a wrong diff against it.

Whether an operator has asked the run to stop. Defaults to `false`: no
cancellation requested.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.sep.apps.shared.om.config import om_schema
from app.sep.config import sep_settings


# revision identifiers, used by Alembic.
revision: str = "9b1f4a6e5c3d"
down_revision: Union[str, None] = "2773844e362d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    schema = om_schema(sep_settings.DATABASE)
    op.add_column(
        "bootstrap_run",
        sa.Column(
            "cancel_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        schema=schema,
    )


def downgrade() -> None:
    schema = om_schema(sep_settings.DATABASE)
    op.drop_column("bootstrap_run", "cancel_requested", schema=schema)
