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


@dataclass(frozen=True, slots=True)
class ExecutorState:
    """Carry why an executor host can or cannot run anything.

    :param name: The host's name as the executor backend knows it.
    :param address: Its network address.
    :param reachable: Whether the backend currently has contact with it.
    :param driver_healthy: Whether it can run this executor's job type.
    :param detail: The backend's reason, when it gives one.
    """

    name: str
    address: str
    reachable: bool
    driver_healthy: bool
    detail: str | None = None

    @property
    def usable(self) -> bool:
        """Return whether a probe can be dispatched here.

        :return: ``True`` when the host is both reachable and driver-healthy.
        """
        return self.reachable and self.driver_healthy


async def get_executor_states(tasks_api: RemoteAPI) -> dict[str, ExecutorState]:
    """Return every executor host the backend knows about, usable or not.

    ``GET /hosts/`` would be the smaller call, but it answers only "where can a job
    be placed": a host that is down, or up with an unhealthy driver, or never
    registered are all equally *absent* from it. POM has to describe hosts it cannot
    probe, so an absence it cannot explain is the one answer it must not give.

    Duplicate registrations of one name collapse, which is what makes name matching
    safe. On a backend that predates ``/hosts/states/`` this raises rather than
    silently degrading - a POM that quietly reported every host as fine would be
    worse than one that failed the sweep.

    :param tasks_api: The tasks API client.
    :return: The executor hosts keyed by name.
    """
    entries = await tasks_api.get("/hosts/states/")
    states: dict[str, ExecutorState] = {}
    for entry in entries:
        state = ExecutorState(
            name=entry["name"],
            address=entry["address"],
            reachable=entry["reachable"],
            driver_healthy=entry["driver_healthy"],
            detail=entry.get("detail"),
        )
        # One name, several registrations: restarting a host's agent leaves the old
        # registration behind as ``down`` beside the new one, so a plain dict
        # comprehension would keep whichever came last and call a running machine
        # unreachable. Measured in this workspace's sandbox -- ``pmm-client-node00``
        # was registered once ready and twice down, and the sweep refused to dispatch
        # to a host that was up. ``get_hosts`` never had to care, because everything
        # in it was usable by construction.
        existing = states.get(entry["name"])
        if existing is None or (state.usable and not existing.usable):
            states[entry["name"]] = state
    usable = sum(1 for state in states.values() if state.usable)
    logger.info(
        "POM discovery: %d executor host(s) known, %d usable",
        len(states),
        usable,
    )
    return states


def usable_executor_hosts(states: dict[str, ExecutorState]) -> dict[str, str]:
    """Narrow the states to the ``{name: address}`` mapping dispatch works from.

    :param states: Every known executor host.
    :return: Only the ones a job can be placed on.
    """
    return {name: state.address for name, state in states.items() if state.usable}


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
