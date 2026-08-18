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

"""Test the freshness and failure lifecycle of ``pom.host`` and ``pom.service``.

Every rule here is one that reads as an implementation detail and is not. Each is
cheap to get right now and expensive to discover later, because the symptom is never
a crash -- it is a column that quietly stops meaning what it says:

* overwrite ``failing_since`` on every failure and "failing for three days" silently
  becomes "failed a minute ago", so the duration is always one schedule interval;
* erase ``observed`` on a failed probe and you lose what the host was running exactly
  when you most want to know, which is while it is unreachable;
* touch the timestamps of an entity a run did not target and one scoped refresh marks
  the rest of the estate failed;
* upsert every column blindly and the first user-writable field ever added is wiped by
  the next sweep.

The last one has nothing to protect yet, which is exactly why the test is written now:
it is the one that cannot be added after the fact, because by then the data is gone.
"""

from contextlib import nullcontext
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.sep.apps.pom_discovery.crud import (
    list_hosts,
    list_services,
    upsert_host,
    upsert_service,
)
from app.sep.apps.pom_discovery.enumeration import InventoryHost
from app.sep.apps.pom_discovery.mapping import ExecutorState
from app.sep.apps.pom_discovery.models import NodeResolution, PomHost, PomService
from app.sep.apps.pom_discovery.service import _persist_estate, SweepOutcome

NODE_ID = "id-db00"
SERVICE_ID = "svc-db00"

#: A document shaped like the one a sweep stores, trimmed to what is asserted.
GOOD_DOCUMENT = {"collected_at": "2026-08-17T09:00:00+00:00", "os": "Ubuntu 24.04"}
LATER_DOCUMENT = {"collected_at": "2026-08-17T10:00:00+00:00", "os": "Ubuntu 24.04"}

#: Two failures in a row, which is the smallest number that can catch an overwritten
#: ``failing_since``.
TWO_FAILURES = 2


async def add_host(session: AsyncSession, **overrides) -> PomHost:
    """Upsert one host with the usual identity and commit.

    :param session: The database session.
    :param overrides: Anything to vary for the case under test.
    :return: The stored row.
    """
    defaults = {
        "node_id": NODE_ID,
        "name": "db00",
        "address": "10.0.0.1",
        "executor_host": "db00",
        "observed": GOOD_DOCUMENT,
    }
    host = await upsert_host(session, **{**defaults, **overrides})
    await session.commit()
    return host


class TestHostLifecycle:
    """Assert what one attempt does to a host row."""

    @pytest.mark.asyncio
    async def test_first_sight_creates_the_row(self, session: AsyncSession) -> None:
        """A host is a row from the first time it is seen.

        :param session: The database session.
        """
        host = await add_host(session)

        assert host.node_id == NODE_ID
        assert host.observed == GOOD_DOCUMENT
        assert host.first_seen_at is not None
        assert host.last_success_at is not None
        assert host.failing_since is None
        assert host.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_failure_keeps_the_last_good_document(
        self, session: AsyncSession
    ) -> None:
        """A failed probe must not erase what the last good one saw.

        What a host was running when it was last reachable is exactly what is wanted
        while it is not, and the PMM side is built to consume aged facts rather than
        absent ones.

        :param session: The database session.
        """
        await add_host(session)

        await add_host(session, observed=None, error="boom")

        host = (await list_hosts(session))[0]
        assert host.observed == GOOD_DOCUMENT
        assert host.last_error == "boom"
        assert host.consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_failing_since_is_the_first_failure_not_the_latest(
        self, session: AsyncSession
    ) -> None:
        """``COALESCE`` is the whole trick, and this is what it buys.

        Two consecutive failures must leave ``failing_since`` at the first one. Move
        it and the column can never say anything but "about one schedule interval".

        :param session: The database session.
        """
        await add_host(session)
        await add_host(session, observed=None, error="first")
        first_failure = (await list_hosts(session))[0].failing_since

        await add_host(session, observed=None, error="second")

        host = (await list_hosts(session))[0]
        assert host.failing_since == first_failure
        assert host.consecutive_failures == TWO_FAILURES
        assert host.last_error == "second"

    @pytest.mark.asyncio
    async def test_success_clears_the_failure_history(
        self, session: AsyncSession
    ) -> None:
        """Recovery resets the counters, or a host that healed still reads as broken.

        :param session: The database session.
        """
        await add_host(session, observed=None, error="boom")

        await add_host(session, observed=LATER_DOCUMENT)

        host = (await list_hosts(session))[0]
        assert host.observed == LATER_DOCUMENT
        assert host.failing_since is None
        assert host.consecutive_failures == 0
        assert host.last_error is None

    @pytest.mark.asyncio
    async def test_an_unattempted_host_keeps_its_freshness_columns(
        self, session: AsyncSession
    ) -> None:
        """Being *seen* is not being *probed*, and the columns must know it.

        This is the live case: a host with an executor and no MongoDB service has
        nothing dispatched to it, and a host with no executor cannot be dispatched to
        at all. Counting either as a failed attempt would have it accrue a failure
        every sweep -- forever -- for a condition that is not a failure. Its identity
        and executor still refresh, because those are what a reader needs.

        :param session: The database session.
        """
        await add_host(session)
        before = (await list_hosts(session))[0]
        attempt_at, success_at = before.last_attempt_at, before.last_success_at

        await add_host(
            session, executor_host=None, observed=None, error="x", attempted=False
        )

        host = (await list_hosts(session))[0]
        assert host.executor_host is None
        assert host.last_attempt_at == attempt_at
        assert host.last_success_at == success_at
        assert host.consecutive_failures == 0
        assert host.last_error is None

    @pytest.mark.asyncio
    async def test_identity_is_refreshed_on_every_sight(
        self, session: AsyncSession
    ) -> None:
        """A renamed or readdressed node must not keep reading as the old one.

        :param session: The database session.
        """
        await add_host(session)

        await add_host(session, name="db00-renamed", address="10.0.0.9")

        host = (await list_hosts(session))[0]
        assert (host.name, host.address) == ("db00-renamed", "10.0.0.9")


class TestServiceLifecycle:
    """Assert the same lifecycle on the service table, plus what is specific to it."""

    @pytest.mark.asyncio
    async def test_service_requires_its_host_row(self, session: AsyncSession) -> None:
        """The foreign key is real, so hosts are written first.

        Not a formality: it is what stops a service row pointing at a host the estate
        view cannot show.

        :param session: The database session.
        """
        await add_host(session)

        await upsert_service(
            session,
            service_id=SERVICE_ID,
            node_id=NODE_ID,
            name="db00",
            port=27017,
            role="mongod",
            observed=GOOD_DOCUMENT,
        )
        await session.commit()

        stored = await list_services(session, node_id=NODE_ID)
        assert [service.service_id for service in stored] == [SERVICE_ID]

    @pytest.mark.asyncio
    async def test_an_orphaned_service_is_a_row_with_no_attempt(
        self, session: AsyncSession
    ) -> None:
        """A service PMM knows is a row even when nothing could probe it.

        Omitting it reports a healthier estate than exists -- the PoC measured 17 of
        18 services unreachable in a single run, and a listing showing one would have
        been worse than useless. What it does not get is an attempt.

        :param session: The database session.
        """
        await add_host(session)

        await upsert_service(
            session,
            service_id=SERVICE_ID,
            node_id=NODE_ID,
            name="db00",
            port=27017,
            role=None,
            attempted=False,
        )
        await session.commit()

        service = (await list_services(session))[0]
        assert service.last_attempt_at is None
        assert service.observed == {}
        assert service.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_a_failed_attempt_keeps_the_last_known_role(
        self, session: AsyncSession
    ) -> None:
        """``role`` is only written when a probe determined one.

        Same reason ``observed`` survives a failure: an unreachable arbiter is still
        an arbiter, and blanking the column would lose that on the first bad sweep.

        :param session: The database session.
        """
        await add_host(session)
        await upsert_service(
            session,
            service_id=SERVICE_ID,
            node_id=NODE_ID,
            name="db00",
            port=27017,
            role="arbiter",
            observed=GOOD_DOCUMENT,
        )
        await session.commit()

        await upsert_service(
            session,
            service_id=SERVICE_ID,
            node_id=NODE_ID,
            name="db00",
            port=27017,
            role=None,
            observed=None,
            error="unreachable",
        )
        await session.commit()

        service = (await list_services(session))[0]
        assert service.role == "arbiter"
        assert service.observed == GOOD_DOCUMENT


class TestUserWritableFieldsSurvive:
    """Guard the field that does not exist yet.

    Nothing in either table is user-writable today, so this asserts the *shape* of the
    upsert rather than a feature: a sweep must only write the columns discovery owns.
    Written now because the alternative is discovering it the day someone adds an
    assigned name or a suppression flag and watches the next sweep erase it.
    """

    @pytest.mark.asyncio
    async def test_a_sweep_only_touches_the_columns_it_owns(
        self, session: AsyncSession
    ) -> None:
        """Stand in for a user-written field with a column discovery never sets.

        ``first_seen_at`` is the one column on the row that no attempt is allowed to
        move: it is written once, at creation. If a sweep were rewriting the whole
        row, this is what would change.

        :param session: The database session.
        """
        await add_host(session)
        original = (await list_hosts(session))[0]
        stamped = original.first_seen_at - timedelta(days=30)
        original.first_seen_at = stamped
        session.add(original)
        await session.commit()

        await add_host(session, observed=LATER_DOCUMENT, run_id=uuid4())

        host = (await list_hosts(session))[0]
        assert host.first_seen_at == stamped
        assert host.observed == LATER_DOCUMENT


class TestRunLinkage:
    """Assert the join back to the receipt that explains a row's state."""

    @pytest.mark.asyncio
    async def test_the_run_id_is_recorded_on_an_attempt(
        self, session: AsyncSession
    ) -> None:
        """Without it a row's freshness cannot be traced to the sweep that set it.

        :param session: The database session.
        """
        run_id = uuid4()

        await add_host(session, run_id=run_id)

        assert (await list_hosts(session))[0].last_run_id == run_id

    @pytest.mark.asyncio
    async def test_updated_at_moves_even_without_an_attempt(
        self, session: AsyncSession
    ) -> None:
        """A row that was merely re-seen still changed, and should say so.

        :param session: The database session.
        """
        await add_host(session)
        before = (await list_hosts(session))[0].updated_at

        await add_host(session, name="db00-renamed", attempted=False)

        assert (await list_hosts(session))[0].updated_at >= before


@pytest.mark.asyncio
async def test_tables_live_in_poms_own_schema(session: AsyncSession) -> None:
    """The tables are ``pom.host`` and ``pom.service``, not SEP's ``service``.

    Named plainly because the schema qualifies them -- which means SEP inventory's
    ``service`` and POM's are two different tables, and on a bind without schemas they
    would not be. Asserting the declared schema is what keeps that from regressing
    into a table name collision nobody notices until ``create_all`` fails.

    :param session: The database session.
    """
    assert PomHost.__table__.schema == "pom_schema"
    assert PomService.__table__.schema == "pom_schema"
    assert PomHost.__tablename__ == "host"
    assert PomService.__tablename__ == "service"


class TestExecutorFactsReachTheRow:
    """Assert the executor facts survive the trip from enumeration into the row.

    They are the one part of a host's document that does **not** come from the probe:
    SEP knows them without running anything, which is precisely why they must be
    written for hosts that were never probed. Those are the rows where the document
    would otherwise be empty, and an empty document is the case a reader most needs
    explained.
    """

    @pytest.mark.asyncio
    async def test_an_unprobeable_host_still_records_why(
        self, session: AsyncSession
    ) -> None:
        """A host nothing can run on gets a document saying so, not an empty one.

        :param session: The database session.
        """
        host = InventoryHost(
            node_id=NODE_ID,
            name="db00",
            address="10.0.0.1",
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
        outcome = SweepOutcome(total=0, hosts=[host])

        with patch(
            "app.sep.apps.pom_discovery.service.get_async_session_maker",
            return_value=lambda: nullcontext(session),
        ):
            await _persist_estate(outcome, uuid4())

        stored = (await list_hosts(session))[0]
        assert stored.observed["executor"] == {
            "registered": True,
            "reachable": True,
            "driver_healthy": False,
            "detail": "Failed to find raw_exec",
        }

    @pytest.mark.asyncio
    async def test_probe_facts_and_executor_facts_share_the_document(
        self, session: AsyncSession
    ) -> None:
        """Merging the two must not drop either half.

        :param session: The database session.
        """
        host = InventoryHost(
            node_id=NODE_ID,
            name="db00",
            address="10.0.0.1",
            executor_host="db00",
            resolution=NodeResolution.NAME,
            executor_state=ExecutorState(
                "db00", "10.0.0.1", reachable=True, driver_healthy=True
            ),
        )
        outcome = SweepOutcome(total=0, hosts=[host])
        outcome.host_documents["db00"] = dict(GOOD_DOCUMENT)
        outcome.dispatched.add("db00")

        with patch(
            "app.sep.apps.pom_discovery.service.get_async_session_maker",
            return_value=lambda: nullcontext(session),
        ):
            await _persist_estate(outcome, uuid4())

        stored = (await list_hosts(session))[0]
        assert stored.observed["os"] == GOOD_DOCUMENT["os"]
        assert stored.observed["executor"]["driver_healthy"] is True
