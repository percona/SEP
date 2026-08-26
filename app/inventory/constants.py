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

#: Discriminator carried by a service with no external identity, confining the port
#: uniqueness index to the rows it actually protects. It is NULL on an externally
#: identified row for two reasons at once: a unique index treats NULLs as distinct
#: on every supported dialect, and the ``all(equal_filters.values())`` guard in
#: ``BaseSQLModelManager.save`` skips an index carrying a falsy value. It has to be
#: truthy here for the same reason :data:`ACTIVE_RETIREMENT_KEY` does.
UNIDENTIFIED_PORT_GUARD_KEY: Final = -1

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
