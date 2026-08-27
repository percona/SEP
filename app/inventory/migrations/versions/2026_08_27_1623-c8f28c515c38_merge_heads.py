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

Revision ID: c8f28c515c38
Revises: e4b8c2f7a915, 91c704d3a08a
Create Date: 2026-08-27 16:23:28.780474

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = 'c8f28c515c38'
down_revision: Union[str, None] = ('e4b8c2f7a915', '91c704d3a08a')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
