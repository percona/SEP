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

"""Resolve executor (Nomad / Celery) node names from network addresses.

The inventory display name (e.g. ``mvc-lab-maria1``) and the executor node
name (e.g. ``mvc-lab-db3``) live in independent name spaces. The host
dropdown reconciles the two by matching on ``address`` so the form submits
the executor-keyed name expected by ``/connectivity-check/``. Centralise
that lookup here so any other call site that starts from an inventory record
can produce the same answer the dropdown does.
"""

from collections.abc import Iterable


def address_to_name_index(pairs: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Invert ``(name, address)`` pairs into an ``{address: name}`` index.

    Both the executor-hosts mapping (``{node_name: address}`` returned by
    ``GET /api/tasks/hosts/``) and the inventory display-name mapping
    (built from ``GET /api/inventory/`` items) need to be consulted by
    ``address``. Build the address-keyed index once via this helper so each
    lookup is O(1) instead of degrading to O(n²) when looped per item.

    :param pairs: Iterable of ``(name, address)`` pairs.
    :type pairs: collections.abc.Iterable[tuple[str, str]]
    :return: Mapping from network address to the first name that registered
        it in iteration order. Callers requiring a deterministic choice on
        duplicate addresses should pass an ordered iterable.
    :rtype: dict[str, str]
    """
    result: dict[str, str] = {}
    for name, address in pairs:
        if address not in result:
            result[address] = name
    return result


def resolve_executor_name_by_address(
    address: str, executor_hosts: dict[str, str]
) -> str | None:
    """Find the executor node name registered for ``address``.

    :param address: The network address as recorded in inventory.
    :type address: str
    :param executor_hosts: Mapping of executor node name to address as
        returned by ``GET /api/tasks/hosts/``.
    :type executor_hosts: dict[str, str]
    :return: The first executor node name whose address matches ``address``,
        or ``None`` when no executor is registered for that address. When
        multiple executor names share the same address, the first match in
        iteration order is returned; callers requiring a deterministic
        choice should pass an ordered mapping.
    :rtype: str | None
    """
    return address_to_name_index(executor_hosts.items()).get(address)
