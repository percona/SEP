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

"""Hold what every OM app shares, and nothing that belongs to one of them.

OM is a namespace rather than a single app: discovery is the first, and restart,
configuration change, upgrade and installation are meant to follow, all keeping their
tables in one ``om`` schema. The schema is therefore owned here rather than by
whichever app happened to be written first -- an app that later ships without the
others must not take the schema definition with it.

Deliberately empty of imports. Anything placed here is loaded by every OM app.
"""
