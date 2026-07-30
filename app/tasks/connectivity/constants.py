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

"""Define constants for the Tasks connectivity check feature."""

CONNECTIVITY_META_HOST_KEY = "_connectivity_host"
CONNECTIVITY_META_PORT_KEY = "_connectivity_port"
CONNECTIVITY_META_SERVICE_TYPE_KEY = "_connectivity_service_type"

#: Post-start connect budget (seconds). Must stay strictly above the inner DB
#: ``CONNECT_TIMEOUT`` (``app/tasks/connectivity/payload.py``) so the inner
#: connect can finish inside this window. ``service.py`` measures the boundary.
CONNECTIVITY_CHECK_TIMEOUT = 20

#: Pre-start provisioning budget (seconds), bounding a task whose ``run-script``
#: step never starts.
PROVISIONING_TIMEOUT = 45
