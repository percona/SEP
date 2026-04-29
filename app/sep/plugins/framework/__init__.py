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

"""Provide shared building blocks for schema-driven plugins."""

from app.sep.plugins.framework.connectivity import (
    ConnectivityWarning,
    maybe_record_connectivity_warning,
    record_connectivity_warning,
)

__all__ = [
    "ConnectivityWarning",
    "maybe_record_connectivity_warning",
    "record_connectivity_warning",
]
