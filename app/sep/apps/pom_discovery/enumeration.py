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

"""List the hosts in scope, from the two sources that already know about them.

Enumerating from *services* -- which is what the app did before this module -- can
only ever produce hosts that run a database, and the case worth catching is the one
where none does. So hosts come from SEP's inventory nodes, filled by ``PMMSyncer``
independently of services, crossed with the Nomad executor list.

Crossing the two gives four states:

===================  =========================  ==========================
Node                 Has executor               No executor
===================  =========================  ==========================
Has MongoDB service  normal: probeable          monitored, not actionable
No MongoDB service   **nothing installed yet**  monitored only
===================  =========================  ==========================

The bottom-left cell is the valuable one, not something to filter out: a reachable
host with no database is where a database can be installed. What *is* filtered out is
the bottom-right -- a node with neither a MongoDB service nor an executor is some
other machine PMM happens to monitor, and PMM's own server node is one of them.

Matching a node to its executor host reuses the order
:mod:`~app.sep.apps.pom_discovery.mapping` uses per service -- name first, then
address -- at the host level, where it belongs: every service on a host resolves to
the same executor, so asking once per host is both cheaper and impossible to answer
inconsistently.
"""

import logging
from dataclasses import dataclass

from app.core.pagination import fetch_all_dict_items
from app.core.requests import RemoteAPI
from app.sep.apps.pom_discovery.inventory import InventoryService
from app.sep.apps.pom_discovery.models import NodeResolution

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class InventoryHost:
    """Carry one host as the two sources jointly describe it.

    :param node_id: **PMM's** node id, which SEP's inventory stores as
        ``external_id``. The primary key of ``pom.pom_host``, the id PMM's trigger
        passes, and the only identifier that means anything on the other side.
    :param name: The node's registered name.
    :param address: The node's registered address, if any.
    :param executor_host: The Nomad client serving it, or ``None``.
    :param resolution: How the executor was matched, or that it was not.
    """

    node_id: str
    name: str
    address: str | None
    executor_host: str | None
    resolution: NodeResolution

    @property
    def has_executor(self) -> bool:
        """Return whether a payload can run on this host.

        :return: ``True`` when an executor host was matched.
        """
        return self.executor_host is not None


def _match_executor(
    name: str | None, address: str | None, executor_hosts: dict[str, str]
) -> tuple[str | None, NodeResolution]:
    """Resolve one host to an executor, by name then by address.

    Deliberately without the fallback ``BaseTaskSyncer.get_task_target`` has: with
    ``strict_executor_matching`` off it resolves an unmatched node to an arbitrary
    other host, which here would mean probing one machine and recording the answers
    against another.

    :param name: The node's registered name.
    :param address: The node's registered address.
    :param executor_hosts: The available executor hosts, ``{name: address}``.
    :return: The executor host and how it was matched.
    """
    if name and name in executor_hosts:
        return name, NodeResolution.NAME
    if address:
        for host, host_address in executor_hosts.items():
            if host_address == address:
                return host, NodeResolution.ADDRESS
    return None, NodeResolution.ORPHANED


async def list_inventory_nodes(inventory_api: RemoteAPI) -> list[dict]:
    """Return every node SEP's inventory holds.

    :param inventory_api: The inventory API client.
    :return: The raw node entries.
    """
    return await fetch_all_dict_items(
        lambda pagination: inventory_api.get("/nodes/", params=pagination.model_dump())
    )


def build_hosts(
    nodes: list[dict],
    services: list[InventoryService],
    executor_hosts: dict[str, str],
) -> list[InventoryHost]:
    """Cross the sources into the hosts POM keeps rows for.

    A node with no ``external_id`` is skipped: PMM's node id is the key, and a row
    that cannot be keyed cannot be joined, triggered or updated. It is logged rather
    than silently dropped, because the cause is an inventory sync that has not caught
    up rather than anything about the host.

    :param nodes: Raw node entries from SEP's inventory.
    :param services: The MongoDB services, used only to decide scope.
    :param executor_hosts: The available executor hosts, ``{name: address}``.
    :return: The hosts in scope, in inventory order.
    """
    # Scope by *name and address* rather than by node id: a service entry carries its
    # node's name and address, not PMM's node id for it.
    with_service = {service.node_name for service in services if service.node_name}
    with_service |= {
        service.node_address for service in services if service.node_address
    }

    hosts: list[InventoryHost] = []
    skipped = 0
    for entry in nodes:
        name = entry.get("name") or ""
        address = entry.get("address") or None
        executor_host, resolution = _match_executor(name, address, executor_hosts)

        if (
            executor_host is None
            and name not in with_service
            and address not in with_service
        ):
            # Neither a database nor a place to run anything: some other machine PMM
            # monitors. Keeping it would put PMM's own server node in the estate.
            continue

        node_id = entry.get("external_id") or None
        if not node_id:
            logger.warning(
                "POM discovery: skipping node %r -- inventory holds no external_id "
                "for it, so there is no PMM node id to key a row on",
                name,
            )
            skipped += 1
            continue

        hosts.append(
            InventoryHost(
                node_id=node_id,
                name=name,
                address=address,
                executor_host=executor_host,
                resolution=resolution,
            )
        )

    with_executor = sum(1 for host in hosts if host.has_executor)
    logger.info(
        "POM discovery: %d node(s) in inventory -> %d host(s) in scope "
        "(%d with an executor, %d without), %d unkeyable",
        len(nodes),
        len(hosts),
        with_executor,
        len(hosts) - with_executor,
        skipped,
    )
    return hosts
