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

"""Name the task-envelope ``meta`` keys shared by their producers and consumers.

A key here is a serialization contract that outlives the request writing it: it
is stamped into ``Task.data["meta"]`` at creation and read back later, sometimes
from another service. Producers and consumers therefore cannot rename one
independently, and a rename on only one side fails silently — the reader simply
finds nothing. Naming the key once removes that possibility.

Deliberately import-free, and a sibling of the app packages rather than a member
of one, so a producer and a consumer sitting in different packages can name a key
from one place without either importing the other.
"""

#: Inventory id of the service a task was created against. Absent when the
#: resolved service carried no primary key.
SERVICE_ID_META_KEY = "_service_id"
