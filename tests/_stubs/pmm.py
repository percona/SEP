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
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Patch the PMM client's metrics query with a deterministic snapshot.

    Reference shape only — the production stub will cover the full
    inventory-sync surface once milestone M4 lands. The returned dict is the
    same shape the dashboard expects so tests can assert against it.

    :param mocker: The ``pytest-mock`` fixture from the calling test.
    :type mocker: pytest_mock.MockerFixture
    :param nodes: Node count returned by the metrics query.
    :type nodes: int
    :param services: Service count returned by the metrics query.
    :type services: int
    :param extra: Optional extra metric fields merged into the snapshot.
    :type extra: dict[str, Any] | None
    :return: The metrics payload the PMM client would return.
    :rtype: dict[str, Any]
    """
    snapshot: dict[str, Any] = {"nodes": nodes, "services": services}
    if extra:
        snapshot.update(extra)
    mocker.patch(
        "app.core.pmm.client.PMMClient.get_metrics",
        new=mocker.AsyncMock(return_value=snapshot),
    )
    return snapshot
