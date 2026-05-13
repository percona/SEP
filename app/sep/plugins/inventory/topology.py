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

from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from functools import lru_cache
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

logger = logging.getLogger(__name__)

NODE_TYPE_MYSQL = "mysql"
NODE_TYPE_CLUSTER = "cluster"
NODE_TYPE_UNKNOWN = "unknown_source"

EDGE_TYPE_REPLICATION = "replication"
EDGE_TYPE_DUAL_PRIMARY = "dual_primary"

TOPOLOGY_JOB_PREFIX = "inventory-topology"
TOPOLOGY_PAYLOAD_REQUIREMENTS = "PyMySQL[rsa,ed25519]\nmyloginpath"


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


def merge_host_records(
    *event_streams: Iterable[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Merge ``host_done`` and ``host_error`` events from N shards into one map.

    Last-write-wins on duplicate ``host`` keys; ``host_error`` always replaces
    a prior ``host_done`` so a later shard's failure is visible.
    """
    by_host: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    for stream in event_streams:
        for ev in stream:
            kind = ev.get("event")
            host = ev.get("host")
            if not host:
                continue
            if kind == "host_done":
                by_host[host] = ev.get("data") or {}
                errors.pop(host, None)
            elif kind == "host_error":
                errors[host] = str(ev.get("error", "unknown error"))
                by_host.pop(host, None)
    out: dict[str, dict[str, Any]] = {}
    for host, data in by_host.items():
        out[host] = {"status": "ok", "data": data}
    for host, err in errors.items():
        out[host] = {"status": "error", "error": err}
    return out


def _server_node_id(host_entry: str) -> str:
    return f"mysql:{host_entry}"


def _cluster_node_id(cluster_name: str) -> str:
    return f"cluster:{cluster_name}"


def _unknown_node_id(host: str | None, port: int | None) -> str:
    return f"unknown:{host or '?'}:{port or 0}"


def _build_repl_edge_id(source_id: str, target_id: str) -> str:
    return f"repl:{source_id}->{target_id}"


def _build_dual_edge_id(a: str, b: str) -> str:
    lo, hi = sorted((a, b))
    return f"dual:{lo}<->{hi}"


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_topology_graph(  # noqa: C901, PLR0912, PLR0915 - graph assembly is naturally branchy
    host_records: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    """Build the React Flow ``{nodes, edges, summary}`` graph from per-host records.

    :param host_records: Output of :func:`merge_host_records` - ``{host_entry:
        {"status": "ok"|"error", "data"|"error": ...}}``.
    :return: Graph dict with ``nodes`` (mysql + cluster + unknown_source) and
        ``edges`` (replication + dual_primary). The shape matches what the
        ``InventoryTopology`` React component expects.
    """
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    cluster_members: dict[str, list[str]] = defaultdict(list)

    hash_to_node: dict[str, str] = {}
    addr_to_node: dict[tuple[str, int], str] = {}

    for host_entry, record in host_records.items():
        node_id = _server_node_id(host_entry)
        if record.get("status") != "ok":
            nodes.append(
                {
                    "id": node_id,
                    "type": NODE_TYPE_MYSQL,
                    "data": {
                        "host_entry": host_entry,
                        "error": record.get("error", "unknown error"),
                        "status": "error",
                    },
                }
            )
            continue
        data = record.get("data") or {}
        server = data.get("server") or {}
        repl = data.get("replication") or {}
        cluster = data.get("cluster") or {}
        gtid_mode = data.get("gtid_mode") or ""

        nodes.append(
            {
                "id": node_id,
                "type": NODE_TYPE_MYSQL,
                "data": {
                    "host_entry": host_entry,
                    "address": data.get("address"),
                    "port": data.get("port"),
                    "status": "ok",
                    "server": server,
                    "replication": {
                        k: v for k, v in repl.items() if k != "source_uuid"
                    },
                    "cluster": cluster or None,
                    "gtid_mode": gtid_mode,
                },
            }
        )
        if server_hash := server.get("server_hash"):
            hash_to_node[server_hash] = node_id
        port = _coerce_int(data.get("port"))
        if port is not None and (addr := data.get("address")):
            addr_to_node[(addr, port)] = node_id
        if cluster and cluster.get("cluster_name"):
            cluster_members[cluster["cluster_name"]].append(node_id)

    for cluster_name, members in cluster_members.items():
        cluster_id = _cluster_node_id(cluster_name)
        first_data = next(
            (
                node["data"]["cluster"]
                for node in nodes
                if node["id"] in members and (node.get("data") or {}).get("cluster")
            ),
            {},
        )
        nodes.append(
            {
                "id": cluster_id,
                "type": NODE_TYPE_CLUSTER,
                "data": {
                    "cluster_name": cluster_name,
                    "size": first_data.get("cluster_size"),
                    "status": first_data.get("cluster_status"),
                    "members": members,
                },
            }
        )

    primary_hashes_seen: dict[str, str] = {}
    for host_entry, record in host_records.items():
        if record.get("status") != "ok":
            continue
        data = record["data"] or {}
        repl = data.get("replication") or {}
        source_host = repl.get("source_host")
        if not source_host:
            continue
        source_node_id = _resolve_replication_source(
            repl, hash_to_node, addr_to_node, nodes
        )
        target_node_id = _server_node_id(host_entry)
        edges.append(
            {
                "id": _build_repl_edge_id(source_node_id, target_node_id),
                "source": source_node_id,
                "target": target_node_id,
                "type": EDGE_TYPE_REPLICATION,
                "data": {
                    "status": repl.get("repl_status"),
                    "io_running": repl.get("io_running"),
                    "sql_running": repl.get("sql_running"),
                    "seconds_behind": repl.get("seconds_behind"),
                    "auto_position": repl.get("auto_position"),
                    "filter": repl.get("repl_filter"),
                    "gtid_mode": data.get("gtid_mode"),
                },
            }
        )
        primary_hash = make_primary_hash(
            repl.get("source_server_id"),
            repl.get("source_uuid"),
            repl.get("source_port"),
        )
        primary_hashes_seen[target_node_id] = primary_hash

    server_hashes = {
        node["id"]: (node.get("data") or {}).get("server", {}).get("server_hash")
        for node in nodes
        if node["type"] == NODE_TYPE_MYSQL
        and node.get("data", {}).get("status") == "ok"
    }
    pair_seen: set[str] = set()
    for replica_id, primary_hash in primary_hashes_seen.items():
        primary_id = next(
            (nid for nid, h in server_hashes.items() if h == primary_hash and h),
            None,
        )
        if not primary_id or primary_id == replica_id:
            continue
        reverse_primary_hash = primary_hashes_seen.get(primary_id)
        if reverse_primary_hash is None:
            continue
        if reverse_primary_hash != server_hashes.get(replica_id):
            continue
        edge_id = _build_dual_edge_id(replica_id, primary_id)
        if edge_id in pair_seen:
            continue
        pair_seen.add(edge_id)
        edges.append(
            {
                "id": edge_id,
                "source": replica_id,
                "target": primary_id,
                "type": EDGE_TYPE_DUAL_PRIMARY,
                "data": {},
            }
        )

    summary = {
        "host_count": sum(1 for n in nodes if n["type"] == NODE_TYPE_MYSQL),
        "ok_count": sum(
            1
            for n in nodes
            if n["type"] == NODE_TYPE_MYSQL
            and (n.get("data") or {}).get("status") == "ok"
        ),
        "error_count": sum(
            1
            for n in nodes
            if n["type"] == NODE_TYPE_MYSQL
            and (n.get("data") or {}).get("status") == "error"
        ),
        "cluster_count": len(cluster_members),
        "edge_count": len(edges),
    }
    return {"nodes": nodes, "edges": edges, "summary": summary}


def _resolve_replication_source(
    repl: Mapping[str, Any],
    hash_to_node: Mapping[str, str],
    addr_to_node: Mapping[tuple[str, int], str],
    nodes: list[dict[str, Any]],
) -> str:
    """Find or synthesize the node id for a replica's replication source.

    Prefer hash-based matching (same identity even when the source IP
    differs), fall back to address+port, and synthesize an
    ``unknown_source`` node when neither matches so the graph still shows
    the dependency.
    """
    if (
        repl.get("source_server_id")
        and repl.get("source_uuid")
        and repl.get("source_port")
    ):
        candidate = make_primary_hash(
            repl["source_server_id"], repl["source_uuid"], repl["source_port"]
        )
        if node_id := hash_to_node.get(candidate):
            return node_id
    source_host = repl.get("source_host")
    source_port = _coerce_int(repl.get("source_port")) or 3306
    if source_host and (node_id := addr_to_node.get((source_host, source_port))):
        return node_id
    unknown_id = _unknown_node_id(source_host, source_port)
    if not any(n["id"] == unknown_id for n in nodes):
        nodes.append(
            {
                "id": unknown_id,
                "type": NODE_TYPE_UNKNOWN,
                "data": {
                    "address": source_host,
                    "port": source_port,
                    "reason": "Replication source not in inventory",
                },
            }
        )
    return unknown_id


@lru_cache(maxsize=64)
def _cached_graph(stdout_blobs: tuple[str, ...]) -> str:
    """Memoised graph build. Cache key is the raw stdout per shard."""
    streams = [parse_ndjson(blob) for blob in stdout_blobs]
    merged = merge_host_records(*streams)
    return json.dumps(build_topology_graph(merged), separators=(",", ":"))


def build_graph_from_stdouts(stdout_blobs: list[str]) -> dict[str, Any]:
    """Public entry point with stable cache semantics on the raw stdout tuple."""
    return json.loads(_cached_graph(tuple(stdout_blobs)))


def build_topology_meta(
    *, target: str, hosts: list[str], extra: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Assemble the ``meta`` dict for a topology ``run-python`` task dispatch."""
    config: dict[str, Any] = {"hosts": hosts}
    if extra:
        config.update(extra)
    return {
        "config": json.dumps(config, separators=(",", ":")),
        "target": target,
        "requirements": TOPOLOGY_PAYLOAD_REQUIREMENTS,
        "_job_id_prefix": TOPOLOGY_JOB_PREFIX,
    }


def shard_hosts(hosts: list[str], shards: int) -> list[list[str]]:
    """Split ``hosts`` into ``shards`` round-robin chunks (ordering preserved per shard)."""
    if shards <= 1 or len(hosts) <= 1:
        return [list(hosts)]
    shards = min(shards, len(hosts))
    out: list[list[str]] = [[] for _ in range(shards)]
    for index, host in enumerate(hosts):
        out[index % shards].append(host)
    return [chunk for chunk in out if chunk]
