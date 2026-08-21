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

"""Test which hosts OM keeps a row for, and how each resolves to an executor.

The case this module exists for is the one the old service-driven enumeration could
not express at all: a host with a PMM client, a live executor and **no database**.
It is not hypothetical -- the sandbox runs three -- and it is the row a future install
app needs, so "it is in scope" is asserted here rather than assumed.

The other half is scope. A node that is neither running a database nor able to run
anything is some other machine PMM happens to monitor, and PMM's own server node is
one of them; keeping those would pad the estate with rows nothing can ever act on.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.sep.apps.om_inventory.enumeration import build_hosts, InventoryHost
from app.sep.apps.om_inventory.inventory import InventoryService
from app.sep.apps.om_inventory.mapping import ExecutorState, get_executor_states
from app.sep.apps.om_inventory.models import NodeResolution

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


def executors(
    hosts: dict[str, str], *, reachable: bool = True, driver_healthy: bool = True
) -> dict[str, ExecutorState]:
    """Build an executor-state map from a ``{name: address}`` shorthand.

    Defaults to usable, which is what most tests here want; the flags exist for the
    ones asserting the split between "no client registered" and "registered but
    cannot run anything".

    :param hosts: The executor hosts, ``{name: address}``.
    :param reachable: Whether the backend has contact with them.
    :param driver_healthy: Whether their driver can run a job.
    :return: The states keyed by name.
    """
    return {
        name: ExecutorState(
            name=name,
            address=address,
            reachable=reachable,
            driver_healthy=driver_healthy,
        )
        for name, address in hosts.items()
    }


def _state(
    name: str,
    *,
    reachable: bool = True,
    driver_healthy: bool = True,
    address: str = "10.0.0.1",
) -> dict:
    """Build one entry as ``GET /hosts/states/`` serves it.

    :param name: The host name.
    :param reachable: Whether the backend has contact with it.
    :param driver_healthy: Whether its driver can run a job.
    :param address: Its address.
    :return: The wire entry.
    """
    return {
        "name": name,
        "address": address,
        "reachable": reachable,
        "driver_healthy": driver_healthy,
        "detail": None,
    }


class TestScope:
    """Assert which nodes become rows and which are left out."""

    def test_host_with_an_executor_and_no_database_is_in_scope(self) -> None:
        """The empty host is the point of the host table, not an edge case.

        A service-driven enumeration cannot produce this row at all: there is no
        service to derive it from. Losing it would mean OM could never answer "where
        could a database be installed".
        """
        hosts = build_hosts(
            [node("pmm-client-node00", "172.24.0.4")],
            [],
            executors({"pmm-client-node00": "172.24.0.4"}),
        )

        assert [host.node_id for host in hosts] == ["id-pmm-client-node00"]
        assert hosts[0].has_executor

    def test_host_with_a_database_and_no_executor_is_in_scope(self) -> None:
        """Monitored but not actionable is still part of the estate.

        Dropping it would make a stopped or misconfigured host vanish from the
        inventory rather than show up as unreachable, which is the opposite of what
        the freshness columns are for.
        """
        hosts = build_hosts(
            [node("db00", "10.0.0.1")], [service("db00", "db00")], executors({})
        )

        assert [host.node_id for host in hosts] == ["id-db00"]
        assert not hosts[0].has_executor
        assert hosts[0].resolution is NodeResolution.ORPHANED

    def test_node_with_neither_is_left_out(self) -> None:
        """PMM's own server node is the case this keeps out.

        It is in inventory, it runs no MongoDB, and nothing dispatches to it. A row
        for it would be permanently empty and permanently unactionable.
        """
        hosts = build_hosts([node("pmm-server", "127.0.0.1")], [], executors({}))

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
            executors({"db00": "10.0.0.1"}),
        )

        assert hosts == []


class TestUnusableExecutors:
    """Assert a broken executor keeps its host in the estate rather than dropping it."""

    def test_a_host_whose_executor_is_down_stays_in_scope(self) -> None:
        """A machine does not leave the estate because its Nomad agent stopped.

        Scope is decided on whether an executor *matched*, not on whether it works.
        Deciding it on usability would make a host disappear from the inventory at
        exactly the moment someone starts looking for it -- and, for a host with no
        database, disappear with no service to bring it back.
        """
        hosts = build_hosts(
            [node("pmm-client-node00", "172.24.0.4")],
            [],
            executors({"pmm-client-node00": "172.24.0.4"}, reachable=False),
        )

        assert len(hosts) == 1
        assert hosts[0].has_executor is False
        assert hosts[0].executor_document["registered"] is True
        assert hosts[0].executor_document["reachable"] is False

    def test_an_unusable_executor_still_resolves_by_name(self) -> None:
        """Matching runs against every known client, not the usable ones.

        Otherwise a registered-but-broken client reports as "no executor", which
        reads as never onboarded and sends the operator to set up a machine that is
        already set up.
        """
        hosts = build_hosts(
            [node("db00", "10.0.0.1")],
            [service("db00", "db00")],
            executors({"db00": "10.0.0.1"}, driver_healthy=False),
        )

        assert hosts[0].executor_host == "db00"
        assert hosts[0].resolution is NodeResolution.NAME
        assert hosts[0].executor_document["driver_healthy"] is False


class TestExecutorMatching:
    """Assert how a node is paired with the executor host that serves it."""

    def test_matches_by_name_first(self) -> None:
        """Name is the primary key of the executor list, so it wins."""
        hosts = build_hosts(
            [node("db00", "10.0.0.1")], [], executors({"db00": "10.0.0.1"})
        )

        assert hosts[0].executor_host == "db00"
        assert hosts[0].resolution is NodeResolution.NAME

    def test_falls_back_to_address(self) -> None:
        """A Nomad client registered under a different name still serves the host."""
        hosts = build_hosts(
            [node("db00", "10.0.0.1")], [], executors({"nomad-client-7": "10.0.0.1"})
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
            executors({"somewhere-else": "10.9.9.9"}),
        )

        assert hosts[0].executor_host is None
        assert hosts[0].resolution is NodeResolution.ORPHANED


class TestInventoryHost:
    """Assert the small contract the rest of the sweep reads off a host."""

    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            (
                ExecutorState("db00", "10.0.0.1", reachable=True, driver_healthy=True),
                True,
            ),
            (
                ExecutorState("db00", "10.0.0.1", reachable=False, driver_healthy=True),
                False,
            ),
            (
                ExecutorState("db00", "10.0.0.1", reachable=True, driver_healthy=False),
                False,
            ),
            (None, False),
        ],
        ids=["usable", "unreachable", "driver-unhealthy", "no-executor"],
    )
    def test_has_executor(self, state: ExecutorState | None, *, expected: bool) -> None:
        """``has_executor`` decides whether a probe is dispatched, so it means usable.

        A matched-but-unusable executor answering ``True`` here would produce a
        dispatch that waits out its timeout instead of a row saying why the host
        cannot be reached.

        :param state: The matched executor's state, or ``None``.
        :param expected: Whether a probe can run there.
        """
        host = InventoryHost(
            node_id="id",
            name="db00",
            address=None,
            executor_host=state.name if state else None,
            resolution=NodeResolution.NAME,
            executor_state=state,
        )

        assert host.has_executor is expected

    @pytest.mark.parametrize(
        ("state", "registered", "reachable", "driver_healthy"),
        [
            (
                ExecutorState("db00", "10.0.0.1", reachable=True, driver_healthy=True),
                True,
                True,
                True,
            ),
            (
                ExecutorState("db00", "10.0.0.1", reachable=False, driver_healthy=True),
                True,
                False,
                True,
            ),
            (
                ExecutorState("db00", "10.0.0.1", reachable=True, driver_healthy=False),
                True,
                True,
                False,
            ),
            (None, False, False, False),
        ],
        ids=["usable", "unreachable", "driver-unhealthy", "never-registered"],
    )
    def test_executor_document_splits_the_orphan_case(
        self,
        state: ExecutorState | None,
        *,
        registered: bool,
        reachable: bool,
        driver_healthy: bool,
    ) -> None:
        """The three ways a host is unprobeable are three different rows.

        This is the whole point of §11's split. "Nothing can run here" was one
        outcome and is now three: never onboarded, onboarded and down, onboarded and
        broken. They need different people to fix them, so collapsing them sends the
        reader to the wrong place two times in three.

        :param state: The matched executor's state, or ``None``.
        :param registered: Whether an executor client exists for this host at all.
        :param reachable: Whether the backend has contact with it.
        :param driver_healthy: Whether it can run a job.
        """
        host = InventoryHost(
            node_id="id",
            name="db00",
            address=None,
            executor_host=state.name if state else None,
            resolution=NodeResolution.NAME,
            executor_state=state,
        )

        assert host.executor_document == {
            "registered": registered,
            "reachable": reachable,
            "driver_healthy": driver_healthy,
            "detail": None,
        }

    def test_executor_document_carries_the_backend_reason(self) -> None:
        """The reason travels with the row, so the estate view is self-explanatory."""
        host = InventoryHost(
            node_id="id",
            name="db00",
            address=None,
            executor_host="db00",
            resolution=NodeResolution.NAME,
            executor_state=ExecutorState(
                name="db00",
                address="10.0.0.1",
                reachable=True,
                driver_healthy=False,
                detail="Failed to find raw_exec",
            ),
        )

        assert host.executor_document["detail"] == "Failed to find raw_exec"


class TestDuplicateRegistrations:
    """One host name, several executor registrations.

    Restarting a host's agent leaves the old registration behind as ``down`` beside
    the new one. ``get_hosts`` never had to care: everything in it was usable by
    construction, so collapsing duplicates could only ever pick another usable entry.
    Reporting unusable hosts breaks that, and picking the wrong one calls a running
    machine unreachable and refuses to dispatch to it.

    Measured in this workspace's sandbox before the fix: ``pmm-client-node00``
    registered once ready and twice down, and a scoped refresh of it failed.
    """

    @pytest.mark.asyncio
    async def test_the_usable_registration_wins_whatever_the_order(self) -> None:
        """A live registration beats a stale one, listed before it or after it."""
        for entries in (
            [_state("node00", reachable=False), _state("node00", reachable=True)],
            [_state("node00", reachable=True), _state("node00", reachable=False)],
        ):
            api = MagicMock()
            api.get = AsyncMock(return_value=entries)

            states = await get_executor_states(api)

            assert states["node00"].usable is True

    @pytest.mark.asyncio
    async def test_all_unusable_still_reports_one(self) -> None:
        """A genuinely down host keeps a row, or the split loses the case it exists for."""
        api = MagicMock()
        api.get = AsyncMock(
            return_value=[
                _state("node00", reachable=False),
                _state("node00", reachable=False),
            ]
        )

        states = await get_executor_states(api)

        assert states["node00"].reachable is False
        assert states["node00"].usable is False
