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

"""Tests for framework dependency factories in ``deps``."""

from typing import Annotated
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends, FastAPI, status
from fastapi.testclient import TestClient

from app.core.requests import RemoteAPI
from app.sep.apps.framework import make_parent_resolver, make_task_dep
from app.sep.deps import get_tasks_api
from app.tasks.models import Task
from tests.app.factories import TaskFactory


class TestMakeTaskDep:
    """Test suite for ``make_task_dep``."""

    @pytest.mark.asyncio
    async def test_delegates_to_get_task_by_name_with_owner(self, mocker) -> None:
        """Invoke ``get_task_by_name`` with the bound owner and return its task."""
        task = TaskFactory.build(name="task-1", owner="ARCHIVER")
        get_task_by_name = mocker.patch(
            "app.sep.apps.framework.deps.get_task_by_name",
            new=AsyncMock(return_value=task),
        )
        tasks_api = AsyncMock(spec=RemoteAPI)
        dep = make_task_dep("ARCHIVER")

        result = await dep("task-1", tasks_api)

        assert result is task
        get_task_by_name.assert_awaited_once_with(tasks_api, "task-1", "ARCHIVER")

    def test_distinct_owners_produce_distinct_callables(self) -> None:
        """Build a distinct callable identity per owner for cache/override scoping."""
        archiver_dep = make_task_dep("ARCHIVER")
        checksums_dep = make_task_dep("CHECKSUMS")

        assert archiver_dep is not checksums_dep

    def test_built_callable_resolves_as_fastapi_dependency(self, mocker) -> None:
        """Resolve a route ``Depends(make_task_dep(...))`` through the FastAPI stack."""
        task = TaskFactory.build(name="task-1", owner="ARCHIVER")
        mocker.patch(
            "app.sep.apps.framework.deps.get_task_by_name",
            new=AsyncMock(return_value=task),
        )
        dep = make_task_dep("ARCHIVER")
        app = FastAPI()

        @app.get("/tasks/{task_name}")
        async def _route(resolved: Annotated[Task, Depends(dep)]) -> dict[str, str]:
            return {"name": resolved.name}

        app.dependency_overrides[get_tasks_api] = lambda: AsyncMock(spec=RemoteAPI)
        client = TestClient(app)

        response = client.get("/tasks/task-1")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"name": "task-1"}


class TestMakeParentResolver:
    """Test suite for ``make_parent_resolver``."""

    @pytest.mark.asyncio
    async def test_parent_present_refetches_parent(self) -> None:
        """Follow ``data["parent"]`` and re-fetch the parent via ``get_task``."""
        satellite = TaskFactory.build(
            name="child-1",
            owner="ARCHIVER",
            data={"parent": "parent-1"},
        )
        parent = TaskFactory.build(name="parent-1", owner="ARCHIVER")
        get_task = AsyncMock(side_effect=[satellite, parent])
        tasks_api = AsyncMock(spec=RemoteAPI)
        resolve = make_parent_resolver(get_task)

        result = await resolve("child-1", tasks_api)

        assert result is parent
        assert get_task.await_args_list[0].args == ("child-1", tasks_api)
        assert get_task.await_args_list[1].args == ("parent-1", tasks_api)

    @pytest.mark.asyncio
    async def test_parent_absent_returns_original(self) -> None:
        """Return the fetched task unchanged when no parent link is present."""
        task = TaskFactory.build(name="parent-1", owner="ARCHIVER", data={})
        get_task = AsyncMock(return_value=task)
        tasks_api = AsyncMock(spec=RemoteAPI)
        resolve = make_parent_resolver(get_task)

        result = await resolve("parent-1", tasks_api)

        assert result is task
        get_task.assert_awaited_once_with("parent-1", tasks_api)

    @pytest.mark.asyncio
    async def test_parent_name_is_coerced_with_str(self) -> None:
        """Coerce the followed parent name with ``str(...)`` before re-fetching."""
        satellite = TaskFactory.build(
            name="child-1",
            owner="ARCHIVER",
            data={"parent": 42},
        )
        parent = TaskFactory.build(name="42", owner="ARCHIVER")
        get_task = AsyncMock(side_effect=[satellite, parent])
        tasks_api = AsyncMock(spec=RemoteAPI)
        resolve = make_parent_resolver(get_task)

        result = await resolve("child-1", tasks_api)

        assert result is parent
        assert get_task.await_args_list[1].args == ("42", tasks_api)
