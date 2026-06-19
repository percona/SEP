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

"""Define dependency-neutral constants shared by the task log scanners.

This module imports nothing from the rest of the tasks package so it can be
imported from ``crud`` and ``logs.log_reader`` without creating an import cycle
(``log_reader`` already imports ``crud``). It is the single source of truth for
the tail-scan bound.
"""

#: Hard cap on chunks scanned for a tail read. Bounds a pathological
#: marker-free STDERR stream.
TAIL_SCAN_MAX_CHUNKS = 512
