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

"""Test the service-to-executor mapping.

The mapping is the whole point of the worker, and its most dangerous failure mode is
silent: :meth:`~app.sep.sync.models.BaseTaskSyncer.get_task_target` falls back to an
arbitrary executor host when nothing matches, which would run a node's probe on an
unrelated box and report facts about a mongod that is not there. These tests pin the
orphaned behaviour so that fallback can never be reintroduced by accident.
"""

import pytest

from app.sep.apps.om_inventory.inventory import InventoryService
from app.sep.apps.om_inventory.mapping import map_service, map_services
from app.sep.apps.om_inventory.models import NodeResolution

#: Services in the three-service fixture that resolve to a live executor.
EXPECTED_RESOLVED = 2
#: Services in the wholly-stale fixture.
STALE_SERVICE_COUNT = 5


def make_service(
    name: str = "svc",
    node_name: str | None = "node",
    node_address: str | None = "10.0.0.1",
) -> InventoryService:
    """Build an inventory service for a mapping case.

    :param name: The service name.
    :param node_name: The node's registered name.
    :param node_address: The node's registered address.
    :return: The service.
    """
    return InventoryService(
        service_id=1,
        external_id="ff0275b6-3633-474a-8068-3c39d3c7a4da",
        name=name,
        port=27017,
        cluster="c",
        replication_set="rs",
        environment="sandbox",
        node_name=node_name,
        node_address=node_address,
    )


class TestMapService:
    """Cover resolving one service against the available executor hosts."""

    def test_matches_by_node_name(self) -> None:
        """A node whose name is an executor host resolves to it."""
        mapped = map_service(
            make_service(node_name="host-a"), {"host-a": "10.0.0.9", "host-b": "x"}
        )

        assert mapped.executor_host == "host-a"
        assert mapped.resolution is NodeResolution.NAME
        assert mapped.is_resolved

    def test_name_wins_over_address(self) -> None:
        """The name match is tried first, even when another host has the address."""
        mapped = map_service(
            make_service(node_name="host-a", node_address="10.0.0.1"),
            {"host-a": "10.0.0.9", "host-b": "10.0.0.1"},
        )

        assert mapped.executor_host == "host-a"
        assert mapped.resolution is NodeResolution.NAME

    def test_falls_back_to_address(self) -> None:
        """A node whose name matches nothing resolves by its address."""
        mapped = map_service(
            make_service(node_name="unknown", node_address="10.0.0.1"),
            {"host-b": "10.0.0.1"},
        )

        assert mapped.executor_host == "host-b"
        assert mapped.resolution is NodeResolution.ADDRESS

    @pytest.mark.parametrize(
        ("node_name", "node_address"),
        [
            ("gone", "10.0.0.254"),
            (None, "10.0.0.254"),
            ("gone", None),
            (None, None),
        ],
    )
    def test_unmatched_is_orphaned_never_a_fallback_host(
        self, node_name: str | None, node_address: str | None
    ) -> None:
        """An unmatched service is orphaned rather than sent to an arbitrary host.

        This is the regression guard. ``get_task_target`` would return the first
        available host here; doing that would probe the wrong machine and report its
        facts under this service's name.
        """
        hosts = {"unrelated-a": "10.0.0.1", "unrelated-b": "10.0.0.2"}

        mapped = map_service(
            make_service(node_name=node_name, node_address=node_address), hosts
        )

        assert mapped.executor_host is None
        assert mapped.resolution is NodeResolution.ORPHANED
        assert not mapped.is_resolved

    def test_no_executors_at_all_orphans_rather_than_raising(self) -> None:
        """An empty executor list orphans every service instead of raising."""
        mapped = map_service(make_service(), {})

        assert mapped.resolution is NodeResolution.ORPHANED


class TestMapServices:
    """Cover mapping a whole inventory listing."""

    def test_preserves_order_and_splits_resolved_from_orphaned(self) -> None:
        """Every service gets exactly one entry, in inventory order."""
        services = [
            make_service(name="a", node_name="host-a"),
            make_service(name="b", node_name="gone", node_address="10.9.9.9"),
            make_service(name="c", node_name="host-c"),
        ]

        mapped = map_services(services, {"host-a": "1", "host-c": "3"})

        assert [entry.service.name for entry in mapped] == ["a", "b", "c"]
        assert [entry.resolution for entry in mapped] == [
            NodeResolution.NAME,
            NodeResolution.ORPHANED,
            NodeResolution.NAME,
        ]
        assert sum(entry.is_resolved for entry in mapped) == EXPECTED_RESOLVED

    def test_orphaned_services_are_still_reported(self) -> None:
        """A wholly stale inventory yields rows, not an empty result.

        An inventory listing routinely outlives the executors that served it -- in
        the workspace sandbox this was 16 of 25 services -- so orphaned entries must
        survive into the output rather than being filtered away.
        """
        # Distinct addresses per service: sharing the live host's address would
        # resolve them by the address fallback, which is not what this covers.
        services = [
            make_service(
                name=f"stale-{index}",
                node_name=f"gone-{index}",
                node_address=f"10.9.9.{index}",
            )
            for index in range(STALE_SERVICE_COUNT)
        ]

        mapped = map_services(services, {"live": "10.0.0.1"})

        assert len(mapped) == STALE_SERVICE_COUNT
        assert all(entry.resolution is NodeResolution.ORPHANED for entry in mapped)
