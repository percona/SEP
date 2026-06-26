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

"""Inventory helpers for legacy ``data['_form']`` backfill service resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TYPE_CHECKING

from sqlmodel import col

from app.inventory.constants import DEFAULT_MYSQL_PORT, DEFAULT_POSTGRESQL_PORT
from app.inventory.crud import ServiceManager
from app.inventory.models import Service, ServiceTypeEnum
from app.sep.connectivity import (
    CONNECTIVITY_META_HOST_KEY,
    CONNECTIVITY_META_PORT_KEY,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "ServiceIdLookup",
    "default_port_for_service_type",
    "load_service_id_lookup",
    "meta_service_hints",
]

_IN_SCOPE_SERVICE_TYPES = frozenset(
    {ServiceTypeEnum.MYSQL, ServiceTypeEnum.POSTGRESQL},
)

_DEFAULT_PORTS = {
    ServiceTypeEnum.MYSQL: DEFAULT_MYSQL_PORT,
    ServiceTypeEnum.POSTGRESQL: DEFAULT_POSTGRESQL_PORT,
}

_ADDRESS_KEY = tuple[ServiceTypeEnum, str, int]
_NAME_KEY = tuple[ServiceTypeEnum, str]


class _InventoryService(Protocol):
    """Describe the inventory fields :class:`ServiceIdLookup` indexes."""

    id: int
    type: ServiceTypeEnum
    name: str
    port: int | None

    @property
    def node(self) -> Any:
        """Return the parent node carrying the service address."""


def default_port_for_service_type(service_type: ServiceTypeEnum) -> int:
    """Return the conventional default port for ``service_type``.

    :param service_type: The inventory service type to resolve a port for.
    :type service_type: ServiceTypeEnum
    :return: The default TCP port for the service type.
    :rtype: int
    :raises KeyError: When ``service_type`` has no configured default port.
    """
    return _DEFAULT_PORTS[service_type]


@dataclass(frozen=True)
class ServiceIdLookup:
    """Resolve inventory service ids by address or service name.

    Built once per backfill run from the inventory database so synchronous per-app
    reconstructors can map persisted task host/port metadata to ``service_id``
    without issuing per-task queries.

    :param by_address: Unique ``(type, host, port)`` keys mapped to service ids.
    :type by_address: dict[_ADDRESS_KEY, int]
    :param ambiguous_addresses: Keys with more than one matching inventory service.
    :type ambiguous_addresses: frozenset[_ADDRESS_KEY]
    :param by_name: Unique ``(type, name)`` keys mapped to service ids.
    :type by_name: dict[_NAME_KEY, int]
    :param ambiguous_names: Names that map to more than one inventory service.
    :type ambiguous_names: frozenset[_NAME_KEY]
    """

    by_address: dict[_ADDRESS_KEY, int]
    ambiguous_addresses: frozenset[_ADDRESS_KEY]
    by_name: dict[_NAME_KEY, int]
    ambiguous_names: frozenset[_NAME_KEY]

    @classmethod
    def from_services(cls, services: Iterable[_InventoryService]) -> ServiceIdLookup:
        """Build a lookup table from inventory :class:`~app.inventory.models.Service` rows.

        :param services: Inventory services whose ``node.address`` is populated.
        :type services: Iterable[_InventoryService]
        :return: The address/name lookup tables for the supplied services.
        :rtype: ServiceIdLookup
        """
        by_address: dict[_ADDRESS_KEY, int] = {}
        ambiguous_addresses: set[_ADDRESS_KEY] = set()
        by_name: dict[_NAME_KEY, int] = {}
        ambiguous_names: set[_NAME_KEY] = set()

        for service in services:
            if service.type not in _IN_SCOPE_SERVICE_TYPES:
                continue
            node = service.node
            if node is None or not getattr(node, "address", None):
                continue

            address = str(node.address).strip()
            if not address:
                continue

            port = (
                service.port
                if service.port is not None
                else default_port_for_service_type(service.type)
            )
            address_key = (service.type, address, port)
            cls._register(by_address, ambiguous_addresses, address_key, service.id)

            name = str(service.name).strip()
            if name:
                name_key = (service.type, name)
                cls._register(by_name, ambiguous_names, name_key, service.id)

        return cls(
            by_address=by_address,
            ambiguous_addresses=frozenset(ambiguous_addresses),
            by_name=by_name,
            ambiguous_names=frozenset(ambiguous_names),
        )

    @staticmethod
    def _register(
        unique: dict[Any, int],
        ambiguous: set[Any],
        key: Any,
        service_id: int,
    ) -> None:
        """Insert ``service_id`` under ``key``, marking duplicates as ambiguous.

        :param unique: The map receiving the first id seen for each key.
        :type unique: dict[Any, int]
        :param ambiguous: Keys that have already collided once.
        :type ambiguous: set[Any]
        :param key: The lookup key being registered.
        :type key: Any
        :param service_id: The inventory service id to register.
        :type service_id: int
        """
        if key in ambiguous:
            return
        existing = unique.get(key)
        if existing is None:
            unique[key] = service_id
            return
        if existing != service_id:
            ambiguous.add(key)
            unique.pop(key, None)

    def resolve(
        self,
        *,
        service_type: ServiceTypeEnum,
        host: str | None,
        port: int | None = None,
        service_name: str | None = None,
    ) -> int | None:
        """Return the inventory id for a host/port or name, or ``None`` when unsure.

        Address lookup runs first when ``host`` is present. When that misses, a
        case-sensitive name lookup is attempted when ``service_name`` is provided.
        Zero or ambiguous matches return ``None`` so the caller can skip stamping.

        :param service_type: The inventory service type to match.
        :type service_type: ServiceTypeEnum
        :param host: The database host address stored on the task.
        :type host: str | None
        :param port: The database port; defaults via :func:`default_port_for_service_type`.
        :type port: int | None
        :param service_name: Optional inventory service name fallback.
        :type service_name: str | None
        :return: The matching service id, or ``None`` when unresolved or ambiguous.
        :rtype: int | None
        """
        if service_type not in _IN_SCOPE_SERVICE_TYPES:
            return None

        normalized_host = host.strip() if host else None
        if normalized_host:
            resolved_port = (
                port
                if port is not None
                else default_port_for_service_type(service_type)
            )
            address_key = (service_type, normalized_host, resolved_port)
            if address_key in self.ambiguous_addresses:
                return None
            service_id = self.by_address.get(address_key)
            if service_id is not None:
                return service_id

        normalized_name = service_name.strip() if service_name else None
        if normalized_name:
            name_key = (service_type, normalized_name)
            if name_key in self.ambiguous_names:
                return None
            return self.by_name.get(name_key)

        return None


async def load_service_id_lookup(session: AsyncSession) -> ServiceIdLookup:
    """Load inventory services used by the legacy form backfill reconstructors.

    :param session: The inventory database session.
    :type session: AsyncSession
    :return: A lookup table covering MySQL and PostgreSQL inventory services.
    :rtype: ServiceIdLookup
    """
    services = await ServiceManager.list(
        session,
        col(Service.type).in_(tuple(_IN_SCOPE_SERVICE_TYPES)),
        select_related=(Service.node,),
    )
    return ServiceIdLookup.from_services(services)


def meta_service_hints(
    meta: Mapping[str, Any],
    *,
    service_type: ServiceTypeEnum,
    host: str | None = None,
    port: int | None = None,
) -> tuple[str | None, int | None, str | None]:
    """Extract host, port, and service-name hints from task ``meta`` for lookup.

    Connectivity keys written by the framework create path take precedence over
    legacy ``_service_*`` stamps. Explicit ``host`` / ``port`` arguments override
    metadata when provided.

    :param meta: The task ``data['meta']`` mapping.
    :type meta: Mapping[str, Any]
    :param service_type: The expected inventory service type (used only for typing
        clarity at call sites).
    :type service_type: ServiceTypeEnum
    :param host: An explicit host override from task YAML/config parsing.
    :type host: str | None
    :param port: An explicit port override from task YAML/config parsing.
    :type port: int | None
    :return: ``(host, port, service_name)`` suitable for :meth:`ServiceIdLookup.resolve`.
    :rtype: tuple[str | None, int | None, str | None]
    """
    del service_type  # reserved for call-site clarity and future validation
    resolved_host = host
    if not resolved_host:
        for key in (CONNECTIVITY_META_HOST_KEY, "_service_host"):
            candidate = meta.get(key)
            if isinstance(candidate, str) and candidate.strip():
                resolved_host = candidate.strip()
                break

    resolved_port = port
    if resolved_port is None:
        for key in (CONNECTIVITY_META_PORT_KEY, "_service_port"):
            candidate = meta.get(key)
            if isinstance(candidate, int):
                resolved_port = candidate
                break

    service_name = meta.get("_service_name")
    if isinstance(service_name, str):
        service_name = service_name.strip() or None
    else:
        service_name = None

    return resolved_host, resolved_port, service_name
