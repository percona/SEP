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

"""merge tasks migration heads

Revision ID: 8657d05d27da
Revises: b2e5d8f0c3a4, b7e1c0a4d9f2, 60bf743eb469
Create Date: 2026-07-01 18:48:25.484638

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = '8657d05d27da'
down_revision: Union[str, Sequence[str], None] = (
    'b2e5d8f0c3a4',
    'b7e1c0a4d9f2',
    '60bf743eb469',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge the three tasks heads into one. No-op; no schema change."""


def downgrade() -> None:
    """Unmerge the heads. No-op; a head merge has nothing to undo."""
