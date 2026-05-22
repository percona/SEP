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

"""Shared constants for SEP proxy API routes."""

UPSTREAM_ERROR_HEADER = "X-Sep-Upstream-Error"
"""Response header carrying the upstream-failure detail string.

SEP proxy routes (``/api/sep/...``) degrade gracefully when an upstream
service (Tasks API, Inventory API) fails: the route returns a default-shaped
empty payload with a ``200`` status so the React frontend can render its
empty state, and attaches the upstream failure detail in this header so the
shell can surface a non-blocking notification.
"""
