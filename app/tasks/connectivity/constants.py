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

#: Budget (seconds) for the DB connect, counted only after the payload emits
#: :data:`CONNECT_PHASE_MARKER`. Kept strictly greater than the inner DB
#: ``connect_timeout`` (``app/tasks/connectivity/payload.py``) so the inner
#: connect can complete inside the outer window.
CONNECTIVITY_CHECK_TIMEOUT = 30

#: Budget (seconds) for the provisioning phase (Nomad dispatch + ``run-python``
#: scheduling + dependency install), counted from dispatch until the payload
#: emits :data:`CONNECT_PHASE_MARKER`. Decoupled from the connect budget so
#: provisioning latency cannot false-negative a reachable DB, while still
#: bounding a task whose payload never reaches the connect phase.
PROVISIONING_TIMEOUT = 60

#: Sentinel the payload flushes to ``run-script`` **stderr** right before the DB
#: connect, marking the boundary between the provisioning phase (charged to
#: :data:`PROVISIONING_TIMEOUT`) and the connect phase (charged to
#: :data:`CONNECTIVITY_CHECK_TIMEOUT`); ``status`` cannot mark it because Nomad
#: reports ``RUNNING`` from dispatch onward. Duplicated in
#: ``app/tasks/connectivity/payload.py`` (runs standalone, cannot import this
#: package); a test asserts the two stay in sync.
CONNECT_PHASE_MARKER = "__SEP_CONNECTIVITY_CONNECT_START__"
