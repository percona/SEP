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

"""Build the React-Flow topology graph from per-host MySQL collector results.

The collector payload (``payloads/topology.py``) emits one NDJSON event per
MySQL host. This module:

* parses those events into per-host records,
* builds the graph (nodes + edges) consumed by the React Flow front end,
* derives PXC cluster groups and unknown-source nodes for replication
  sources we never queried.

Pure functions only; the dispatch/SSE layer lives in ``api_routes.py``.
"""

import hashlib
import json
import logging
logger = logging.getLogger(__name__)



def make_primary_hash(server_id: Any, server_uuid: Any, port: Any) -> str:
    """Deterministic hash that lets a replica match a primary's identity.

    Mirrors ``GAS/tools/bin/db_tree.py::make_primary_hash`` so existing
    operator intuition transfers (replica's source_server_id+uuid+port hash
    must equal its primary's @@server_hash).
    """
    raw = f"{server_id or ''}{server_uuid or ''}{port or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_ndjson(stdout: str) -> list[dict[str, Any]]:
    """Parse the NDJSON stdout from one topology collector task.

    Skips blank lines and silently drops malformed JSON (logged at debug).
    """
    events: list[dict[str, Any]] = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            logger.debug("Skipping non-JSON topology line: %s", line[:200])
    return events


def _server_node_id(host_entry: str) -> str:
    return f"mysql:{host_entry}"


def _cluster_node_id(cluster_name: str) -> str:
    return f"cluster:{cluster_name}"


def _unknown_node_id(host: str | None, port: int | None) -> str:
    return f"unknown:{host or '?'}:{port or 0}"


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


