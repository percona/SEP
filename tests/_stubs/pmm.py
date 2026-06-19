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

"""Canonical stub for the PMM monitoring service.

Pattern reference for milestone M4. The actual consolidation pulls the PMM
mocks currently inlined across inventory sync and dashboard tests into a
single fixture surface here, with payloads recorded via ``vcrpy``.

Usage from a test::

    from tests._stubs.pmm import patch_pmm_metrics

    def test_something(mocker):
        patch_pmm_metrics(mocker, nodes=12, services=45)
        ...

Companion modules: ``tests._stubs.casdoor`` and ``tests._stubs.nomad``.
"""

from typing import Any

from pytest_mock import MockerFixture


def patch_pmm_metrics(
    mocker: MockerFixture,
    *,
    nodes: int = 0,
    services: int = 0,
) -> dict[str, list[dict[str, Any]]]:
    """Patch the PMM client's inventory queries with a deterministic snapshot.

    Reference shape only — the production stub will cover the full
    inventory-sync surface once milestone M4 lands. Patches the two
    ``PMMRemoteAPI`` coroutines the dashboard counts (``get_nodes`` and
    ``get_services``) so a test gets stable node/service inventories without a
    live PMM. The returned dict holds the same lists that were installed, so
    tests can assert against them.

    :param mocker: The ``pytest-mock`` fixture from the calling test.
    :type mocker: pytest_mock.MockerFixture
    :param nodes: Number of placeholder nodes ``get_nodes`` returns.
    :type nodes: int
    :param services: Number of placeholder services ``get_services`` returns.
    :type services: int
    :return: The node and service lists the patched methods return.
    :rtype: dict[str, list[dict[str, Any]]]
    """
    snapshot: dict[str, list[dict[str, Any]]] = {
        "nodes": [{"node_id": f"node-{i}"} for i in range(nodes)],
        "services": [{"service_id": f"service-{i}"} for i in range(services)],
    }
    mocker.patch(
        "app.sep.clients.pmm.PMMRemoteAPI.get_nodes",
        new=mocker.AsyncMock(return_value=snapshot["nodes"]),
    )
    mocker.patch(
        "app.sep.clients.pmm.PMMRemoteAPI.get_services",
        new=mocker.AsyncMock(return_value=snapshot["services"]),
    )
    return snapshot
