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

"""Test which hosts POM keeps a row for, and how each resolves to an executor.

The case this module exists for is the one the old service-driven enumeration could
not express at all: a host with a PMM client, a live executor and **no database**.
It is not hypothetical -- the sandbox runs three -- and it is the row a future install
app needs, so "it is in scope" is asserted here rather than assumed.

The other half is scope. A node that is neither running a database nor able to run
anything is some other machine PMM happens to monitor, and PMM's own server node is
one of them; keeping those would pad the estate with rows nothing can ever act on.
"""

from typing import Any

import pytest

from app.sep.apps.pom_discovery.enumeration import build_hosts, InventoryHost
from app.sep.apps.pom_discovery.inventory import InventoryService
from app.sep.apps.pom_discovery.models import NodeResolution

#: Distinguishes "the caller did not care about the id" from "inventory holds none",
#: which is the whole point of one of the tests below and is not expressible with
#: ``None`` as the default.
UNSET = object()


def node(name: str, address: str | None = None, external_id: Any = UNSET) -> dict:
    """Build one inventory node entry.

    :param name: The node's registered name.
    :param address: Its address.
    :param external_id: PMM's node id, which inventory stores under this key. Pass
        ``None`` for a node inventory has not yet learned an id for.
    :return: The entry as the inventory listing serves it.
    """
    return {
        "name": name,
        "address": address,
        "external_id": f"id-{name}" if external_id is UNSET else external_id,
    }


def service(name: str, node_name: str | None, node_address: str | None = None):
    """Build one MongoDB service as inventory reports it.

    :param name: The service name.
    :param node_name: Its node's registered name.
    :param node_address: Its node's address.
    :return: The service.
    """
    return InventoryService(
        service_id=1,
        external_id=f"svc-{name}",
        name=name,
        port=27017,
        cluster=None,
        replication_set=None,
        environment=None,
        node_name=node_name,
        node_address=node_address,
    )


class TestScope:
    """Assert which nodes become rows and which are left out."""

    def test_host_with_an_executor_and_no_database_is_in_scope(self) -> None:
        """The empty host is the point of the host table, not an edge case.

        A service-driven enumeration cannot produce this row at all: there is no
        service to derive it from. Losing it would mean POM could never answer "where
        could a database be installed".
        """
        hosts = build_hosts(
            [node("pmm-client-node00", "172.24.0.4")],
            [],
            {"pmm-client-node00": "172.24.0.4"},
        )

        assert [host.node_id for host in hosts] == ["id-pmm-client-node00"]
        assert hosts[0].has_executor

    def test_host_with_a_database_and_no_executor_is_in_scope(self) -> None:
        """Monitored but not actionable is still part of the estate.

        Dropping it would make a stopped or misconfigured host vanish from the
        inventory rather than show up as unreachable, which is the opposite of what
        the freshness columns are for.
        """
        hosts = build_hosts([node("db00", "10.0.0.1")], [service("db00", "db00")], {})

        assert [host.node_id for host in hosts] == ["id-db00"]
        assert not hosts[0].has_executor
        assert hosts[0].resolution is NodeResolution.ORPHANED

    def test_node_with_neither_is_left_out(self) -> None:
        """PMM's own server node is the case this keeps out.

        It is in inventory, it runs no MongoDB, and nothing dispatches to it. A row
        for it would be permanently empty and permanently unactionable.
        """
        hosts = build_hosts([node("pmm-server", "127.0.0.1")], [], {})

        assert hosts == []

    def test_node_without_a_pmm_id_is_skipped(self) -> None:
        """An unkeyable node cannot be a row.

        PMM's node id is the primary key and the id the trigger passes; a row without
        one could not be joined, refreshed or targeted. The usual cause is an
        inventory sync that has not caught up, so it is skipped rather than invented.
        """
        hosts = build_hosts(
            [node("db00", "10.0.0.1", external_id=None)],
            [service("db00", "db00")],
            {"db00": "10.0.0.1"},
        )

        assert hosts == []


class TestExecutorMatching:
    """Assert how a node is paired with the executor host that serves it."""

    def test_matches_by_name_first(self) -> None:
        """Name is the primary key of the executor list, so it wins."""
        hosts = build_hosts([node("db00", "10.0.0.1")], [], {"db00": "10.0.0.1"})

        assert hosts[0].executor_host == "db00"
        assert hosts[0].resolution is NodeResolution.NAME

    def test_falls_back_to_address(self) -> None:
        """A Nomad client registered under a different name still serves the host."""
        hosts = build_hosts(
            [node("db00", "10.0.0.1")], [], {"nomad-client-7": "10.0.0.1"}
        )

        assert hosts[0].executor_host == "nomad-client-7"
        assert hosts[0].resolution is NodeResolution.ADDRESS

    def test_never_falls_back_to_an_arbitrary_host(self) -> None:
        """An unmatched node is orphaned, not assigned to whatever is available.

        ``BaseTaskSyncer.get_task_target`` does fall back with strict matching off,
        which here would mean probing one machine and recording the answers against
        another -- confidently wrong facts, which are worse than none.
        """
        hosts = build_hosts(
            [node("db00", "10.0.0.1")],
            [service("db00", "db00")],
            {"somewhere-else": "10.9.9.9"},
        )

        assert hosts[0].executor_host is None
        assert hosts[0].resolution is NodeResolution.ORPHANED


class TestInventoryHost:
    """Assert the small contract the rest of the sweep reads off a host."""

    @pytest.mark.parametrize(
        ("executor_host", "expected"),
        [("db00", True), (None, False)],
        ids=["with-executor", "orphaned"],
    )
    def test_has_executor(self, executor_host: str | None, *, expected: bool) -> None:
        """``has_executor`` is what decides whether anything can run on the host.

        :param executor_host: The matched executor, or ``None``.
        :param expected: Whether the host should report one.
        """
        host = InventoryHost(
            node_id="id",
            name="db00",
            address=None,
            executor_host=executor_host,
            resolution=NodeResolution.NAME,
        )

        assert host.has_executor is expected
