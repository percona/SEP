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

"""Define constants for the Inventory service."""

from enum import StrEnum
from typing import Final

DEFAULT_MYSQL_PORT = 3306
DEFAULT_POSTGRESQL_PORT = 5432

#: Discriminator carried by an active row inside every unique index, so a retired
#: row (which carries its own primary key instead) never collides with its
#: replacement. It has to be truthy and outside the autoincrement range:
#: ``BaseSQLModelManager.save`` guards its Python duplicate check with
#: ``all(equal_filters.values())``, which a ``0`` or ``NULL`` sentinel would
#: silently disable.
ACTIVE_RETIREMENT_KEY: Final = -1

#: Part of the API contract: callers tell an uncollected observation apart from a
#: missing parent by this wording, so both routes and their tests share it.
UNCOLLECTED_HOST_OBSERVATION_DETAIL = (
    "System observation not collected yet for this node"
)
#: Service-level counterpart of :data:`UNCOLLECTED_HOST_OBSERVATION_DETAIL`, pinned
#: by the same contract.
UNCOLLECTED_SERVICE_OBSERVATION_DETAIL = (
    "System observation not collected yet for this service"
)


class RetirableEntityName(StrEnum):
    """Name the inventory entity types that carry a retirement tombstone.

    Values are spelled out rather than derived, because they cross a service
    boundary: SEP names an entity type by these strings when it asks inventory
    to collect. Inventory-local on purpose — SEP's own
    ``SyncInventoryEntityTypeEnum`` lives in a package this service must not
    import.
    """

    NODE = "node"
    SERVICE = "service"
    SCHEMA = "schema"
    TABLE = "table"


#: The entity types that carry an external identity and can therefore be linked
#: across a re-registration. Schemas and tables are keyed by name within their
#: parent and sourced by the MySQL syncer, so no upstream identity changes under
#: them.
ALIASABLE_ENTITY_NAMES: Final = frozenset(
    {RetirableEntityName.NODE, RetirableEntityName.SERVICE}
)
