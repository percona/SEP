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

Revision ID: fa5b80a1c8e0
Revises: 2f5a00236369, abc65df0318a, c4e8f0a3b1d2
Create Date: 2026-06-30 18:38:54.941378

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = 'fa5b80a1c8e0'
down_revision: Union[str, None] = ('2f5a00236369', 'abc65df0318a', 'c4e8f0a3b1d2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
