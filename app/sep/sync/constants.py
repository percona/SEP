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

"""Define constants shared across the SEP sync package.

A leaf module: importing it pulls in nothing beyond the entity-type enum, so a
collaborator can address an inventory entity generically without reaching back
into the syncer framework that also needs the same map.
"""

from typing import Final

from app.sep.models import SyncInventoryEntityTypeEnum

#: Inventory API path segment per entity type, for the routes that address one
#: entity generically rather than through a per-level method.
INVENTORY_PATH_SEGMENTS: Final = {
    SyncInventoryEntityTypeEnum.NODE: "nodes",
    SyncInventoryEntityTypeEnum.SERVICE: "services",
    SyncInventoryEntityTypeEnum.SCHEMA: "schemas",
    SyncInventoryEntityTypeEnum.TABLE: "tables",
}
