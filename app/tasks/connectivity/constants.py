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

#: Budget (seconds) for the DB connect, counted only once the ``run-script``
#: Nomad task has started (see :func:`app.tasks.connectivity.service`). Kept
#: strictly greater than the inner DB ``connect_timeout``
#: (``app/tasks/connectivity/payload.py``) so the inner connect can complete
#: inside the outer window.
CONNECTIVITY_CHECK_TIMEOUT = 20

#: Budget (seconds) for the provisioning phase (Nomad dispatch + ``run-python``
#: scheduling + ``prepare-env`` dependency install), counted from dispatch until
#: the ``run-script`` task reports ``StartedAt``. Decoupled from the connect
#: budget so provisioning latency cannot false-negative a reachable DB, while
#: still bounding a task whose ``run-script`` step never starts.
PROVISIONING_TIMEOUT = 45
