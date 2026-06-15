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

"""Test the app.sep.sync.syncers.system_facts.syncer module."""

import json
from unittest.mock import AsyncMock, call

import pytest

from app.inventory.models import ServiceTypeEnum
from app.sep.inventory import CreatedNode, CreatedService
from app.sep.models import SyncInventoryEntityTypeEnum
from app.sep.sync.models import TaskRunResult
from app.sep.sync.syncers.system_facts.syncer import (
    SystemFactsService,
    SystemFactsSyncer,
)
from tests.app.factories import (
    CreatedNodeFactory,
    CreatedServiceFactory,
    MOCK_CREATED_NODE_ID,
)

NODE_NAME = "db-node-1"
NODE_ADDRESS = "10.0.0.5"
COLLECTED_AT = "2026-06-01T12:00:00+00:00"
# observed_at as serialized by pydantic model_dump(mode="json") (UTC -> trailing "Z").
COLLECTED_AT_JSON = "2026-06-01T12:00:00Z"
MYSQL_PORT = 3306
MYSQL_VERSION = "8.0.35"
OS_VERSION = "Ubuntu 22.04"
INSTALLED_PACKAGES = [{"name": "glibc", "version": "2.35"}]
HOST_CONFIG = {"kernel": "5.15.0"}
EXECUTOR_NAME = "executor-1"
EXECUTOR_ADDRESS = "10.0.0.99"


def _make_service(
    service_type: ServiceTypeEnum, port: int, node: CreatedNode, service_id: int
) -> CreatedService:
    """Build a fake created service attached to ``node``."""
    service = CreatedServiceFactory.build()
    service.id = service_id
    service.node_id = node.id
    service.type = service_type
    service.port = port
    service.node = node
    return service


@pytest.fixture
def mock_syncer(mock_remote_api) -> SystemFactsSyncer:
    """Return a SystemFactsSyncer with mocked tasks/inventory APIs."""
    return SystemFactsSyncer(tasks_api=mock_remote_api, inventory_api=mock_remote_api)


@pytest.fixture
def created_node() -> CreatedNode:
    """Return a node with one MySQL service on a known address."""
    node = CreatedNodeFactory.build()
    node.id = MOCK_CREATED_NODE_ID
    node.name = NODE_NAME
    node.address = NODE_ADDRESS
    node.services = [_make_service(ServiceTypeEnum.MYSQL, MYSQL_PORT, node, 1)]
    return node


@pytest.fixture
def created_service(created_node) -> CreatedService:
    """Return the MySQL service from ``created_node``."""
    return created_node.services[0]


class TestConfigAndCanSync:
    """Test config building and sync eligibility predicates."""

    def test_sync_to_limit_is_service(self):
        """SystemFactsSyncer stops recursion at the service level."""
        assert SystemFactsSyncer.SYNC_TO_LIMIT == SyncInventoryEntityTypeEnum.SERVICE

    def test_build_script_config(self, mock_syncer, created_service):
        """Script config carries probe targets and the collect_host flag."""
        cfg = json.loads(
            mock_syncer.build_script_config([created_service], collect_host=True)
        )
        assert cfg["collect_host"] is True
        assert cfg["services"] == [
            {"address": created_service.address, "type": ServiceTypeEnum.MYSQL}
        ]

    @pytest.mark.parametrize(
        ("service_type", "expected"),
        [
            (ServiceTypeEnum.MYSQL, True),
            (ServiceTypeEnum.POSTGRESQL, True),
            (ServiceTypeEnum.MONGODB, True),
            (ServiceTypeEnum.PROXYSQL, False),
            (ServiceTypeEnum.HAPROXY, False),
            (ServiceTypeEnum.EXTERNAL, False),
        ],
    )
    def test_can_sync_service(self, created_node, service_type, expected):
        """Only DB engine services are collected for facts."""
        service = _make_service(service_type, MYSQL_PORT, created_node, 1)
        assert SystemFactsSyncer.can_sync_service(service) is expected

    def test_can_sync_node_true_with_db_service(self, created_node):
        """A node with at least one DB engine service is collectable."""
        assert SystemFactsSyncer.can_sync_node(created_node) is True

    def test_can_sync_node_true_without_db_service(self, created_node):
        """Host facts are node-level: a proxy-only node is still collectable.

        Host facts (``os_version``/``installed_packages``/``config``) are independent of
        the services on the node, so node eligibility must not be gated on a DB engine.
        """
        created_node.services = [
            _make_service(ServiceTypeEnum.HAPROXY, MYSQL_PORT, created_node, 1)
        ]
        assert SystemFactsSyncer.can_sync_node(created_node) is True


class TestFetchNode:
    """Test fetching node-level facts via the task payload."""

    @pytest.mark.asyncio
    async def test_fetch_node_colocated_collects_host_and_services(
        self, mock_syncer, created_node, created_service, mocker
    ):
        """A co-located node collects host facts and caches service versions."""
        mocker.patch.object(
            SystemFactsSyncer, "get_available_hosts", new_callable=AsyncMock
        ).return_value = {NODE_NAME: NODE_ADDRESS}
        wait = mocker.patch.object(
            SystemFactsSyncer, "wait_for_task_output", new_callable=AsyncMock
        )
        wait.return_value = TaskRunResult(
            1,
            json.dumps(
                {
                    "host": {
                        "os_version": OS_VERSION,
                        "installed_packages": INSTALLED_PACKAGES,
                        "config": HOST_CONFIG,
                        "collected_at": COLLECTED_AT,
                    },
                    "services": {
                        created_service.address: {
                            "db_engine_version": MYSQL_VERSION,
                            "collected_at": COLLECTED_AT,
                        }
                    },
                }
            ),
        )
        updated = await mock_syncer.fetch_node(created_node)

        assert updated is not None
        wait.assert_awaited_once()
        # collect_host True is sent to the payload for a co-located node.
        assert json.loads(wait.await_args.kwargs["config"])["collect_host"] is True
        assert (
            mock_syncer._host_facts_cache[created_node.id]["os_version"] == OS_VERSION
        )
        assert (
            mock_syncer._service_facts_cache[created_service.id]["db_engine_version"]
            == MYSQL_VERSION
        )

    @pytest.mark.asyncio
    async def test_fetch_node_rds_skips_host_but_keeps_services(
        self, mock_syncer, created_node, created_service, mocker
    ):
        """A node with no co-located executor collects service facts only."""
        mock_syncer.default_executor_host = EXECUTOR_NAME
        mocker.patch.object(
            SystemFactsSyncer, "get_available_hosts", new_callable=AsyncMock
        ).return_value = {EXECUTOR_NAME: EXECUTOR_ADDRESS}
        wait = mocker.patch.object(
            SystemFactsSyncer, "wait_for_task_output", new_callable=AsyncMock
        )
        wait.return_value = TaskRunResult(
            1,
            json.dumps(
                {
                    "host": None,
                    "services": {
                        created_service.address: {
                            "db_engine_version": MYSQL_VERSION,
                            "collected_at": COLLECTED_AT,
                        }
                    },
                }
            ),
        )
        updated = await mock_syncer.fetch_node(created_node)

        assert updated is not None  # must NOT skip the whole node
        assert json.loads(wait.await_args.kwargs["config"])["collect_host"] is False
        assert created_node.id not in mock_syncer._host_facts_cache
        assert created_service.id in mock_syncer._service_facts_cache

    @pytest.mark.asyncio
    async def test_fetch_node_colocated_proxy_only_collects_host(
        self, mock_syncer, created_node, mocker
    ):
        """A co-located node with no DB service still collects host facts."""
        created_node.services = [
            _make_service(ServiceTypeEnum.HAPROXY, MYSQL_PORT, created_node, 1)
        ]
        mocker.patch.object(
            SystemFactsSyncer, "get_available_hosts", new_callable=AsyncMock
        ).return_value = {NODE_NAME: NODE_ADDRESS}
        wait = mocker.patch.object(
            SystemFactsSyncer, "wait_for_task_output", new_callable=AsyncMock
        )
        wait.return_value = TaskRunResult(
            1,
            json.dumps(
                {
                    "host": {
                        "os_version": OS_VERSION,
                        "collected_at": COLLECTED_AT,
                    },
                    "services": {},
                }
            ),
        )
        updated = await mock_syncer.fetch_node(created_node)

        assert updated is not None
        wait.assert_awaited_once()
        cfg = json.loads(wait.await_args.kwargs["config"])
        assert cfg["collect_host"] is True
        assert cfg["services"] == []  # no DB engine services to probe
        assert mock_syncer._host_facts_cache[created_node.id]["os_version"] == (
            OS_VERSION
        )

    @pytest.mark.asyncio
    async def test_fetch_node_no_host_no_services_skips_task_run(
        self, mock_syncer, created_node, mocker
    ):
        """A non-co-located node with no DB service runs no task at all."""
        created_node.services = [
            _make_service(ServiceTypeEnum.HAPROXY, MYSQL_PORT, created_node, 1)
        ]
        mock_syncer.default_executor_host = EXECUTOR_NAME
        mocker.patch.object(
            SystemFactsSyncer, "get_available_hosts", new_callable=AsyncMock
        ).return_value = {EXECUTOR_NAME: EXECUTOR_ADDRESS}
        wait = mocker.patch.object(
            SystemFactsSyncer, "wait_for_task_output", new_callable=AsyncMock
        )
        updated = await mock_syncer.fetch_node(created_node)

        assert updated is not None
        wait.assert_not_awaited()
        assert not mock_syncer._host_facts_cache
        assert not mock_syncer._service_facts_cache

    @pytest.mark.asyncio
    async def test_fetch_node_malformed_output_skips_cleanly(
        self, mock_syncer, created_node, mocker
    ):
        """Malformed payload stdout yields empty caches, not an exception."""
        mocker.patch.object(
            SystemFactsSyncer, "get_available_hosts", new_callable=AsyncMock
        ).return_value = {NODE_NAME: NODE_ADDRESS}
        mocker.patch.object(
            SystemFactsSyncer, "wait_for_task_output", new_callable=AsyncMock
        ).return_value = TaskRunResult(1, "not-json")

        updated = await mock_syncer.fetch_node(created_node)

        assert updated is not None
        assert not mock_syncer._host_facts_cache
        assert not mock_syncer._service_facts_cache

    @pytest.mark.asyncio
    async def test_fetch_node_wrong_shape_output_skips_cleanly(
        self, mock_syncer, created_node, mocker
    ):
        """Valid JSON with non-dict host/services degrades to empty caches, no crash."""
        mocker.patch.object(
            SystemFactsSyncer, "get_available_hosts", new_callable=AsyncMock
        ).return_value = {NODE_NAME: NODE_ADDRESS}
        mocker.patch.object(
            SystemFactsSyncer, "wait_for_task_output", new_callable=AsyncMock
        ).return_value = TaskRunResult(
            1, json.dumps({"host": "oops", "services": ["not-a-dict"]})
        )

        updated = await mock_syncer.fetch_node(created_node)

        assert updated is not None
        assert not mock_syncer._host_facts_cache
        assert not mock_syncer._service_facts_cache


class TestPerformNodeSync:
    """Test upserting host observations and recursing into services."""

    @pytest.mark.asyncio
    async def test_perform_node_sync_colocated_upserts_host(
        self, mock_syncer, created_node, mock_remote_api, mocker
    ):
        """Co-located host facts are PUT to the system-observation endpoint."""
        mock_syncer._host_facts_cache[created_node.id] = {
            "os_version": OS_VERSION,
            "installed_packages": INSTALLED_PACKAGES,
            "config": HOST_CONFIG,
            "collected_at": COLLECTED_AT,
        }
        sync_service = mocker.patch.object(
            SystemFactsSyncer, "sync_service", new_callable=AsyncMock
        )
        await mock_syncer.perform_node_sync(created_node, created_node)

        mock_remote_api.put.assert_awaited_once()
        url = mock_remote_api.put.await_args.args[0]
        body = mock_remote_api.put.await_args.kwargs["json"]
        assert url == f"/nodes/{created_node.id}/system-observation"
        assert body["os_version"] == OS_VERSION
        assert body["observed_at"] == COLLECTED_AT_JSON
        sync_service.assert_awaited_once_with(created_node.services[0])

    @pytest.mark.asyncio
    async def test_perform_node_sync_rds_skips_host_put(
        self, mock_syncer, created_node, mock_remote_api, mocker
    ):
        """With no host facts cached, no host observation is written."""
        sync_service = mocker.patch.object(
            SystemFactsSyncer, "sync_service", new_callable=AsyncMock
        )
        await mock_syncer.perform_node_sync(created_node, created_node)

        mock_remote_api.put.assert_not_awaited()
        sync_service.assert_awaited_once_with(created_node.services[0])

    @pytest.mark.asyncio
    async def test_perform_node_sync_empty_host_facts_skips_put(
        self, mock_syncer, created_node, mock_remote_api, mocker
    ):
        """Host facts with no usable field never write a half-empty snapshot."""
        mock_syncer._host_facts_cache[created_node.id] = {"collected_at": COLLECTED_AT}
        mocker.patch.object(SystemFactsSyncer, "sync_service", new_callable=AsyncMock)
        await mock_syncer.perform_node_sync(created_node, created_node)

        mock_remote_api.put.assert_not_awaited()


class TestFetchService:
    """Test resolving cached service facts."""

    @pytest.mark.asyncio
    async def test_fetch_service_returns_cached_version(
        self, mock_syncer, created_service
    ):
        """The cached engine version is surfaced on the carrier."""
        mock_syncer._service_facts_cache[created_service.id] = {
            "db_engine_version": MYSQL_VERSION,
            "collected_at": COLLECTED_AT,
        }
        svc = await mock_syncer.fetch_service(created_service)
        assert isinstance(svc, SystemFactsService)
        assert svc.db_engine_version == MYSQL_VERSION
        assert svc.collected_at == COLLECTED_AT

    @pytest.mark.asyncio
    async def test_fetch_service_consumes_cache_entry(
        self, mock_syncer, created_service
    ):
        """A cache hit is popped so a later failed collection cannot resurface it."""
        mock_syncer._service_facts_cache[created_service.id] = {
            "db_engine_version": MYSQL_VERSION,
            "collected_at": COLLECTED_AT,
        }
        await mock_syncer.fetch_service(created_service)
        assert created_service.id not in mock_syncer._service_facts_cache

    @pytest.mark.asyncio
    async def test_fetch_service_stale_address_not_reused(
        self, mock_syncer, created_node, created_service, mocker
    ):
        """A sibling sharing an address never reads another service's cached fact.

        Service A's fact is cached by A's id. Service B shares A's address but has its own
        id; its fallback collection yields nothing, so B must resolve to ``None`` rather
        than reusing A's version.
        """
        service_b = _make_service(
            ServiceTypeEnum.MYSQL, MYSQL_PORT, created_node, created_service.id + 1
        )
        mock_syncer._service_facts_cache[created_service.id] = {
            "db_engine_version": MYSQL_VERSION,
            "collected_at": COLLECTED_AT,
        }
        mocker.patch.object(
            SystemFactsSyncer, "get_available_hosts", new_callable=AsyncMock
        ).return_value = {NODE_NAME: NODE_ADDRESS}
        mocker.patch.object(
            SystemFactsSyncer, "wait_for_task_output", new_callable=AsyncMock
        ).return_value = TaskRunResult(1, json.dumps({"host": None, "services": {}}))

        assert await mock_syncer.fetch_service(service_b) is None
        # Service A's fact stays untouched (B never popped it).
        assert created_service.id in mock_syncer._service_facts_cache

    @pytest.mark.asyncio
    async def test_fetch_service_cache_miss_collects_single_service(
        self, mock_syncer, created_service, mocker
    ):
        """A standalone service sync (empty cache) collects that one service.

        The scheduled run primes the cache in ``fetch_node``, but a per-service sync
        triggered from the UI starts empty; ``fetch_service`` must fall back to running
        the payload for just that service rather than silently no-op.
        """
        mocker.patch.object(
            SystemFactsSyncer, "get_available_hosts", new_callable=AsyncMock
        ).return_value = {NODE_NAME: NODE_ADDRESS}
        wait = mocker.patch.object(
            SystemFactsSyncer, "wait_for_task_output", new_callable=AsyncMock
        )
        wait.return_value = TaskRunResult(
            1,
            json.dumps(
                {
                    "host": None,
                    "services": {
                        created_service.address: {
                            "db_engine_version": MYSQL_VERSION,
                            "collected_at": COLLECTED_AT,
                        }
                    },
                }
            ),
        )
        svc = await mock_syncer.fetch_service(created_service)

        assert isinstance(svc, SystemFactsService)
        assert svc.db_engine_version == MYSQL_VERSION
        wait.assert_awaited_once()
        # A standalone service collection never collects host facts.
        assert json.loads(wait.await_args.kwargs["config"])["collect_host"] is False

    @pytest.mark.asyncio
    async def test_fetch_service_cache_miss_collection_fails_returns_none(
        self, mock_syncer, created_service, mocker
    ):
        """A fallback collection that yields no version skips the service."""
        mocker.patch.object(
            SystemFactsSyncer, "get_available_hosts", new_callable=AsyncMock
        ).return_value = {NODE_NAME: NODE_ADDRESS}
        mocker.patch.object(
            SystemFactsSyncer, "wait_for_task_output", new_callable=AsyncMock
        ).return_value = TaskRunResult(1, json.dumps({"host": None, "services": {}}))

        assert await mock_syncer.fetch_service(created_service) is None

    @pytest.mark.asyncio
    async def test_fetch_service_uncollected_no_node_returns_none(
        self, mock_syncer, created_service, mocker
    ):
        """A cache miss with no collectable version returns None, never a crash."""
        mocker.patch.object(
            SystemFactsSyncer, "get_available_hosts", new_callable=AsyncMock
        ).return_value = {NODE_NAME: NODE_ADDRESS}
        mocker.patch.object(
            SystemFactsSyncer, "wait_for_task_output", new_callable=AsyncMock
        ).return_value = TaskRunResult(1, "not-json")
        assert await mock_syncer.fetch_service(created_service) is None

    @pytest.mark.asyncio
    async def test_fetch_service_batch_primed_failure_skips_standalone_run(
        self, mock_syncer, created_service, mocker
    ):
        """A batch-attempted service with no version is skipped, not re-collected.

        ``fetch_node`` marks every probed service as batch-attempted. One that failed in
        the batch (no cached version) must resolve to ``None`` without dispatching a fresh
        per-service task -- otherwise a node with K dead services issues ``1 + K`` runs.
        """
        mock_syncer._batch_attempted_services.add(created_service.id)
        collect = mocker.patch.object(
            SystemFactsSyncer, "_collect_single_service", new_callable=AsyncMock
        )

        assert await mock_syncer.fetch_service(created_service) is None
        collect.assert_not_awaited()
        # The marker is consumed so a later standalone sync is free to collect.
        assert created_service.id not in mock_syncer._batch_attempted_services

    @pytest.mark.asyncio
    async def test_fetch_service_unprimed_collects_single_service(
        self, mock_syncer, created_service, mocker
    ):
        """A service never primed by a batch run falls back to standalone collection."""
        collect = mocker.patch.object(
            SystemFactsSyncer, "_collect_single_service", new_callable=AsyncMock
        )
        collect.return_value = {
            "db_engine_version": MYSQL_VERSION,
            "collected_at": COLLECTED_AT,
        }

        svc = await mock_syncer.fetch_service(created_service)

        collect.assert_awaited_once_with(created_service)
        assert isinstance(svc, SystemFactsService)
        assert svc.db_engine_version == MYSQL_VERSION


class TestPerformServiceSync:
    """Test upserting service observations."""

    @pytest.mark.asyncio
    async def test_perform_service_sync_upserts_version(
        self, mock_syncer, created_service, mock_remote_api
    ):
        """The engine version is PUT to the service system-observation endpoint."""
        updated = SystemFactsService.model_validate(
            created_service.model_dump(exclude={"node", "schemas"})
        )
        updated.db_engine_version = MYSQL_VERSION
        updated.collected_at = COLLECTED_AT

        await mock_syncer.perform_service_sync(created_service, updated)

        mock_remote_api.put.assert_awaited_once()
        url = mock_remote_api.put.await_args.args[0]
        body = mock_remote_api.put.await_args.kwargs["json"]
        assert url == f"/services/{created_service.id}/system-observation"
        assert body["db_engine_version"] == MYSQL_VERSION
        assert body["observed_at"] == COLLECTED_AT_JSON

    @pytest.mark.asyncio
    async def test_perform_service_sync_is_idempotent_put_not_post(
        self, mock_syncer, created_service, mock_remote_api
    ):
        """Re-running upserts via PUT (server-side), never POST."""
        updated = SystemFactsService.model_validate(
            created_service.model_dump(exclude={"node", "schemas"})
        )
        updated.db_engine_version = MYSQL_VERSION
        updated.collected_at = COLLECTED_AT

        expected_put_calls = 2
        await mock_syncer.perform_service_sync(created_service, updated)
        await mock_syncer.perform_service_sync(created_service, updated)

        assert mock_remote_api.put.await_count == expected_put_calls
        mock_remote_api.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_perform_service_sync_without_version_skips(
        self, mock_syncer, created_service, mock_remote_api
    ):
        """A carrier missing the version never writes an empty db_engine_version."""
        updated = SystemFactsService.model_validate(
            created_service.model_dump(exclude={"node", "schemas"})
        )
        await mock_syncer.perform_service_sync(created_service, updated)
        mock_remote_api.put.assert_not_awaited()


class TestResolveTaskTarget:
    """Test executor-host resolution and the co-location flag it reports."""

    @pytest.mark.asyncio
    async def test_colocated_by_name(self, mock_syncer, mocker):
        """An executor matching the node name is co-located."""
        mocker.patch.object(
            SystemFactsSyncer, "get_available_hosts", new_callable=AsyncMock
        ).return_value = {NODE_NAME: NODE_ADDRESS}
        target, colocated = await mock_syncer.resolve_task_target(
            NODE_ADDRESS, NODE_NAME
        )
        assert (target, colocated) == (NODE_NAME, True)

    @pytest.mark.asyncio
    async def test_fallback_not_colocated(self, mock_syncer, mocker):
        """A default-executor fallback (RDS) is not co-located."""
        mock_syncer.default_executor_host = EXECUTOR_NAME
        mocker.patch.object(
            SystemFactsSyncer, "get_available_hosts", new_callable=AsyncMock
        ).return_value = {EXECUTOR_NAME: EXECUTOR_ADDRESS}
        target, colocated = await mock_syncer.resolve_task_target(
            NODE_ADDRESS, NODE_NAME
        )
        assert (target, colocated) == (EXECUTOR_NAME, False)

    @pytest.mark.asyncio
    async def test_force_executor_not_matching_node_is_not_colocated(
        self, mock_syncer, mocker
    ):
        """A forced executor that is not the node must NOT report co-location.

        Otherwise host facts gathered on the forced executor would be misattributed to
        the node (writing executor-2's OS/packages onto db-node-1).
        """
        mock_syncer.force_executor_host = "executor-2"
        mocker.patch.object(
            SystemFactsSyncer, "get_available_hosts", new_callable=AsyncMock
        ).return_value = {NODE_NAME: NODE_ADDRESS, "executor-2": "10.0.0.77"}
        target, colocated = await mock_syncer.resolve_task_target(
            NODE_ADDRESS, NODE_NAME
        )
        assert (target, colocated) == ("executor-2", False)

    @pytest.mark.asyncio
    async def test_force_executor_matching_node_name_is_colocated(
        self, mock_syncer, mocker
    ):
        """A forced executor that IS the node (by name) is co-located."""
        mock_syncer.force_executor_host = NODE_NAME
        mocker.patch.object(
            SystemFactsSyncer, "get_available_hosts", new_callable=AsyncMock
        ).return_value = {NODE_NAME: NODE_ADDRESS}
        target, colocated = await mock_syncer.resolve_task_target(
            NODE_ADDRESS, NODE_NAME
        )
        assert (target, colocated) == (NODE_NAME, True)

    @pytest.mark.asyncio
    async def test_force_executor_matching_node_address_is_colocated(
        self, mock_syncer, mocker
    ):
        """A forced executor whose address is the node's is co-located."""
        mock_syncer.force_executor_host = "executor-2"
        mocker.patch.object(
            SystemFactsSyncer, "get_available_hosts", new_callable=AsyncMock
        ).return_value = {"executor-2": NODE_ADDRESS}
        target, colocated = await mock_syncer.resolve_task_target(
            NODE_ADDRESS, NODE_NAME
        )
        assert (target, colocated) == ("executor-2", True)

    @pytest.mark.asyncio
    async def test_no_available_hosts_raises_value_error(self, mock_syncer, mocker):
        """An empty ``/hosts/`` response cannot yield a target and raises."""
        mocker.patch.object(
            SystemFactsSyncer, "get_available_hosts", new_callable=AsyncMock
        ).return_value = {}
        with pytest.raises(ValueError, match="No executor hosts available"):
            await mock_syncer.resolve_task_target(NODE_ADDRESS, NODE_NAME)

    @pytest.mark.asyncio
    async def test_default_executor_not_in_hosts_falls_back_to_first(
        self, mock_syncer, mocker
    ):
        """A configured default executor absent from the host list falls back."""
        mock_syncer.default_executor_host = "ghost-executor"
        mocker.patch.object(
            SystemFactsSyncer, "get_available_hosts", new_callable=AsyncMock
        ).return_value = {EXECUTOR_NAME: EXECUTOR_ADDRESS}
        target, colocated = await mock_syncer.resolve_task_target(
            NODE_ADDRESS, NODE_NAME
        )
        assert (target, colocated) == (EXECUTOR_NAME, False)


class TestPerformInventorySync:
    """Test the top-level sync entrypoint."""

    @pytest.mark.asyncio
    async def test_perform_inventory_sync_invokes_sync_node(
        self, mock_syncer, created_node, mocker
    ):
        """Every inventory node is handed to sync_node (loop fans out to all nodes)."""
        second_node = CreatedNodeFactory.build()
        second_node.id = MOCK_CREATED_NODE_ID + 1
        mocker.patch.object(
            SystemFactsSyncer,
            "get_inventory_nodes",
            new_callable=AsyncMock,
            return_value=[created_node, second_node],
        )
        sync_node = mocker.patch.object(
            SystemFactsSyncer, "sync_node", new_callable=AsyncMock
        )
        await mock_syncer.perform_inventory_sync()
        assert sync_node.await_args_list == [call(created_node), call(second_node)]
