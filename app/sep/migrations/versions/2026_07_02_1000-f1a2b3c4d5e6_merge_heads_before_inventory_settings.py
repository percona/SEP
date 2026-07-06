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

"""merge dangling sep_main heads before wiring INVENTORY_SETTINGS

The ``sep_main`` branch had two divergent heads that both descend from the
``ed97b99eef38`` (add setting_override table) branchpoint:

* ``410eedfc5b43`` -- the appstate / apprunningtask / lifecycle lineage.
* ``a1f4c7e9b2d3`` -- the setting_class enum-extension lineage (SETTINGS,
  ALERT_SETTINGS, ANONYMIZER_SETTINGS, ALERTS_SETTINGS).

``upgrade heads`` applies both, but ``upgrade head`` (singular) and any single
``down_revision`` are ambiguous while two heads exist. This no-op merge unifies
them so the follow-up ``INVENTORY_SETTINGS`` extension has one parent.

Revision ID: f1a2b3c4d5e6
Revises: 410eedfc5b43, a1f4c7e9b2d3
Create Date: 2026-07-02 10:00:00.000000

"""

# revision identifiers, used by Alembic.
revision = "f1a2b3c4d5e6"
down_revision = ("410eedfc5b43", "a1f4c7e9b2d3")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Merge the two ``sep_main`` heads (no schema change)."""


def downgrade() -> None:
    """Split back into the two pre-merge ``sep_main`` heads (no schema change)."""
