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

"""merge heads

Revision ID: 410eedfc5b43
Revises: b8d5f2a9c1e4, 378c0872642f
Create Date: 2026-06-22 12:23:53.239429

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = '410eedfc5b43'
down_revision: Union[str, None] = ('b8d5f2a9c1e4', '378c0872642f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge the two sep_main heads into one. No-op; no schema change."""


def downgrade() -> None:
    """Unmerge the heads. No-op; a head merge has nothing to undo."""
