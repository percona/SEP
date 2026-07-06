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

"""Shared UI label constants for schema-driven plugins.

Lives alongside (not inside) :mod:`app.sep.apps.framework` so Alembic env
modules and legacy Jinja form builders can reference labels without
importing ``framework.__init__`` and unrelated SQLModel tables into
metadata.
"""

#: Canonical UI label for the host where task commands execute.
EXECUTION_HOST_LABEL = "Execution Host"
