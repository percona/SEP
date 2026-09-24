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

"""add bootstrap_run.member_configs

Revision ID: 4d7a2e9c1b6f
Revises: 9b1f4a6e5c3d
Create Date: 2026-09-09 12:00:00.000000

Hand-written, matching this table's own prior migrations' note on why:
autogenerate proposes a wrong diff against it.

Per-member replica-set election settings (priority/votes/hidden/delay), keyed
by host. Defaults to `{}`: no per-host overrides, so every host gets
MemberConfig's own defaults.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.extensions.apps.shared.om.config import om_schema
from app.extensions.config import extensions_settings as sep_settings


# revision identifiers, used by Alembic.
revision: str = "4d7a2e9c1b6f"
down_revision: Union[str, None] = "9b1f4a6e5c3d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    schema = om_schema(sep_settings.DATABASE)
    op.add_column(
        "bootstrap_run",
        sa.Column(
            "member_configs",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
            server_default="{}",
        ),
        schema=schema,
    )


def downgrade() -> None:
    schema = om_schema(sep_settings.DATABASE)
    op.drop_column("bootstrap_run", "member_configs", schema=schema)
