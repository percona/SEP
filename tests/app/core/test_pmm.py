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

"""Tests for PMM annotation helpers."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from app.core.config import PMMSettings
from app.core.pmm import annotate_task_event, create_pmm_annotation
from app.core.requests.remote_api import RemoteAPI
from app.tasks.models import TaskExecutionRequest, TaskHistory, TaskHistoryStatusEnum


@pytest.fixture
def pmm_settings_enabled():
    """Return a mock PMMSettings with annotations enabled."""
    pmm = MagicMock(spec=PMMSettings)
    pmm.annotations_enabled = True
    pmm.endpoint = "https://pmm.example.com"
    pmm.api_key = SecretStr("test-api-key")
    pmm.verify_ssl = True
    pmm.annotations_timeout = 5
    return pmm


@pytest.fixture
def mock_remote_api():
    """Return a mock RemoteAPI with a synchronous auth context manager."""
    api = MagicMock(spec=RemoteAPI)
    api.post = AsyncMock(return_value={})
    api.auth.return_value.__enter__ = MagicMock(return_value=api)
    api.auth.return_value.__exit__ = MagicMock(return_value=False)
    return api


@pytest.fixture
def queue_item_factory():
    """Return a factory for creating mock TaskHistory objects."""

    def _make(
        task="backup_data",
        target="node-1",
        status=TaskHistoryStatusEnum.RUNNING,
        meta=None,
    ):
        queue_item = MagicMock(spec=TaskHistory)
        queue_item.execution_request = TaskExecutionRequest(
            task=task,
            target=target,
            meta=meta if meta is not None else {},
        )
        queue_item.status = status
        return queue_item

    return _make


class TestCreatePmmAnnotation:
    """Test ``create_pmm_annotation()``."""

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self, pmm_settings_enabled):
        """Assert no HTTP call is made when annotations are disabled."""
        pmm_settings_enabled.annotations_enabled = False

        with patch("app.core.pmm.settings") as mock_settings:
            mock_settings.PMM = pmm_settings_enabled
            mock_settings.get_remote_api = AsyncMock()

            await create_pmm_annotation(
                text="SEP backup - STARTED",
                node_name="node-1",
            )

            mock_settings.get_remote_api.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_when_no_endpoint(self, pmm_settings_enabled):
        """Assert no HTTP call is made when endpoint is not configured."""
        pmm_settings_enabled.endpoint = None

        with patch("app.core.pmm.settings") as mock_settings:
            mock_settings.PMM = pmm_settings_enabled
            mock_settings.get_remote_api = AsyncMock()

            await create_pmm_annotation(
                text="SEP backup - STARTED",
                node_name="node-1",
            )

            mock_settings.get_remote_api.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_when_no_api_key(self, pmm_settings_enabled):
        """Assert no HTTP call is made when api_key is not configured."""
        pmm_settings_enabled.api_key = None

        with patch("app.core.pmm.settings") as mock_settings:
            mock_settings.PMM = pmm_settings_enabled
            mock_settings.get_remote_api = AsyncMock()

            await create_pmm_annotation(
                text="SEP backup - STARTED",
                node_name="node-1",
            )

            mock_settings.get_remote_api.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_creates_annotation(self, pmm_settings_enabled, mock_remote_api):
        """Assert annotation POST is made with correct payload."""
        with patch("app.core.pmm.settings") as mock_settings:
            mock_settings.PMM = pmm_settings_enabled
            mock_settings.get_remote_api = AsyncMock(return_value=mock_remote_api)

            await create_pmm_annotation(
                text="SEP backup_data - STARTED",
                node_name="node-1",
                tags=["sep", "backup_data", "started"],
                service_names=["mysql-svc"],
            )

        mock_remote_api.auth.assert_called_once_with("test-api-key")
        mock_remote_api.post.assert_awaited_once_with(
            "/v1/management/annotations",
            json={
                "text": "SEP backup_data - STARTED",
                "tags": ["sep", "backup_data", "started"],
                "node_name": "node-1",
                "service_names": ["mysql-svc"],
            },
        )

    @pytest.mark.asyncio
    async def test_defaults_tags_and_service_names_to_empty(
        self, pmm_settings_enabled, mock_remote_api
    ):
        """Assert tags and service_names default to empty lists."""
        with patch("app.core.pmm.settings") as mock_settings:
            mock_settings.PMM = pmm_settings_enabled
            mock_settings.get_remote_api = AsyncMock(return_value=mock_remote_api)

            await create_pmm_annotation(
                text="SEP test - STARTED",
                node_name="node-1",
            )

        mock_remote_api.post.assert_awaited_once_with(
            "/v1/management/annotations",
            json={
                "text": "SEP test - STARTED",
                "tags": [],
                "node_name": "node-1",
                "service_names": [],
            },
        )

    @pytest.mark.asyncio
    async def test_does_not_propagate_post_exception(
        self, pmm_settings_enabled, mock_remote_api
    ):
        """Assert exceptions from the POST are logged but not raised."""
        mock_remote_api.post.side_effect = Exception("PMM unreachable")

        with patch("app.core.pmm.settings") as mock_settings:
            mock_settings.PMM = pmm_settings_enabled
            mock_settings.get_remote_api = AsyncMock(return_value=mock_remote_api)

            await create_pmm_annotation(
                text="SEP backup - STARTED",
                node_name="node-1",
            )

    @pytest.mark.asyncio
    async def test_timeout_does_not_propagate(
        self, pmm_settings_enabled, mock_remote_api
    ):
        """Assert asyncio.TimeoutError from slow PMM does not propagate."""

        async def slow_post(*args, **kwargs):
            await asyncio.sleep(10)

        mock_remote_api.post = slow_post

        with (
            patch("app.core.pmm.settings") as mock_settings,
        ):
            mock_settings.PMM = pmm_settings_enabled
            mock_settings.PMM.annotations_timeout = 0.01
            mock_settings.get_remote_api = AsyncMock(return_value=mock_remote_api)

            await create_pmm_annotation(
                text="SEP backup - STARTED",
                node_name="node-1",
            )


class TestAnnotateTaskEvent:
    """Test ``annotate_task_event()``."""

    @pytest.mark.asyncio
    async def test_annotation_text_format(self, queue_item_factory):
        """Assert annotation text follows 'SEP {task} - {event}' format."""
        queue_item = queue_item_factory(task="backup_data", target="node-1")

        with patch(
            "app.core.pmm.create_pmm_annotation", new_callable=AsyncMock
        ) as mock_create:
            await annotate_task_event(queue_item, "STARTED")

        mock_create.assert_awaited_once_with(
            text="SEP backup_data - STARTED",
            node_name="node-1",
            tags=["sep", "backup_data", "started"],
            service_names=[],
        )

    @pytest.mark.asyncio
    async def test_reads_service_names_list_from_meta(self, queue_item_factory):
        """Assert ``_service_names`` list is passed through from meta."""
        queue_item = queue_item_factory(meta={"_service_names": ["svc1", "svc2"]})

        with patch(
            "app.core.pmm.create_pmm_annotation", new_callable=AsyncMock
        ) as mock_create:
            await annotate_task_event(queue_item, "COMPLETED")

        mock_create.assert_awaited_once()
        call_kwargs = mock_create.await_args.kwargs
        assert call_kwargs["service_names"] == ["svc1", "svc2"]

    @pytest.mark.asyncio
    async def test_reads_single_service_name_from_meta(self, queue_item_factory):
        """Assert ``_service_name`` string is wrapped in a list."""
        queue_item = queue_item_factory(meta={"_service_name": "mysql-svc"})

        with patch(
            "app.core.pmm.create_pmm_annotation", new_callable=AsyncMock
        ) as mock_create:
            await annotate_task_event(queue_item, "FAILED")

        mock_create.assert_awaited_once()
        call_kwargs = mock_create.await_args.kwargs
        assert call_kwargs["service_names"] == ["mysql-svc"]

    @pytest.mark.asyncio
    async def test_empty_service_names_when_no_meta_keys(self, queue_item_factory):
        """Assert empty service_names when meta has no service keys."""
        queue_item = queue_item_factory(meta={})

        with patch(
            "app.core.pmm.create_pmm_annotation", new_callable=AsyncMock
        ) as mock_create:
            await annotate_task_event(queue_item, "STARTED")

        mock_create.assert_awaited_once()
        call_kwargs = mock_create.await_args.kwargs
        assert call_kwargs["service_names"] == []

    @pytest.mark.asyncio
    async def test_service_names_list_takes_precedence_over_single(
        self, queue_item_factory
    ):
        """Assert ``_service_names`` list takes precedence over ``_service_name``."""
        queue_item = queue_item_factory(
            meta={"_service_names": ["svc-a", "svc-b"], "_service_name": "ignored-svc"}
        )

        with patch(
            "app.core.pmm.create_pmm_annotation", new_callable=AsyncMock
        ) as mock_create:
            await annotate_task_event(queue_item, "STARTED")

        mock_create.assert_awaited_once()
        call_kwargs = mock_create.await_args.kwargs
        assert call_kwargs["service_names"] == ["svc-a", "svc-b"]

    @pytest.mark.asyncio
    async def test_handles_none_meta(self, queue_item_factory):
        """Assert ``None`` meta falls back to empty dict."""
        queue_item = queue_item_factory(meta=None)

        with patch(
            "app.core.pmm.create_pmm_annotation", new_callable=AsyncMock
        ) as mock_create:
            await annotate_task_event(queue_item, "STARTED")

        mock_create.assert_awaited_once()
        call_kwargs = mock_create.await_args.kwargs
        assert call_kwargs["service_names"] == []
