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

"""Define test cases for periodic task routes."""

import json

import pytest
import pytest_asyncio
from fastapi import status
from sqlalchemy_celery_beat import IntervalSchedule
from sqlalchemy_celery_beat.models import Period, PeriodicTask
from sqlmodel.ext.asyncio.session import AsyncSession

from app.tasks.crud import TaskManager
from app.tasks.models import TaskWrite
from tests.app.factories import TaskFactory

CELERY_TASK_NAME = "app.tasks.celery.execute_task_by_name"


@pytest_asyncio.fixture
async def second_periodic_task(celery_beat_session: AsyncSession) -> PeriodicTask:
    """Create a second periodic task for list tests."""
    schedule = IntervalSchedule(every=1, period=Period.HOURS)
    celery_beat_session.add(schedule)
    await celery_beat_session.flush()

    task = PeriodicTask(
        name="second-periodic",
        task=CELERY_TASK_NAME,
        kwargs=json.dumps({"task_name": "other-task", "execution_data": None}),
        enabled=False,
        description="Second periodic task",
        schedule_model=schedule,
    )
    celery_beat_session.add(task)
    await celery_beat_session.commit()
    await celery_beat_session.refresh(task)
    return task


class TestListPeriodicTasks:
    """Test the GET /periodic/ endpoint."""

    def test_list_all_periodic_tasks(self, periodic_test_client, created_periodic_task):
        """Assert listing all periodic tasks returns a list."""
        response = periodic_test_client.get("/periodic/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "test-periodic-task"
        assert data[0]["task"] == "my-backup-task"

    def test_list_periodic_tasks_empty(self, periodic_test_client):
        """Assert listing periodic tasks when none exist returns empty list."""
        response = periodic_test_client.get("/periodic/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_list_periodic_tasks_filter_enabled(
        self,
        periodic_test_client,
        created_periodic_task,
        second_periodic_task,
    ):
        """Assert filtering by enabled returns only enabled tasks."""
        response = periodic_test_client.get("/periodic/", params={"enabled": True})
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["enabled"] is True


class TestRetrievePeriodicTask:
    """Test the GET /periodic/{periodic_task_id} endpoint."""

    def test_retrieve_existing(self, periodic_test_client, created_periodic_task):
        """Assert retrieving an existing periodic task returns it."""
        response = periodic_test_client.get(f"/periodic/{created_periodic_task.id}")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == created_periodic_task.id
        assert data["task"] == "my-backup-task"

    def test_retrieve_nonexistent_returns_404(self, periodic_test_client):
        """Assert retrieving a non-existent periodic task returns 404."""
        response = periodic_test_client.get("/periodic/99999")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestUpdatePeriodicTask:
    """Test the PUT /periodic/{periodic_task_id} endpoint."""

    def test_update_periodic_task(self, periodic_test_client, created_periodic_task):
        """Assert updating a periodic task returns the updated task."""
        update_data = {
            "name": "updated-name",
            "task": "my-backup-task",
            "start_time": None,
            "enabled": False,
            "description": "Updated description",
            "interval": {"every": 30, "period": "minutes"},
        }
        response = periodic_test_client.put(
            f"/periodic/{created_periodic_task.id}",
            json=update_data,
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "updated-name"
        assert data["enabled"] is False
        assert data["description"] == "Updated description"

    @pytest.mark.asyncio
    async def test_update_with_changed_task_name_validates(
        self,
        periodic_test_client,
        created_periodic_task,
        tasks_session,
    ):
        """Assert updating task_name validates via get_executable_task_by_name."""
        await TaskManager.create(
            tasks_session,
            TaskWrite.model_validate(TaskFactory.build(name="new-task-name")),
        )
        update_data = {
            "name": "updated-name",
            "task": "new-task-name",
            "start_time": None,
            "enabled": True,
            "description": "",
            "interval": {"every": 10, "period": "minutes"},
        }
        response = periodic_test_client.put(
            f"/periodic/{created_periodic_task.id}",
            json=update_data,
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["task"] == "new-task-name"


class TestCreatePeriodicTaskChainValidation:
    """Test chain_task_names validation on POST /{task_name}/periodic/."""

    @pytest.mark.asyncio
    async def test_self_chain_returns_400(self, periodic_test_client, tasks_session):
        """Assert creating a periodic task that chains to itself returns 400."""
        await TaskManager.create(
            tasks_session,
            TaskWrite.model_validate(TaskFactory.build(name="my-task")),
        )
        payload = {
            "interval": {"every": 10, "period": "minutes"},
            "execute_request": {"chain_task_names": ["my-task"]},
        }
        response = periodic_test_client.post("/my-task/periodic/", json=payload)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Cycle detected" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_nonexistent_chain_task_returns_404(
        self, periodic_test_client, tasks_session
    ):
        """Assert creating a periodic task with a nonexistent chain task returns 404."""
        await TaskManager.create(
            tasks_session,
            TaskWrite.model_validate(TaskFactory.build(name="my-task")),
        )
        payload = {
            "interval": {"every": 10, "period": "minutes"},
            "execute_request": {"chain_task_names": ["does-not-exist"]},
        }
        response = periodic_test_client.post("/my-task/periodic/", json=payload)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_valid_chain_task_succeeds(self, periodic_test_client, tasks_session):
        """Assert creating a periodic task with a valid chain task succeeds."""
        shared = {"owner": "BACKUPS", "data": {"Constraints": [{"RTarget": "n"}]}}
        await TaskManager.create(
            tasks_session,
            TaskWrite.model_validate(TaskFactory.build(name="task-a", **shared)),
        )
        await TaskManager.create(
            tasks_session,
            TaskWrite.model_validate(TaskFactory.build(name="task-b", **shared)),
        )
        payload = {
            "interval": {"every": 10, "period": "minutes"},
            "execute_request": {"chain_task_names": ["task-b"]},
        }
        response = periodic_test_client.post("/task-a/periodic/", json=payload)
        assert response.status_code == status.HTTP_201_CREATED


class TestDeletePeriodicTask:
    """Test the DELETE /periodic/{periodic_task_id} endpoint."""

    def test_delete_existing(self, periodic_test_client, created_periodic_task):
        """Assert deleting an existing periodic task returns 204."""
        response = periodic_test_client.delete(f"/periodic/{created_periodic_task.id}")
        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_delete_nonexistent_returns_404(self, periodic_test_client):
        """Assert deleting a non-existent periodic task returns 404."""
        response = periodic_test_client.delete("/periodic/99999")
        assert response.status_code == status.HTTP_404_NOT_FOUND
