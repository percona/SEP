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

"""Map MongoDB services to the executor host their probe must run on.

This is the question the worker exists to answer: given ``rsc-node02``, which host does
a script run on to reach that mongod?

The matching order mirrors
:meth:`~app.sep.sync.models.BaseTaskSyncer.get_task_target` -- node name first, then
node address -- against the executor list the Tasks API serves from
:meth:`~app.tasks.execution.executors.nomad.models.NomadExecutor.get_hosts`, which
already filters server-side to ready clients with a healthy ``raw_exec`` driver.

**What this module deliberately does not copy** is that method's fallback. With
``strict_executor_matching`` off, an unmatched node resolves to
``next(iter(available_hosts))`` -- an arbitrary unrelated host -- and the probe runs
there and reports facts about a mongod that is not on that box. Here an unmatched
service is :attr:`~app.sep.apps.pom_discovery.models.NodeResolution.ORPHANED` and is not
probed at all.

That case is the norm, not an edge: an inventory row routinely outlives the executor
that served it.
"""

import logging
from dataclasses import dataclass

from app.core.requests import RemoteAPI
from app.sep.apps.pom_discovery.inventory import InventoryService
from app.sep.apps.pom_discovery.models import NodeResolution

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MappedService:
    """Pair one inventory service with the executor host resolved for it.

    :param service: The inventory service.
    :param executor_host: The Nomad executor host to run its probe on; ``None`` when
        the service is orphaned.
    :param resolution: How the host was matched, or that it was not.
    """

    service: InventoryService
    executor_host: str | None
    resolution: NodeResolution

    @property
    def is_resolved(self) -> bool:
        """Return whether this service has an executor host to probe on.

        :return: ``True`` when an executor host was matched.
        """
        return self.executor_host is not None


async def get_executor_hosts(tasks_api: RemoteAPI) -> dict[str, str]:
    """Return the executor hosts available to SEP, as ``{name: address}``.

    The Tasks API applies the readiness and ``raw_exec``-health filter upstream, so
    down or driver-unhealthy Nomad clients never appear here. Duplicate registrations
    of one name collapse, which is what makes name matching safe.

    :param tasks_api: The tasks API client.
    :return: The available executor hosts keyed by name.
    """
    hosts = await tasks_api.get("/hosts/")
    logger.info("POM discovery: %d executor host(s) available", len(hosts))
    return hosts


def map_service(
    service: InventoryService, executor_hosts: dict[str, str]
) -> MappedService:
    """Resolve one service to an executor host, or mark it orphaned.

    :param service: The inventory service to map.
    :param executor_hosts: The available executor hosts, ``{name: address}``.
    :return: The mapping outcome for this service.
    """
    if service.node_name and service.node_name in executor_hosts:
        return MappedService(service, service.node_name, NodeResolution.NAME)

    if service.node_address:
        for host, address in executor_hosts.items():
            if address == service.node_address:
                return MappedService(service, host, NodeResolution.ADDRESS)

    # Deliberately not falling back to an arbitrary host -- see the module docstring.
    logger.info(
        "POM discovery: service %r is orphaned (node name=%r address=%r matches no "
        "executor host); it will not be probed",
        service.name,
        service.node_name,
        service.node_address,
    )
    return MappedService(service, None, NodeResolution.ORPHANED)


def map_services(
    services: list[InventoryService], executor_hosts: dict[str, str]
) -> list[MappedService]:
    """Resolve every service to an executor host, preserving inventory order.

    :param services: The MongoDB services from inventory.
    :param executor_hosts: The available executor hosts, ``{name: address}``.
    :return: One mapping per service, resolved or orphaned.
    """
    mapped = [map_service(service, executor_hosts) for service in services]
    resolved = sum(1 for entry in mapped if entry.is_resolved)
    logger.info(
        "POM discovery: mapped %d service(s) -> %d resolved, %d orphaned",
        len(mapped),
        resolved,
        len(mapped) - resolved,
    )
    return mapped
