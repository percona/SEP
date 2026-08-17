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

"""Test that a host is probed for its own sake, not only through its services.

The app used to dispatch strictly per resolved service, which meant the machines it
could say the least about were exactly the ones worth an install decision: a PMM
client with no database has no service to be reached through. So a dispatch now goes
to every executor host in the estate, and the payload prints a record for the host
whether or not it has any targets.

That record is also what stops host attributes being read off whichever service
happened to answer -- they belong to the host, they are collected once, and now they
are reported once.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.sep.apps.pom_discovery.dispatch import parse_ndjson, probe_all
from app.sep.apps.pom_discovery.inventory import InventoryService
from app.sep.apps.pom_discovery.mapping import MappedService
from app.sep.apps.pom_discovery.models import NodeResolution

HOST_LINE = (
    '{"service": null, "collected_at": 1, "status": "ok", '
    '"system": {"os_name": "Ubuntu 24.04"}, "binary_version": null}'
)
SERVICE_LINE = (
    '{"service": "db00", "collected_at": 1, "status": "ok", '
    '"binary_version": "7.0.39-21"}'
)


def mapped(name: str, host: str | None) -> MappedService:
    """Pair a service with an executor host.

    :param name: The service name.
    :param host: The executor host, or ``None`` for an orphan.
    :return: The mapped service.
    """
    return MappedService(
        service=InventoryService(
            service_id=1,
            external_id=f"svc-{name}",
            name=name,
            port=27017,
            cluster=None,
            replication_set=None,
            environment=None,
            node_name=name,
            node_address=None,
        ),
        executor_host=host,
        resolution=NodeResolution.NAME if host else NodeResolution.ORPHANED,
    )


class TestParseNdjson:
    """Assert the host record is told apart from the service records."""

    def test_splits_the_host_record_from_the_service_records(self) -> None:
        """``service: null`` is the whole discriminator."""
        records, host_record = parse_ndjson(f"{HOST_LINE}\n{SERVICE_LINE}")

        assert list(records) == ["db00"]
        assert host_record is not None
        assert host_record["system"]["os_name"] == "Ubuntu 24.04"

    def test_a_host_with_no_database_still_reports(self) -> None:
        """The only line from an empty host is its own, and it must not be dropped.

        This is the case the app could not express at all before: no targets meant no
        output, and the payload refused to run.
        """
        records, host_record = parse_ndjson(HOST_LINE)

        assert records == {}
        assert host_record is not None

    def test_noise_around_the_records_is_ignored(self) -> None:
        """Pip and the job template write to the same stream the payload does."""
        stdout = f"Collecting pymongo\n{HOST_LINE}\nnot json\n{SERVICE_LINE}\n"

        records, host_record = parse_ndjson(stdout)

        assert list(records) == ["db00"]
        assert host_record is not None

    def test_no_output_yields_no_host_record(self) -> None:
        """``None`` is what distinguishes "did not answer" from "has no database"."""
        records, host_record = parse_ndjson("")

        assert records == {}
        assert host_record is None


class TestProbeAllTargets:
    """Assert which hosts a sweep dispatches to."""

    @pytest.mark.asyncio
    async def test_dispatches_to_a_host_that_serves_no_service(self) -> None:
        """The empty host is dispatched to, or it can never be described.

        :return: Nothing.
        """
        seen: dict[str, list] = {}

        async def fake_probe_host(_api, host, entries):
            seen[host] = entries
            return type("R", (), {"executor_host": host})()

        with patch(
            "app.sep.apps.pom_discovery.dispatch.probe_host",
            AsyncMock(side_effect=fake_probe_host),
        ):
            await probe_all(
                AsyncMock(),
                [mapped("db00", "db00")],
                executor_hosts=["db00", "pmm-client-node00"],
            )

        assert set(seen) == {"db00", "pmm-client-node00"}
        # A host that serves services keeps them as targets...
        assert [entry.service.name for entry in seen["db00"]] == ["db00"]
        # ...and one that serves none is dispatched to with an empty target list.
        assert seen["pmm-client-node00"] == []

    @pytest.mark.asyncio
    async def test_an_orphaned_service_adds_no_dispatch(self) -> None:
        """Orphans have no executor by definition, so there is nowhere to dispatch.

        :return: Nothing.
        """
        seen: dict[str, list] = {}

        async def fake_probe_host(_api, host, entries):
            seen[host] = entries
            return type("R", (), {"executor_host": host})()

        with patch(
            "app.sep.apps.pom_discovery.dispatch.probe_host",
            AsyncMock(side_effect=fake_probe_host),
        ):
            await probe_all(AsyncMock(), [mapped("db01", None)])

        assert seen == {}
