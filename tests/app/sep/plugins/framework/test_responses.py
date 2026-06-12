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

"""Tests for the shared JSON-API list-pipeline framework helpers."""

from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel, ConfigDict

from app.core.pagination import PaginatedResponse, Pagination
from app.core.requests import RemoteAPI
from app.sep.plugins.framework import (
    build_default_task_response,
    build_task_list_responses,
)
from app.tasks.models import Task, TaskHistoryStatusEnum, TaskOwner
from tests.app.factories import TaskFactory


class _TaskResponse(BaseModel):
    """Minimal response model exercising the helper and the default builder."""

    model_config = ConfigDict(extra="allow")

    name: str
    status: TaskHistoryStatusEnum | None = None


def _build_response(
    task: Task, *, status: TaskHistoryStatusEnum | None = None
) -> _TaskResponse:
    """Build a minimal response carrying only the name and resolved status."""
    return _TaskResponse(name=task.name, status=status)


def _task(name: str) -> Task:
    """Build a validatable archive task with the given name."""
    return TaskFactory.build(name=name, owner=TaskOwner.ARCHIVER)


def _items(*names: str) -> list[dict]:
    """Return upstream ``items`` dicts that round-trip through ``Task``."""
    return [_task(name).model_dump() for name in names]


def _mock_tasks_api(
    *,
    items: list[dict],
    statuses: dict[str, str | None],
    total: int | None = None,
) -> AsyncMock:
    """Build a ``RemoteAPI`` mock returning ``items`` and batch ``statuses``."""
    payload = {"items": items}
    if total is not None:
        payload["total"] = total
    tasks_api = AsyncMock(spec=RemoteAPI)
    tasks_api.get = AsyncMock(return_value=payload)
    tasks_api.post = AsyncMock(
        side_effect=lambda _path, json: {
            name: statuses.get(name) for name in json["names"]
        }
    )
    return tasks_api


class TestBuildTaskListResponses:
    """Test suite for ``build_task_list_responses``."""

    @pytest.mark.asyncio
    async def test_unpaginated_no_filter_builds_one_response_per_task(self) -> None:
        """Return a ``list`` with the builder called per task with its status."""
        tasks_api = _mock_tasks_api(
            items=_items("task-a", "task-b"),
            statuses={"task-a": "success", "task-b": "failed"},
        )

        result = await build_task_list_responses(
            tasks_api,
            owner=TaskOwner.ARCHIVER.value,
            response_builder=_build_response,
        )

        assert [(r.name, r.status) for r in result] == [
            ("task-a", TaskHistoryStatusEnum.SUCCESS),
            ("task-b", TaskHistoryStatusEnum.FAILED),
        ]

    @pytest.mark.asyncio
    async def test_status_filter_keeps_only_matching_status(self) -> None:
        """Return only items whose resolved status matches ``status_filter``."""
        tasks_api = _mock_tasks_api(
            items=_items("task-a", "task-b"),
            statuses={"task-a": "success", "task-b": "failed"},
        )

        result = await build_task_list_responses(
            tasks_api,
            owner=TaskOwner.ARCHIVER.value,
            response_builder=_build_response,
            status_filter=TaskHistoryStatusEnum.SUCCESS,
        )

        assert [r.name for r in result] == ["task-a"]

    @pytest.mark.asyncio
    async def test_paginated_no_filter_uses_upstream_total(self) -> None:
        """Return a ``PaginatedResponse`` whose total echoes the upstream total."""
        upstream_total = 5
        pagination = Pagination(offset=0, limit=10)
        tasks_api = _mock_tasks_api(
            items=_items("task-a", "task-b"),
            statuses={"task-a": "success", "task-b": "failed"},
            total=upstream_total,
        )

        result = await build_task_list_responses(
            tasks_api,
            owner=TaskOwner.ARCHIVER.value,
            response_builder=_build_response,
            pagination=pagination,
        )

        assert isinstance(result, PaginatedResponse)
        assert result.total == upstream_total
        assert (result.offset, result.limit) == (pagination.offset, pagination.limit)
        assert [r.name for r in result.items] == ["task-a", "task-b"]

    @pytest.mark.asyncio
    async def test_paginated_status_filter_total_is_current_page_count(self) -> None:
        """Set total to the filtered current-page count when a filter is active."""
        pagination = Pagination(offset=0, limit=10)
        tasks_api = _mock_tasks_api(
            items=_items("task-a", "task-b"),
            statuses={"task-a": "success", "task-b": "failed"},
            total=5,
        )

        result = await build_task_list_responses(
            tasks_api,
            owner=TaskOwner.ARCHIVER.value,
            response_builder=_build_response,
            pagination=pagination,
            status_filter=TaskHistoryStatusEnum.SUCCESS,
        )

        assert result.total == 1
        assert [r.name for r in result.items] == ["task-a"]

    @pytest.mark.asyncio
    async def test_task_filter_excludes_from_batch_and_result(self) -> None:
        """Drop ``task_filter`` rejects before the batch-status call and result."""
        tasks_api = _mock_tasks_api(
            items=_items("task-a", "task-b"),
            statuses={"task-a": "success", "task-b": "success"},
        )

        result = await build_task_list_responses(
            tasks_api,
            owner=TaskOwner.ARCHIVER.value,
            response_builder=_build_response,
            task_filter=lambda task: task.name != "task-b",
        )

        assert [r.name for r in result] == ["task-a"]
        tasks_api.post.assert_awaited_once_with(
            "/history/latest", json={"names": ["task-a"]}
        )

    @pytest.mark.asyncio
    async def test_empty_items_returns_empty_list_without_post(self) -> None:
        """Return ``[]`` and issue no batch-status POST when there are no items."""
        tasks_api = _mock_tasks_api(items=[], statuses={})

        result = await build_task_list_responses(
            tasks_api,
            owner=TaskOwner.ARCHIVER.value,
            response_builder=_build_response,
        )

        assert result == []
        tasks_api.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_paginated_missing_total_falls_back_to_len(self) -> None:
        """Fall back to the item count when the paginated response omits total."""
        names = ["task-a", "task-b"]
        pagination = Pagination(offset=0, limit=10)
        tasks_api = _mock_tasks_api(
            items=_items(*names),
            statuses={"task-a": "success", "task-b": "failed"},
        )

        result = await build_task_list_responses(
            tasks_api,
            owner=TaskOwner.ARCHIVER.value,
            response_builder=_build_response,
            pagination=pagination,
        )

        assert result.total == len(names)

    @pytest.mark.asyncio
    async def test_owner_and_pagination_forwarded_in_get_params(self) -> None:
        """Forward owner and the pagination window in the upstream GET params."""
        pagination = Pagination(offset=20, limit=5)
        tasks_api = _mock_tasks_api(
            items=_items("task-a"),
            statuses={"task-a": "success"},
            total=1,
        )

        await build_task_list_responses(
            tasks_api,
            owner=TaskOwner.ARCHIVER.value,
            response_builder=_build_response,
            pagination=pagination,
        )

        tasks_api.get.assert_awaited_once_with(
            "/", params={"owner": TaskOwner.ARCHIVER.value, "offset": 20, "limit": 5}
        )


class TestBuildDefaultTaskResponse:
    """Test suite for ``build_default_task_response``."""

    def test_additive_extras_are_spread_onto_the_response(self) -> None:
        """Add extras as new fields on top of the dumped task payload."""
        task = _task("task-a")

        result = build_default_task_response(
            _TaskResponse,
            task,
            TaskHistoryStatusEnum.SUCCESS,
            extras={"hostname": "host-1"},
        )

        assert result.status == TaskHistoryStatusEnum.SUCCESS
        assert result.hostname == "host-1"

    def test_override_extras_win_over_dumped_value(self) -> None:
        """Let an extra override a field already present in the task dump."""
        task = _task("task-a")
        task.created_by = "user-id-1"

        result = build_default_task_response(
            _TaskResponse,
            task,
            extras={"created_by": "Alice"},
        )

        assert result.created_by == "Alice"

    def test_status_defaults_to_none_when_omitted(self) -> None:
        """Default the status to ``None`` when no status is supplied."""
        task = _task("task-a")

        result = build_default_task_response(_TaskResponse, task)

        assert result.status is None
