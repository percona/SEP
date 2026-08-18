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

"""Test the per-service records a sweep writes alongside its facts.

The counters answer "5 of 14 answered"; these records answer "which five, on which
host, and why did that one take a minute". They are the only place a sweep says where
it probed, so what they claim has to survive the cases that make them interesting: a
service with no executor, a host whose probe failed, and a service PMM does not know.
"""

from contextlib import nullcontext
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.sep.apps.pom_discovery.dispatch import HostProbeResult
from app.sep.apps.pom_discovery.inventory import InventoryService
from app.sep.apps.pom_discovery.mapping import MappedService
from app.sep.apps.pom_discovery.models import NodeResolution
from app.sep.apps.pom_discovery.service import _sweep

OBSERVED_AT = "2026-08-12T12:00:00+00:00"

#: A host's wall-clock, as the dispatcher would have measured it.
HOST_SECONDS = 12.5
#: A failing host's, which is the case where the number matters most.
FAILED_HOST_SECONDS = 61.0
#: One dispatch's, shared by every service that host served.
SHARED_HOST_SECONDS = 8.25

#: A probe record shaped like the payload's NDJSON, trimmed to the fields asserted.
RECORD: dict[str, Any] = {
    "binary_version": "7.0.39-21",
    "database": {"db_version": "7.0.39-21", "storage_engine": "wiredTiger"},
    "process": {"config_path": "/etc/mongod.conf", "argv": "mongod --config ..."},
    "system": {"os_name": "Ubuntu 24.04.3 LTS", "kernel": "6.17.0-35-generic"},
}


def make_service(
    name: str, external_id: str | None = "ff0275b6-3633-474a-8068-3c39d3c7a4da"
) -> InventoryService:
    """Build an inventory service.

    :param name: The service name.
    :param external_id: PMM's service UUID, or ``None`` where inventory holds none.
    :return: The service.
    """
    return InventoryService(
        service_id=1,
        external_id=external_id,
        name=name,
        port=27017,
        cluster="c",
        replication_set="rs",
        environment="sandbox",
        node_name="node00",
        node_address="10.0.0.1",
    )


def mapped(
    name: str,
    host: str | None,
    resolution: NodeResolution,
    external_id: str | None = "ff0275b6-3633-474a-8068-3c39d3c7a4da",
) -> MappedService:
    """Pair a service with the executor host resolved for it.

    :param name: The service name.
    :param host: The executor host, or ``None``.
    :param resolution: How that host was matched.
    :param external_id: PMM's service UUID.
    :return: The mapped service.
    """
    return MappedService(
        service=make_service(name, external_id),
        executor_host=host,
        resolution=resolution,
    )


async def run_sweep(
    mapped_services: list[MappedService], host_results: dict[str, HostProbeResult]
):
    """Run a sweep with the mapping and probe results stubbed.

    Everything above the mapping is I/O -- two authenticated clients, the inventory
    and Nomad -- so it is replaced wholesale; what is under test is what the sweep
    concludes from a mapping and its probe results.

    :param mapped_services: The mapping the sweep should see.
    :param host_results: The probe results, keyed by executor host.
    :return: The sweep's outcome.
    """
    # `auth` is a sync context manager setting a header for its block, so the stub
    # clients have to be usable in a `with`, not merely present.
    clients = (MagicMock(), MagicMock())
    for client in clients:
        client.auth.return_value = nullcontext()

    base = "app.sep.apps.pom_discovery.service"
    with (
        patch(f"{base}._build_clients", AsyncMock(return_value=clients)),
        patch(f"{base}.require_internal_token", return_value="token"),
        patch(f"{base}.list_mongodb_services", AsyncMock(return_value=[])),
        # The host half of enumeration, stubbed empty for the same reason as the
        # service half: these tests are about what a sweep concludes from a mapping,
        # and the hosts it would write have their own tests in test_enumeration.py.
        patch(f"{base}.list_inventory_nodes", AsyncMock(return_value=[])),
        patch(f"{base}.build_hosts", return_value=[]),
        patch(f"{base}.get_executor_states", AsyncMock(return_value={})),
        patch(f"{base}.map_services", return_value=mapped_services),
        patch(f"{base}.probe_all", AsyncMock(return_value=host_results)),
    ):
        return await _sweep(OBSERVED_AT)


@pytest.mark.asyncio
async def test_records_where_each_service_was_probed() -> None:
    """Name the host, how it was matched, and how long it took."""
    outcome = await run_sweep(
        [mapped("svc-a", "node00", NodeResolution.NAME)],
        {
            "node00": HostProbeResult(
                executor_host="node00",
                records={"svc-a": RECORD},
                duration_seconds=HOST_SECONDS,
            )
        },
    )

    assert outcome.answered == 1
    assert len(outcome.nodes) == 1
    node = outcome.nodes[0]
    assert node["service_name"] == "svc-a"
    assert node["executor_host"] == "node00"
    assert node["resolution"] == NodeResolution.NAME
    assert node["answered"] is True
    assert node["duration_seconds"] == HOST_SECONDS
    assert node["facts_collected"] == len(outcome.facts)
    assert node["error"] is None


@pytest.mark.asyncio
async def test_every_field_the_probe_read_is_kept() -> None:
    """Collect the fields no consumer maps, not only the three POM renders."""
    outcome = await run_sweep(
        [mapped("svc-a", "node00", NodeResolution.NAME)],
        {"node00": HostProbeResult(executor_host="node00", records={"svc-a": RECORD})},
    )

    collected = {fact["field"] for fact in outcome.facts}
    # The three POM's document carries...
    assert {"installed_version", "config_path", "argv"} <= collected
    # ...and the ones it does not, which is the reason to keep the run's own copy.
    assert {"storage_engine", "os", "kernel"} <= collected


@pytest.mark.asyncio
async def test_an_orphan_is_recorded_with_no_host() -> None:
    """Keep a row for a service with no executor, and count it as orphaned."""
    outcome = await run_sweep([mapped("svc-b", None, NodeResolution.ORPHANED)], {})

    assert (outcome.resolved, outcome.orphaned, outcome.answered) == (0, 1, 0)
    node = outcome.nodes[0]
    assert node["executor_host"] is None
    assert node["resolution"] == NodeResolution.ORPHANED
    assert node["answered"] is False
    assert node["facts_collected"] == 0


@pytest.mark.asyncio
async def test_a_failed_host_carries_its_error_and_its_time() -> None:
    """Report why a host produced nothing, and how long it took to say so."""
    outcome = await run_sweep(
        [mapped("svc-c", "node01", NodeResolution.ADDRESS)],
        {
            "node01": HostProbeResult(
                executor_host="node01",
                error="probe run FAILED: no output",
                duration_seconds=FAILED_HOST_SECONDS,
            )
        },
    )

    assert (outcome.resolved, outcome.answered) == (1, 0)
    node = outcome.nodes[0]
    assert node["answered"] is False
    assert node["error"] == "probe run FAILED: no output"
    assert node["duration_seconds"] == FAILED_HOST_SECONDS


@pytest.mark.asyncio
async def test_a_service_pmm_does_not_know_is_still_a_row() -> None:
    """Record a service with no PMM id, which can contribute no joinable facts."""
    outcome = await run_sweep(
        [mapped("svc-d", "node00", NodeResolution.NAME, external_id=None)],
        {"node00": HostProbeResult(executor_host="node00", records={"svc-d": RECORD})},
    )

    assert outcome.facts == []
    node = outcome.nodes[0]
    assert node["service_id"] is None
    assert node["service_name"] == "svc-d"
    # It answered -- the host ran the payload. What is missing is a key to join on,
    # which is a different failure from the node not answering.
    assert node["answered"] is True
    assert node["facts_collected"] == 0


@pytest.mark.asyncio
async def test_one_dispatch_times_every_service_it_served() -> None:
    """Repeat a host's duration across the services that host served."""
    outcome = await run_sweep(
        [
            mapped("svc-a", "node00", NodeResolution.NAME),
            mapped("svc-b", "node00", NodeResolution.NAME),
        ],
        {
            "node00": HostProbeResult(
                executor_host="node00",
                records={"svc-a": RECORD, "svc-b": RECORD},
                duration_seconds=SHARED_HOST_SECONDS,
            )
        },
    )

    assert [node["duration_seconds"] for node in outcome.nodes] == [
        SHARED_HOST_SECONDS,
        SHARED_HOST_SECONDS,
    ]
