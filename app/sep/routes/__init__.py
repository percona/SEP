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

from types import MappingProxyType

STREAMING_PROXY_HEADERS = MappingProxyType({"X-Accel-Buffering": "no"})
"""Headers that stop an intermediary proxy buffering an incremental response.

Frozen because the streaming routes hold it directly rather than copying, so an
in-place mutation at one call site would reach every later response.
"""
