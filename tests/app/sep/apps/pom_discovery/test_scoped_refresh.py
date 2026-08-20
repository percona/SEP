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

"""Test refreshing named hosts rather than the whole estate.

A full sweep dispatches a Nomad job to every executor host and takes a minute and a
half in this sandbox. "I just did something to this host, is it healthy now" should
not cost that, and it is the question every action PMM grows will ask next.

Two rules make it work, and both are easy to get subtly wrong:

**Conflict is per host.** The old guard refused any run while any other was in
flight. Keep that and a scoped refresh is useless exactly when the estate is busiest,
because the ten-minute schedule is often mid-sweep. Two runs collide only when they
would touch the same host -- and a full refresh touches all of them.

**Nothing outside the scope is written.** This is where §5.4's "only a run that
attempted an entity touches its timestamps" stops being a principle and starts being
load-bearing: get it wrong and refreshing one host marks the rest of the estate
failed, which is worse than not having the feature.
"""

from datetime import timedelta

import pytest
import pytest_asyncio
from fastapi import status
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth.providers.casdoor.models import CasdoorUser
from app.core.utils.date_time import utc_now
from app.sep.apps.pom_discovery.config import pom_discovery_settings
from app.sep.apps.pom_discovery.crud import (
    conflict_detail,
    conflicting_run,
    ProbeRunManager,
    upsert_host,
)
from app.sep.apps.pom_discovery.enumeration import InventoryHost
from app.sep.apps.pom_discovery.inventory import InventoryService
from app.sep.apps.pom_discovery.mapping import ExecutorState, MappedService
from app.sep.apps.pom_discovery.models import NodeResolution, ProbeRun, ProbeRunStatus
from app.sep.apps.pom_discovery.service import (
    _finalise,
    _narrow_to_scope,
    _terminal_status,
    SweepOutcome,
)
from app.sep.deps import (
    get_current_user,
    get_session,
    require_bearer_for_unsafe_methods,
)
from app.sep.main import sep_app

BASE = "/api/apps/pom_discovery"
NODE_A = "id-db00"
NODE_B = "id-db01"
#: One host with an executor and one without, which is the smallest estate that can
#: tell hosts_total and hosts_probeable apart.
TWO_HOSTS = 2


@pytest_asyncio.fixture
async def api(regular_user: CasdoorUser, session: AsyncSession) -> AsyncClient:
    """Yield an authenticated client sharing the test session.

    :param regular_user: The authenticated user.
    :param session: The database session the routes should use.
    :return: The client.
    """
    sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user
    sep_app.dependency_overrides[get_session] = lambda: session
    client = AsyncClient(
        transport=ASGITransport(app=sep_app),
        base_url="http://test",
        headers={"Authorization": "Bearer test"},
    )
    try:
        yield client
    finally:
        await client.aclose()
        sep_app.dependency_overrides = {}


@pytest_asyncio.fixture
async def two_hosts(session: AsyncSession) -> AsyncSession:
    """Give the estate two hosts, so "one of them" is a meaningful scope.

    :param session: The database session.
    :return: The same session, with rows.
    """
    for node_id, name in ((NODE_A, "db00"), (NODE_B, "db01")):
        await upsert_host(
            session,
            node_id=node_id,
            name=name,
            address=None,
            executor_host=name,
            observed={"collected_at": "2026-08-17T09:00:00+00:00"},
        )
    await session.commit()
    return session


async def start_run(session: AsyncSession, scope: list[str] | None) -> ProbeRun:
    """Put a run in flight with the given scope.

    :param session: The database session.
    :param scope: Its scope, or ``None`` for the whole estate.
    :return: The run.
    """
    return await ProbeRunManager.save(
        session, ProbeRun(scope=scope, status=ProbeRunStatus.RUNNING)
    )


def host(node_id: str, name: str) -> InventoryHost:
    """Build one enumerated host.

    :param node_id: PMM's node id.
    :param name: Its registered name.
    :return: The host.
    """
    return InventoryHost(
        node_id=node_id,
        name=name,
        address=None,
        executor_host=name,
        resolution=NodeResolution.NAME,
    )


def service_on(name: str) -> InventoryService:
    """Build one service on the named node.

    :param name: The node's name.
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
        node_name=name,
        node_address=None,
    )


class TestNarrowToScope:
    """Assert what a scoped sweep keeps and what it drops."""

    def test_keeps_only_the_named_hosts_and_their_services(self) -> None:
        """Everything downstream of enumeration is narrowed, in one place."""
        hosts = [host(NODE_A, "db00"), host(NODE_B, "db01")]
        services = [service_on("db00"), service_on("db01")]
        mapped = [MappedService(s, s.node_name, NodeResolution.NAME) for s in services]

        scoped_hosts, scoped_services, scoped_mapped = _narrow_to_scope(
            hosts, services, mapped, [NODE_A]
        )

        assert [h.node_id for h in scoped_hosts] == [NODE_A]
        assert [s.name for s in scoped_services] == ["db00"]
        assert [m.service.name for m in scoped_mapped] == ["db00"]

    def test_an_unknown_id_narrows_to_nothing_rather_than_everything(self) -> None:
        """The dangerous failure is a scope that silently means "all".

        The endpoint rejects an unknown id before this runs, so reaching here means
        the estate changed underneath the request -- and refreshing nothing is the
        safe reading, because refreshing everything would touch timestamps the caller
        never asked about.
        """
        hosts = [host(NODE_A, "db00")]

        scoped_hosts, scoped_services, scoped_mapped = _narrow_to_scope(
            hosts, [service_on("db00")], [], ["id-that-vanished"]
        )

        assert (scoped_hosts, scoped_services, scoped_mapped) == ([], [], [])


class TestTerminalStatus:
    """Assert what counts as a successful run now that hosts can be probed alone."""

    def test_a_host_with_no_database_that_answered_is_a_success(self) -> None:
        """The case that made this wrong: a scoped refresh of a pmm-client host.

        It resolves no services, because there are none, and judging on services
        alone reported ``FAILED`` for a run that did exactly what it was asked.
        Measured against ``standalone-node00`` before the verdict counted hosts.
        """
        outcome = SweepOutcome(
            dispatched={"pmm-client-node00"},
            host_documents={"pmm-client-node00": {"os": "Ubuntu 24.04"}},
        )

        assert _terminal_status(outcome) is ProbeRunStatus.SUCCESS

    def test_a_dispatch_that_answered_nothing_is_partial(self) -> None:
        """One silent host among several is partial, not total failure."""
        outcome = SweepOutcome(
            dispatched={"a", "b"}, host_documents={"a": {"os": "Ubuntu 24.04"}}
        )

        assert _terminal_status(outcome) is ProbeRunStatus.PARTIAL

    def test_reaching_nothing_at_all_is_a_failure(self) -> None:
        """No host answered and no service resolved: POM's own plumbing is down.

        That is the condition the probe exists to surface, so it must stay loud.
        """
        assert _terminal_status(SweepOutcome()) is ProbeRunStatus.FAILED

    def test_orphans_alone_do_not_fail_a_run(self) -> None:
        """A service with no executor is an estate fact, not a sweep failure."""
        outcome = SweepOutcome(
            orphaned=3,
            dispatched={"a"},
            host_documents={"a": {"os": "Ubuntu 24.04"}},
        )

        assert _terminal_status(outcome) is ProbeRunStatus.SUCCESS


class TestTriggerScope:
    """Assert the trigger's contract."""

    @pytest.mark.asyncio
    async def test_no_body_means_the_whole_estate(
        self, api: AsyncClient, two_hosts: AsyncSession
    ) -> None:
        """The scheduled sweep and a bare POST take the same path.

        :param api: The authenticated client.
        :param two_hosts: The populated session.
        """
        response = await api.post(f"{BASE}/runs")

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.json()["scope"] is None

    @pytest.mark.asyncio
    async def test_a_scope_is_recorded_on_the_run(
        self, api: AsyncClient, two_hosts: AsyncSession
    ) -> None:
        """Stored rather than inferred: the receipt cannot be read without it.

        :param api: The authenticated client.
        :param two_hosts: The populated session.
        """
        response = await api.post(f"{BASE}/runs", json={"node_ids": [NODE_A]})

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.json()["scope"] == [NODE_A]

    @pytest.mark.asyncio
    async def test_a_full_estate_run_is_sql_null_not_json_null(
        self, api: AsyncClient, two_hosts: AsyncSession
    ) -> None:
        """A full sweep has to store SQL NULL, or `scope IS NULL` finds no full sweeps.

        SQLAlchemy's JSON types store a Python ``None`` as the JSON scalar ``null``
        unless told otherwise, and the Python side reads back ``None`` either way --
        so nothing complains until someone asks the database which runs were full
        sweeps and gets an empty answer. Measured happening before ``none_as_null``
        was set, which is why this asserts against SQL rather than the response.

        :param api: The authenticated client.
        :param two_hosts: The populated session.
        """
        await api.post(f"{BASE}/runs")

        full = await two_hosts.exec(
            text("select count(*) from pom_schema.discovery_run where scope is null")
        )
        assert full.scalar() == 1

    @pytest.mark.asyncio
    async def test_an_unknown_host_is_404_not_an_empty_refresh(
        self, api: AsyncClient, two_hosts: AsyncSession
    ) -> None:
        """SEP's inventory copy can lag PMM's, so this is a real case.

        Answering 404 by name beats running a refresh that quietly does nothing and
        reports success.

        :param api: The authenticated client.
        :param two_hosts: The populated session.
        """
        response = await api.post(f"{BASE}/runs", json={"node_ids": ["nope"]})

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "nope" in response.json()["detail"]


class TestConflict:
    """Assert that conflict is judged per host."""

    @pytest.mark.asyncio
    async def test_two_different_hosts_do_not_conflict(
        self, api: AsyncClient, two_hosts: AsyncSession
    ) -> None:
        """The whole point: refreshing one host must not wait on another.

        :param api: The authenticated client.
        :param two_hosts: The populated session.
        """
        await start_run(two_hosts, [NODE_A])

        response = await api.post(f"{BASE}/runs", json={"node_ids": [NODE_B]})

        assert response.status_code == status.HTTP_202_ACCEPTED

    @pytest.mark.asyncio
    async def test_the_same_host_conflicts(
        self, api: AsyncClient, two_hosts: AsyncSession
    ) -> None:
        """Two runs probing one host at once is the case worth refusing.

        :param api: The authenticated client.
        :param two_hosts: The populated session.
        """
        await start_run(two_hosts, [NODE_A])

        response = await api.post(f"{BASE}/runs", json={"node_ids": [NODE_A]})

        assert response.status_code == status.HTTP_409_CONFLICT

    @pytest.mark.asyncio
    async def test_a_full_refresh_conflicts_with_a_scoped_one(
        self, api: AsyncClient, two_hosts: AsyncSession
    ) -> None:
        """A run over everything overlaps every scope by definition.

        :param api: The authenticated client.
        :param two_hosts: The populated session.
        """
        await start_run(two_hosts, [NODE_A])

        response = await api.post(f"{BASE}/runs")

        assert response.status_code == status.HTTP_409_CONFLICT

    @pytest.mark.asyncio
    async def test_a_scoped_refresh_conflicts_with_a_full_one(
        self, api: AsyncClient, two_hosts: AsyncSession
    ) -> None:
        """And the same in reverse, which is the easy half to forget.

        :param api: The authenticated client.
        :param two_hosts: The populated session.
        """
        await start_run(two_hosts, None)

        response = await api.post(f"{BASE}/runs", json={"node_ids": [NODE_A]})

        assert response.status_code == status.HTTP_409_CONFLICT

    @pytest.mark.asyncio
    async def test_an_abandoned_run_is_reaped_rather_than_blocking_forever(
        self, api: AsyncClient, two_hosts: AsyncSession
    ) -> None:
        """A crashed worker leaves a RUNNING row nothing else will ever advance.

        Without the reaper that row wedges the app permanently, which is a bug this
        app has already had once.

        :param api: The authenticated client.
        :param two_hosts: The populated session.
        """
        stale = await start_run(two_hosts, [NODE_A])
        stale.started_at = utc_now() - (
            pom_discovery_settings.STALE_RUN_AFTER + timedelta(minutes=1)
        )
        await ProbeRunManager.save(two_hosts, stale)

        response = await api.post(f"{BASE}/runs", json={"node_ids": [NODE_A]})

        assert response.status_code == status.HTTP_202_ACCEPTED
        reaped = await ProbeRunManager.get(two_hosts, id=stale.id)
        assert reaped.status == ProbeRunStatus.FAILED
        assert "abandoned" in (reaped.error or "")


class TestHostCounters:
    """Assert a run's receipt counts hosts, not only the services on them.

    A sweep has attempted hosts as well as services since a host became probeable for
    its own sake, and until these columns existed the receipt could not say so. A
    refresh of a pmm-client host read as "0 of 0 services", which is exactly what a
    run that did nothing at all looks like - on the one host POM most exists to
    describe.
    """

    @pytest.mark.asyncio
    async def test_a_host_only_refresh_reports_what_it_reached(
        self, session: AsyncSession
    ) -> None:
        """A host with no database produces non-zero counters.

        :param session: The database session.
        """
        host = InventoryHost(
            node_id="id-pmm-client-node00",
            name="pmm-client-node00",
            address="10.0.0.2",
            executor_host="pmm-client-node00",
            resolution=NodeResolution.NAME,
            executor_state=ExecutorState(
                "pmm-client-node00",
                "10.0.0.2",
                reachable=True,
                driver_healthy=True,
            ),
        )
        run = await ProbeRunManager.save(session, ProbeRun())
        outcome = SweepOutcome(
            hosts=[host],
            dispatched={"pmm-client-node00"},
            host_documents={"pmm-client-node00": {"os": "Ubuntu 24.04"}},
        )

        await _finalise(session, run.id, outcome)

        stored = await ProbeRunManager.get(session, id=run.id)
        assert (stored.hosts_total, stored.hosts_probeable, stored.hosts_answered) == (
            1,
            1,
            1,
        )
        # Zero services is the honest answer here, and it is why the host counters had
        # to exist rather than the service ones being reinterpreted.
        assert stored.services_total == 0

    @pytest.mark.asyncio
    async def test_a_host_with_no_executor_counts_but_is_not_probeable(
        self, session: AsyncSession
    ) -> None:
        """``total`` and ``probeable`` differ, which is the point of having both.

        The gap between them is the estate nothing can be run on - a fact about
        onboarding rather than a failure of the sweep, and one a single "hosts" count
        would hide.

        :param session: The database session.
        """
        reachable = InventoryHost(
            node_id="id-a",
            name="a",
            address=None,
            executor_host="a",
            resolution=NodeResolution.NAME,
            executor_state=ExecutorState(
                "a", "10.0.0.1", reachable=True, driver_healthy=True
            ),
        )
        stranded = InventoryHost(
            node_id="id-b",
            name="b",
            address=None,
            executor_host=None,
            resolution=NodeResolution.ORPHANED,
        )
        run = await ProbeRunManager.save(session, ProbeRun())
        outcome = SweepOutcome(
            hosts=[reachable, stranded],
            dispatched={"a"},
            host_documents={"a": {"os": "Ubuntu 24.04"}},
        )

        await _finalise(session, run.id, outcome)

        stored = await ProbeRunManager.get(session, id=run.id)
        assert stored.hosts_total == TWO_HOSTS
        assert stored.hosts_probeable == 1
        assert stored.hosts_answered == 1


class TestTheScheduleRespectsSingleFlight:
    """Assert a scheduled sweep cannot start on top of one already running.

    The guard used to live only in the trigger endpoint, and **the schedule does not
    go through it** - Celery beat calls the task directly. So a scheduled sweep would
    start while another was still dispatching, both would enqueue the same job for the
    same host, and the Tasks layer would refuse the duplicate with
    ``409 Identical queue item already running``. The loser recorded that against a
    host that was perfectly healthy.

    Measured on this workspace's sandbox: two full sweeps 31 seconds apart, four
    healthy replicaset hosts marked unanswered with a 409 as their reason. It did no
    lasting damage only because the good sweep happened to finish last and overwrite
    the failure - reverse the order and four fine hosts read as failing.
    """

    @pytest.mark.asyncio
    async def test_a_second_full_sweep_is_skipped_not_run(
        self, session: AsyncSession
    ) -> None:
        """The whole estate overlaps the whole estate.

        :param session: The database session.
        """
        in_flight = await ProbeRunManager.save(session, ProbeRun(scope=None))

        blocking = await conflicting_run(
            session, None, stale_after=timedelta(minutes=30)
        )

        assert blocking is not None
        assert blocking.id == in_flight.id

    @pytest.mark.asyncio
    async def test_a_run_does_not_refuse_itself(self, session: AsyncSession) -> None:
        """The trigger endpoint creates the row before dispatching.

        Without excluding its own id the task would find that row, conclude a sweep
        was already in flight, and skip every run started through the API - which is
        every manual refresh.

        :param session: The database session.
        """
        mine = await ProbeRunManager.save(session, ProbeRun(scope=None))

        blocking = await conflicting_run(
            session, None, exclude=mine.id, stale_after=timedelta(minutes=30)
        )

        assert blocking is None

    @pytest.mark.asyncio
    async def test_disjoint_scopes_do_not_block_each_other(
        self, session: AsyncSession
    ) -> None:
        """Two one-host refreshes of different hosts are not a conflict.

        Single-flight is per host precisely so a ten-minute schedule does not refuse
        the refresh someone wants.

        :param session: The database session.
        """
        await ProbeRunManager.save(session, ProbeRun(scope=[NODE_A]))

        blocking = await conflicting_run(
            session, [NODE_B], stale_after=timedelta(minutes=30)
        )

        assert blocking is None

    @pytest.mark.asyncio
    async def test_an_abandoned_run_is_reaped_rather_than_honoured(
        self, session: AsyncSession
    ) -> None:
        """A crashed worker must not wedge the app permanently.

        :param session: The database session.
        """
        stale = await ProbeRunManager.save(session, ProbeRun(scope=None))
        stale.started_at = utc_now() - timedelta(hours=2)
        await ProbeRunManager.save(session, stale)

        blocking = await conflicting_run(
            session, None, stale_after=timedelta(minutes=30)
        )

        assert blocking is None
        reaped = await ProbeRunManager.get(session, id=stale.id)
        assert reaped.status is ProbeRunStatus.FAILED
        assert reaped.error is not None

    @pytest.mark.asyncio
    async def test_the_message_names_the_hosts_that_are_held(
        self, session: AsyncSession
    ) -> None:
        """Naming the held hosts beats "a sweep is already running".

        :param session: The database session.
        """
        blocking = await ProbeRunManager.save(session, ProbeRun(scope=[NODE_A]))

        detail = conflict_detail(blocking, [NODE_A, NODE_B])

        assert NODE_A in detail
        assert str(blocking.id) in detail
