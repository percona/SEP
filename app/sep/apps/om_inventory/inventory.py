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

"""List the MongoDB services the worker diagnoses, from SEP's inventory."""

import logging
from dataclasses import dataclass

from app.core.pagination import fetch_all_dict_items
from app.core.requests import RemoteAPI
from app.inventory.models import ServiceTypeEnum

logger = logging.getLogger(__name__)

#: MongoDB's port when a service carries none in inventory.
DEFAULT_MONGODB_PORT = 27017


@dataclass(frozen=True, slots=True)
class InventoryService:
    """Carry one MongoDB service as inventory reports it.

    ``cluster`` and ``replication_set`` come straight from inventory and are recorded
    rather than interpreted here. Note that one ``cluster`` value can span two
    generations of members with different replica sets, so downstream topology work
    must group on ``replication_set``.

    :param service_id: The inventory service id.
    :param external_id: **PMM's** service UUID, which inventory stores as
        ``external_id``. This is the join key against VictoriaMetrics, whose
        ``service_id`` label carries the same UUID -- and it is the *only* safe one:
        ``service_name`` is reused across re-registrations while the superseded series
        live on until retention expires, so a name-keyed join silently mixes
        generations. ``None`` when inventory carries none, which makes the service
        invisible to the metrics source.
    :param name: The inventory service name.
    :param port: The service port, defaulted when inventory carries none.
    :param cluster: The service's cluster attribute, if any.
    :param replication_set: The service's replica set; empty for a mongos.
    :param environment: The service's environment label, set once at registration.
    :param node_name: The node's registered name, if any.
    :param node_address: The node's registered address, if any.
    """

    service_id: int | None
    external_id: str | None
    name: str
    port: int
    cluster: str | None
    replication_set: str | None
    environment: str | None
    node_name: str | None
    node_address: str | None


def _service_from_entry(entry: dict) -> InventoryService | None:
    """Build a service record from one raw ``GET /services/`` listing entry.

    An entry whose node carries neither a name nor an address is skipped: there is
    nothing to match an executor host against, and nothing to connect to.

    :param entry: One entry from the inventory services listing.
    :return: The service, or ``None`` when it carries no usable node identity.
    """
    node = entry.get("node") or {}
    node_name = node.get("name")
    node_address = node.get("address")
    if not node_name and not node_address:
        logger.warning(
            "Skipping MongoDB service %r: inventory entry carries no node name "
            "or address",
            entry.get("name"),
        )
        return None
    return InventoryService(
        service_id=entry.get("id"),
        external_id=entry.get("external_id") or None,
        name=entry.get("name") or node_name or node_address or "",
        port=entry.get("port") or DEFAULT_MONGODB_PORT,
        cluster=entry.get("cluster") or None,
        replication_set=entry.get("replication_set") or None,
        environment=entry.get("environment") or None,
        node_name=node_name,
        node_address=node_address,
    )


async def list_mongodb_services(inventory_api: RemoteAPI) -> list[InventoryService]:
    """Return every MongoDB service in inventory, in inventory order.

    :param inventory_api: The inventory API client.
    :return: The MongoDB services carrying a usable node identity.
    """
    listed = await fetch_all_dict_items(
        lambda pagination: inventory_api.get(
            "/services/",
            params={
                "service_type": ServiceTypeEnum.MONGODB.value,
                **pagination.model_dump(),
            },
        )
    )
    services = [
        service
        for entry in listed
        if (service := _service_from_entry(entry)) is not None
    ]
    logger.info(
        "OM inventory: inventory lists %d MongoDB service(s), %d usable",
        len(listed),
        len(services),
    )
    return services
