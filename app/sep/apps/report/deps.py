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

"""Define dependencies for the report plugin."""

# ``get_pmm_api`` / ``PMMAPIDep`` / ``require_pmm_api`` / ``RequiredPMMAPIDep`` live
# in ``app.sep.deps`` alongside the sibling Inventory / Tasks client deps; they are
# re-exported here for existing importers (api_routes, tests).
from app.sep.deps import (
    get_pmm_api,  # noqa: F401 -- re-exported for existing importers
    PMMAPIDep,  # noqa: F401 -- re-exported for existing importers
    require_pmm_api,  # noqa: F401 -- re-exported for existing importers
    RequiredPMMAPIDep,  # noqa: F401 -- re-exported for existing importers
)
