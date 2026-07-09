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

"""Tests for the ``make_task_dep`` task-by-name dependency factory."""

from typing import Annotated
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends, FastAPI, status
from fastapi.testclient import TestClient

from app.core.requests import RemoteAPI
from app.sep.apps.framework import make_task_dep
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
