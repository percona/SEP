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

"""Define tests for base SEP dependencies."""

from collections import OrderedDict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request
from itsdangerous import BadSignature
from pydantic import ValidationError

from app.core.auth.exceptions import HTTPForbiddenException
from app.core.exceptions import HTTPConflictException, HTTPNotFoundException
from app.models import CasdoorUser
from app.sep.deps import (
    check_for_conflicted_running_tasks,
    ExecutorHostsContext,
    get_base_url,
    get_created_entity,
    get_created_node,
    get_created_schema,
    get_current_admin,
    get_current_user,
    get_executor_hosts,
    get_executor_hosts_context,
    get_inventory_api,
    get_task_by_name,
    get_task_history,
    get_tasks_api,
    get_tasks_context,
    get_tasks_index_context,
    get_username_mapping,
)
from app.sep.exceptions import LoginRedirectException
from app.sep.inventory import CreatedNode, CreatedSchema
from app.sep.models import SyncInventoryEntityTypeEnum
from app.tasks.models import (
    Task,
    TaskHistoryStatusEnum,
    TaskOwner,
)
from tests.app.factories import (
    CasdoorUserFactory,
    CreatedNodeFactory,
    CreatedSchemaFactory,
    CreatedServiceFactory,
    TaskFactory,
)

PENDING_HISTORY_ID = 10
RUNNING_HISTORY_ID = 11
SUCCESS_HISTORY_ID = 12
EXPECTED_NODE_COUNT = 5


def _make_request() -> Request:
    """Build a minimal Request with messages state for testing."""
    scope = {
        "type": "http",
        "headers": [],
        "client": ("127.0.0.1", "80"),
        "path": "/",
        "app": MagicMock(),
        "router": MagicMock(),
    }
    req = Request(scope)
    req.state.messages = OrderedDict()
    return req


class TestGetBaseUrl:
    """Test get_base_url dependency."""

    def test_returns_setting_when_configured(self) -> None:
        """Assert BASE_URL from settings is returned when set."""
        request = _make_request()
        with patch("app.sep.deps.settings") as mock_settings:
            mock_settings.BASE_URL = "https://example.com"
            result = get_base_url(request)
        assert result == "https://example.com"


class TestGetCurrentUser:
    """Test get_current_user dependency."""

    @pytest.mark.asyncio
    async def test_bad_signature_raises_redirect(self) -> None:
        """Assert BadSignature during JWT decode raises LoginRedirectException."""
        request = _make_request()
        with (
            patch(
                "app.sep.deps.get_access_token_from_cookie", return_value="fake-token"
            ),
            patch.object(CasdoorUser, "from_jwt", side_effect=BadSignature("bad")),
            pytest.raises(LoginRedirectException),
        ):
            await get_current_user(request)

    @pytest.mark.asyncio
    async def test_validation_error_raises_redirect(self) -> None:
        """Assert ValidationError during user parsing raises LoginRedirectException."""
        request = _make_request()
        with (
            patch(
                "app.sep.deps.get_access_token_from_cookie", return_value="fake-token"
            ),
            patch.object(
                CasdoorUser,
                "from_jwt",
                side_effect=ValidationError.from_exception_data("CasdoorUser", []),
            ),
            pytest.raises(LoginRedirectException),
        ):
            await get_current_user(request)

    @pytest.mark.asyncio
    async def test_inactive_user_raises_redirect(self) -> None:
        """Assert inactive user raises LoginRedirectException."""
        inactive_user = CasdoorUserFactory.build(is_forbidden=True)
        request = _make_request()
        with (
            patch(
                "app.sep.deps.get_access_token_from_cookie", return_value="fake-token"
            ),
            patch.object(CasdoorUser, "from_jwt", return_value=inactive_user),
            pytest.raises(LoginRedirectException),
        ):
            await get_current_user(request)


class TestGetCurrentAdmin:
    """Test get_current_admin dependency."""

    @pytest.mark.asyncio
    async def test_non_admin_raises_forbidden(self) -> None:
        """Assert non-admin user raises HTTPForbiddenException."""
        regular_user = CasdoorUserFactory.build(is_admin=False)
        with pytest.raises(HTTPForbiddenException):
            await get_current_admin(regular_user)

    @pytest.mark.asyncio
    async def test_admin_returns_user(self) -> None:
        """Assert admin user is returned successfully."""
        admin_user = CasdoorUserFactory.build(is_admin=True)
        result = await get_current_admin(admin_user)
        assert result is admin_user


class TestGetUsernameMapping:
    """Test get_username_mapping dependency."""

    @pytest.mark.asyncio
    async def test_casdoor_failure_returns_empty_dict(self) -> None:
        """Assert Casdoor API failure returns empty dict."""
        with patch("app.sep.deps.settings") as mock_settings:
            mock_settings.CASDOOR.get_users = AsyncMock(
                side_effect=ValueError("connection failed")
            )
            result = await get_username_mapping()
        assert result == {}

    @pytest.mark.asyncio
    async def test_http_exception_returns_empty_dict(self) -> None:
        """Assert HTTPException from Casdoor returns empty dict."""
        with patch("app.sep.deps.settings") as mock_settings:
            mock_settings.CASDOOR.get_users = AsyncMock(
                side_effect=HTTPException(status_code=500, detail="fail")
            )
            result = await get_username_mapping()
        assert result == {}

    @pytest.mark.asyncio
    async def test_key_error_returns_empty_dict(self) -> None:
        """Assert KeyError from malformed response returns empty dict."""
        with patch("app.sep.deps.settings") as mock_settings:
            mock_settings.CASDOOR.get_users = AsyncMock(side_effect=KeyError("missing"))
            result = await get_username_mapping()
        assert result == {}


class TestGetInventoryApi:
    """Test get_inventory_api context manager."""

    @pytest.mark.asyncio
    async def test_yields_authenticated_client(self) -> None:
        """Assert authenticated API client is yielded and cleaned up."""
        mock_client = MagicMock()
        mock_authenticated = MagicMock()
        mock_client.auth.return_value.__enter__ = MagicMock(
            return_value=mock_authenticated
        )
        mock_client.auth.return_value.__exit__ = MagicMock(return_value=False)
        mock_user = CasdoorUserFactory.build()
        mock_user.access_token = "test-token"

        gen = get_inventory_api(mock_client, mock_user)
        result = await gen.__anext__()
        assert result is mock_authenticated
        mock_client.auth.assert_called_once_with("test-token")


class TestGetTasksApi:
    """Test get_tasks_api context manager."""

    @pytest.mark.asyncio
    async def test_yields_authenticated_client(self) -> None:
        """Assert authenticated API client is yielded and cleaned up."""
        mock_client = MagicMock()
        mock_authenticated = MagicMock()
        mock_client.auth.return_value.__enter__ = MagicMock(
            return_value=mock_authenticated
        )
        mock_client.auth.return_value.__exit__ = MagicMock(return_value=False)
        mock_user = CasdoorUserFactory.build()
        mock_user.access_token = "test-token"

        gen = get_tasks_api(mock_client, mock_user)
        result = await gen.__anext__()
        assert result is mock_authenticated
        mock_client.auth.assert_called_once_with("test-token")


class TestGetExecutorHosts:
    """Test get_executor_hosts dependency."""

    @pytest.mark.asyncio
    async def test_api_failure_returns_empty_dict(self) -> None:
        """Assert HTTPException from API returns empty dict and logs error."""
        request = _make_request()
        mock_api = AsyncMock()
        mock_api.get.side_effect = HTTPException(
            status_code=500, detail="Service unavailable"
        )
        result = await get_executor_hosts(request, mock_api)
        assert result == {}


class TestGetCreatedEntity:
    """Test get_created_entity dependency."""

    @pytest.mark.asyncio
    async def test_filter_mismatch_raises_value_error(self) -> None:
        """Assert mismatched filter raises ValueError."""
        node = CreatedNodeFactory.build()
        mock_api = AsyncMock()
        mock_api.get.return_value = node.model_dump()

        with pytest.raises(ValueError, match="address is not valid"):
            await get_created_entity(
                mock_api,
                SyncInventoryEntityTypeEnum.NODE,
                node.id,
                address="wrong-address",
            )


class TestGetCreatedNode:
    """Test get_created_node dependency."""

    @pytest.mark.asyncio
    async def test_delegates_to_get_created_entity(self) -> None:
        """Assert get_created_node fetches node via the correct entity path."""
        node = CreatedNodeFactory.build()
        mock_api = AsyncMock()
        mock_api.get.return_value = node.model_dump()

        result = await get_created_node(mock_api, node.id)
        assert isinstance(result, CreatedNode)
        mock_api.get.assert_called_once_with(f"/{node.id}")


class TestGetCreatedSchema:
    """Test get_created_schema dependency."""

    @pytest.mark.asyncio
    async def test_loads_node_when_missing(self) -> None:
        """Assert node is fetched when schema has node_id but no node object."""
        node = CreatedNodeFactory.build()
        service = CreatedServiceFactory.build(node_id=node.id, node=None)
        schema = CreatedSchemaFactory.build(service=service)
        mock_api = AsyncMock()

        schema_data = schema.model_dump()
        schema_data["service"]["node"] = None
        schema_data["service"]["node_id"] = node.id

        mock_api.get.side_effect = [
            schema_data,
            node.model_dump(),
        ]

        result = await get_created_schema(mock_api, schema.id)
        assert isinstance(result, CreatedSchema)
        assert result.service.node is not None
        assert result.service.node.id == node.id


class TestGetTaskByName:
    """Test get_task_by_name dependency."""

    @pytest.mark.asyncio
    async def test_validation_error_raises_not_found(self) -> None:
        """Assert ValidationError during model validation raises 404."""
        mock_api = AsyncMock()
        mock_api.get.return_value = {"invalid": "data"}

        with pytest.raises(HTTPNotFoundException):
            await get_task_by_name(mock_api, "test-task")

    @pytest.mark.asyncio
    async def test_owner_mismatch_raises_not_found(self) -> None:
        """Assert wrong owner raises 404."""
        task = TaskFactory.build(owner=TaskOwner.BACKUPS)
        mock_api = AsyncMock()
        mock_api.get.return_value = task.model_dump(mode="json")

        with pytest.raises(HTTPNotFoundException):
            await get_task_by_name(mock_api, task.name, owner=TaskOwner.ALTERS)

    @pytest.mark.asyncio
    async def test_matching_owner_returns_task(self) -> None:
        """Assert correct owner returns the task."""
        task = TaskFactory.build(owner=TaskOwner.BACKUPS)
        mock_api = AsyncMock()
        mock_api.get.return_value = task.model_dump(mode="json")

        result = await get_task_by_name(mock_api, task.name, owner=TaskOwner.BACKUPS)
        assert isinstance(result, Task)
        assert result.name == task.name


class TestGetTaskHistory:
    """Test get_task_history dependency."""

    @pytest.mark.asyncio
    async def test_validation_error_raises_not_found(self) -> None:
        """Assert ValidationError during model validation raises 404."""
        mock_api = AsyncMock()
        mock_api.get.return_value = {"invalid": "data"}

        with pytest.raises(HTTPNotFoundException):
            await get_task_history(mock_api, 1)

    @pytest.mark.asyncio
    async def test_owner_mismatch_raises_not_found(self) -> None:
        """Assert wrong owner raises 404."""
        task = TaskFactory.build(owner=TaskOwner.BACKUPS)
        history_data = {
            "id": 1,
            "execution_request": {"tracking": {}},
            "status": TaskHistoryStatusEnum.SUCCESS,
            "started_at": None,
            "finished_at": None,
            "anonymize_mask": None,
            "task": task.model_dump(mode="json"),
            "executed_by": None,
        }
        mock_api = AsyncMock()
        mock_api.get.return_value = history_data

        with pytest.raises(HTTPNotFoundException):
            await get_task_history(mock_api, 1, owner=TaskOwner.ALTERS)


class TestGetTasksContext:
    """Test get_tasks_context dependency."""

    @pytest.mark.asyncio
    async def test_basic_context(
        self, created_service, created_schema, mock_remote_api
    ) -> None:
        """Assert template context is assembled for task-dependent plugins."""
        task_data = {
            "name": "fakeTask",
            "id": 1,
            "created_by": None,
            "last_updated_by": None,
        }
        extra_data = {"success": True, "extra": "extra_data"}
        mock_remote_api.get = AsyncMock(
            side_effect=[
                [created_service.model_dump()],
                created_schema.model_dump(),
                [task_data],
                [],
                [],
            ]
        )

        def get_task_info(_task):
            return extra_data

        executor_hosts_ctx = ExecutorHostsContext(
            hosts={"host1": "address1", "host2": "address2"},
            display_names={"address1": "DB Primary", "address2": "DB Replica"},
        )
        context = await get_tasks_context(
            mock_remote_api,
            mock_remote_api,
            get_task_info,
            executor_hosts_ctx,
        )
        assert context["services"][0]["id"] == created_service.id
        assert context["executor_hosts"] == [
            {"value": "host1", "label": "DB Primary"},
            {"value": "host2", "label": "DB Replica"},
        ]
        assert len(context["tasks"]) == 1
        task = context["tasks"][0]
        assert task == task_data | extra_data

    @pytest.mark.asyncio
    async def test_status_branches(self) -> None:
        """Assert PENDING, RUNNING, and completed histories are categorized correctly."""
        mock_api = AsyncMock()
        task_data = {
            "name": "test-task",
            "id": 1,
            "created_by": None,
            "last_updated_by": None,
        }
        pending_hist = {
            "status": TaskHistoryStatusEnum.PENDING,
            "id": PENDING_HISTORY_ID,
        }
        running_hist = {
            "status": TaskHistoryStatusEnum.RUNNING,
            "id": RUNNING_HISTORY_ID,
        }
        success_hist = {
            "status": TaskHistoryStatusEnum.SUCCESS,
            "id": SUCCESS_HISTORY_ID,
        }

        mock_api.get = AsyncMock(
            side_effect=[
                [],
                [task_data],
                [pending_hist, running_hist, success_hist],
                [],
            ]
        )

        executor_hosts_ctx = ExecutorHostsContext(hosts={}, display_names={})
        context = await get_tasks_context(
            mock_api,
            mock_api,
            lambda _: {},
            executor_hosts_ctx,
        )
        assert len(context["pending_tasks"]) == 1
        assert context["pending_tasks"][0]["id"] == PENDING_HISTORY_ID
        assert len(context["running_tasks"]) == 1
        assert context["running_tasks"][0]["id"] == RUNNING_HISTORY_ID
        assert len(context["history_tasks"]) == 1
        assert context["history_tasks"][0]["id"] == SUCCESS_HISTORY_ID


class TestGetTasksIndexContext:
    """Test get_tasks_index_context dependency."""

    @pytest.mark.asyncio
    async def test_assembles_context(self) -> None:
        """Assert all API calls are made and context dict is structured correctly."""
        mock_inv_api = AsyncMock()
        mock_tasks_api = AsyncMock()
        mock_tasks_api.get = AsyncMock(
            side_effect=[
                [{"id": 1, "status": "running"}],
                [{"id": 2, "status": "pending"}],
                [{"task": "backup-task", "enabled": True}],
                [{"name": "backup-task", "owner": TaskOwner.BACKUPS}],
            ]
        )
        mock_inv_api.get = AsyncMock(
            return_value={"nodes": EXPECTED_NODE_COUNT, "services": 3}
        )

        default_context = {"user": "test"}
        executor_hosts_ctx = ExecutorHostsContext(
            hosts={"host1": "addr1"}, display_names={}
        )

        with patch("app.sep.deps.sep_settings") as mock_sep:
            mock_sep.PLUGINS = []
            context = await get_tasks_index_context(
                mock_inv_api, mock_tasks_api, default_context, executor_hosts_ctx
            )

        assert "running_tasks" in context
        assert "pending_tasks" in context
        assert "periodic_tasks" in context
        assert "is_task_manager_enabled" in context
        assert context["is_task_manager_enabled"] is False
        assert context["nodes"] == EXPECTED_NODE_COUNT
        assert context["periodic_tasks"][0]["owner"] == TaskOwner.BACKUPS

    @pytest.mark.asyncio
    async def test_task_manager_enabled(self) -> None:
        """Assert is_task_manager_enabled is True when Task Manager plugin has sidebar."""
        mock_inv_api = AsyncMock()
        mock_tasks_api = AsyncMock()
        mock_tasks_api.get = AsyncMock(
            side_effect=[
                [],
                [],
                [],
                [],
            ]
        )
        mock_inv_api.get = AsyncMock(return_value={})

        mock_plugin = MagicMock()
        mock_plugin.name = "Task Manager"
        mock_plugin.sidebar = True

        executor_hosts_ctx = ExecutorHostsContext(hosts={}, display_names={})
        with patch("app.sep.deps.sep_settings") as mock_sep:
            mock_sep.PLUGINS = [mock_plugin]
            context = await get_tasks_index_context(
                mock_inv_api, mock_tasks_api, {}, executor_hosts_ctx
            )

        assert context["is_task_manager_enabled"] is True


class TestCheckForConflictedRunningTasks:
    """Test check_for_conflicted_running_tasks dependency."""

    @pytest.mark.asyncio
    async def test_conflict_raises_409(self) -> None:
        """Assert running task exists raises HTTPConflictException."""
        mock_api = AsyncMock()
        mock_api.get = AsyncMock(
            side_effect=[
                [{"id": 1, "status": "running"}],
                [],
            ]
        )
        with pytest.raises(HTTPConflictException):
            await check_for_conflicted_running_tasks("test-task", mock_api)

    @pytest.mark.asyncio
    async def test_pending_conflict_raises_409(self) -> None:
        """Assert pending task exists raises HTTPConflictException."""
        mock_api = AsyncMock()
        mock_api.get = AsyncMock(
            side_effect=[
                [],
                [{"id": 2, "status": "pending"}],
            ]
        )
        with pytest.raises(HTTPConflictException):
            await check_for_conflicted_running_tasks("test-task", mock_api)

    @pytest.mark.asyncio
    async def test_no_conflict_passes(self) -> None:
        """Assert no running or pending tasks does not raise."""
        mock_api = AsyncMock()
        mock_api.get = AsyncMock(
            side_effect=[
                [],
                [],
            ]
        )
        await check_for_conflicted_running_tasks("test-task", mock_api)


class TestExecutorHostsContext:
    """Test ExecutorHostsContext class."""

    def test_display_name_returns_inventory_name_when_match_exists(self) -> None:
        """Assert inventory name is returned when address matches."""
        hosts = {"nomad-node-1": "10.0.0.1", "nomad-node-2": "10.0.0.2"}
        display_names = {"10.0.0.1": "db-primary", "10.0.0.2": "db-replica"}
        ctx = ExecutorHostsContext(hosts=hosts, display_names=display_names)
        assert ctx.display_name("nomad-node-1") == "db-primary"

    def test_display_name_falls_back_to_nomad_name(self) -> None:
        """Assert nomad name is returned when no inventory match exists."""
        hosts = {"nomad-node-1": "10.0.0.1"}
        display_names = {}
        ctx = ExecutorHostsContext(hosts=hosts, display_names=display_names)
        assert ctx.display_name("nomad-node-1") == "nomad-node-1"

    def test_display_name_falls_back_for_unknown_host(self) -> None:
        """Assert unknown host returns itself as display name."""
        ctx = ExecutorHostsContext(hosts={}, display_names={})
        assert ctx.display_name("unknown-host") == "unknown-host"

    def test_as_template_list_returns_sorted_dicts(self) -> None:
        """Assert template list is sorted by value with value/label keys."""
        hosts = {"beta-node": "10.0.0.2", "alpha-node": "10.0.0.1"}
        display_names = {"10.0.0.1": "Alpha DB", "10.0.0.2": "Beta DB"}
        ctx = ExecutorHostsContext(hosts=hosts, display_names=display_names)
        result = ctx.as_template_list()
        assert result == [
            {"value": "alpha-node", "label": "Alpha DB"},
            {"value": "beta-node", "label": "Beta DB"},
        ]

    def test_as_template_list_uses_nomad_name_as_fallback_label(self) -> None:
        """Assert nomad name is used as label when no inventory match."""
        hosts = {"nomad-node": "10.0.0.1"}
        display_names = {}
        ctx = ExecutorHostsContext(hosts=hosts, display_names=display_names)
        result = ctx.as_template_list()
        assert result == [{"value": "nomad-node", "label": "nomad-node"}]

    def test_as_form_hosts_returns_frozenset_of_tuples(self) -> None:
        """Assert form hosts returns frozenset of (value, label) tuples."""
        hosts = {"nomad-node": "10.0.0.1"}
        display_names = {"10.0.0.1": "My DB"}
        ctx = ExecutorHostsContext(hosts=hosts, display_names=display_names)
        result = ctx.as_form_hosts()
        assert result == frozenset({("nomad-node", "My DB")})

    def test_with_host_adds_new_host(self) -> None:
        """Assert with_host returns new context with the additional host."""
        hosts = {"nomad-node": "10.0.0.1"}
        display_names = {"10.0.0.1": "My DB"}
        ctx = ExecutorHostsContext(hosts=hosts, display_names=display_names)
        new_ctx = ctx.with_host("extra-host")
        result = new_ctx.as_template_list()
        values = [item["value"] for item in result]
        assert "extra-host" in values
        assert "nomad-node" in values

    def test_with_host_returns_same_when_host_exists(self) -> None:
        """Assert with_host returns same context when host already present."""
        hosts = {"nomad-node": "10.0.0.1"}
        ctx = ExecutorHostsContext(hosts=hosts, display_names={})
        new_ctx = ctx.with_host("nomad-node")
        assert new_ctx is ctx

    def test_hosts_property_returns_raw_dict(self) -> None:
        """Assert hosts property returns the raw hosts dictionary."""
        hosts = {"node-1": "10.0.0.1"}
        ctx = ExecutorHostsContext(hosts=hosts, display_names={})
        assert ctx.hosts == hosts


class TestGetExecutorHostsContext:
    """Test get_executor_hosts_context dependency."""

    @pytest.mark.asyncio
    async def test_returns_enriched_context_when_inventory_succeeds(self) -> None:
        """Assert inventory node names are used as display names."""
        executor_hosts = {"nomad-1": "10.0.0.1", "nomad-2": "10.0.0.2"}
        inventory_nodes = [
            {"name": "db-primary", "address": "10.0.0.1"},
            {"name": "db-replica", "address": "10.0.0.2"},
        ]
        mock_inventory_api = AsyncMock()
        mock_inventory_api.get = AsyncMock(return_value=inventory_nodes)

        ctx = await get_executor_hosts_context(executor_hosts, mock_inventory_api)
        assert ctx.display_name("nomad-1") == "db-primary"
        assert ctx.display_name("nomad-2") == "db-replica"
        mock_inventory_api.get.assert_called_once_with("/nodes/")

    @pytest.mark.asyncio
    async def test_returns_fallback_when_inventory_raises(self) -> None:
        """Assert fallback to nomad names when inventory API fails."""
        executor_hosts = {"nomad-1": "10.0.0.1"}
        mock_inventory_api = AsyncMock()
        mock_inventory_api.get = AsyncMock(
            side_effect=HTTPException(status_code=500, detail="unavailable")
        )

        ctx = await get_executor_hosts_context(executor_hosts, mock_inventory_api)
        assert ctx.display_name("nomad-1") == "nomad-1"
        assert ctx.hosts == executor_hosts

    @pytest.mark.asyncio
    async def test_matches_by_address(self) -> None:
        """Assert matching is done by address, not by node name."""
        executor_hosts = {"nomad-1": "10.0.0.1", "nomad-2": "10.0.0.2"}
        inventory_nodes = [
            {"name": "db-primary", "address": "10.0.0.1"},
        ]
        mock_inventory_api = AsyncMock()
        mock_inventory_api.get = AsyncMock(return_value=inventory_nodes)

        ctx = await get_executor_hosts_context(executor_hosts, mock_inventory_api)
        assert ctx.display_name("nomad-1") == "db-primary"
        assert ctx.display_name("nomad-2") == "nomad-2"
