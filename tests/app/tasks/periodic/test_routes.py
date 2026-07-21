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
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import status
from sqlalchemy_celery_beat import IntervalSchedule
from sqlalchemy_celery_beat.models import Period, PeriodicTask
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.utils.date_time import utc_now
from app.tasks.crud import TaskHistoryManager, TaskManager
from app.tasks.models import (
    SYSTEM_USER,
    TaskHistory,
    TaskHistoryStatusEnum,
    TaskWrite,
)
from tests.app.factories import TaskFactory

CELERY_TASK_NAME = "app.tasks.celery.execute_task_by_name"


async def _add_periodic_task(
    celery_beat_session: AsyncSession,
    *,
    name: str,
    task_name: str,
    enabled: bool = True,
    last_run_at=None,
) -> PeriodicTask:
    """Create and persist a periodic task bound to ``task_name``."""
    schedule = IntervalSchedule(every=10, period=Period.MINUTES)
    celery_beat_session.add(schedule)
    await celery_beat_session.flush()

    task = PeriodicTask(
        name=name,
        task=CELERY_TASK_NAME,
        kwargs=json.dumps({"task_name": task_name, "execution_data": None}),
        enabled=enabled,
        last_run_at=last_run_at,
        schedule_model=schedule,
    )
    celery_beat_session.add(task)
    await celery_beat_session.commit()
    await celery_beat_session.refresh(task)
    return task


async def _add_history(
    tasks_session: AsyncSession,
    *,
    task_name: str,
    task_status: TaskHistoryStatusEnum,
    executed_by: str | None = SYSTEM_USER,
) -> None:
    """Persist a task plus one history row for ``task_name`` in the tasks DB."""
    task = await TaskManager.create(
        tasks_session, TaskWrite.model_validate(TaskFactory.build(name=task_name))
    )
    history = TaskHistory(
        task_id=task.id,
        status=task_status,
        executed_by=executed_by,
        execution_request={
            "task": task_name,
            "target": "localhost",
            "meta": {},
            "tracking": {"allocation_id": None, "evaluation_id": None},
        },
    )
    await TaskHistoryManager.save(tasks_session, history)


async def _add_history_row(
    tasks_session: AsyncSession,
    task,
    *,
    task_status: TaskHistoryStatusEnum,
    created_at: datetime,
    executed_by: str | None = SYSTEM_USER,
) -> None:
    """Persist one history row for an existing task at an explicit ``created_at``."""
    history = TaskHistory(
        task_id=task.id,
        status=task_status,
        created_at=created_at,
        executed_by=executed_by,
        execution_request={
            "task": task.name,
            "target": "localhost",
            "meta": {},
            "tracking": {"allocation_id": None, "evaluation_id": None},
        },
    )
    await TaskHistoryManager.save(tasks_session, history)


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


class TestPeriodicTaskLastRunStatus:
    """Test last-run-status population on the periodic-task list/retrieve routes."""

    @pytest_asyncio.fixture
    async def seeded_matrix(
        self,
        celery_beat_session: AsyncSession,
        tasks_session: AsyncSession,
    ) -> None:
        """Seed one periodic task per acceptance-criteria scenario."""
        ran_at = utc_now()

        # Never run: a system history row exists, but last_run_at is None.
        await _add_periodic_task(
            celery_beat_session,
            name="never-run",
            task_name="never-run-task",
            last_run_at=None,
        )
        await _add_history(
            tasks_session,
            task_name="never-run-task",
            task_status=TaskHistoryStatusEnum.SUCCESS,
        )

        await _add_periodic_task(
            celery_beat_session,
            name="succeeded",
            task_name="succeeded-task",
            last_run_at=ran_at,
        )
        await _add_history(
            tasks_session,
            task_name="succeeded-task",
            task_status=TaskHistoryStatusEnum.SUCCESS,
        )

        await _add_periodic_task(
            celery_beat_session,
            name="failed",
            task_name="failed-task",
            last_run_at=ran_at,
        )
        await _add_history(
            tasks_session,
            task_name="failed-task",
            task_status=TaskHistoryStatusEnum.FAILED,
        )

        await _add_periodic_task(
            celery_beat_session,
            name="running",
            task_name="running-task",
            last_run_at=ran_at,
        )
        await _add_history(
            tasks_session,
            task_name="running-task",
            task_status=TaskHistoryStatusEnum.RUNNING,
        )

        # Manual-only: history exists but was not system-executed.
        await _add_periodic_task(
            celery_beat_session,
            name="manual-only",
            task_name="manual-task",
            last_run_at=ran_at,
        )
        await _add_history(
            tasks_session,
            task_name="manual-task",
            task_status=TaskHistoryStatusEnum.SUCCESS,
            executed_by="test-user",
        )

        # No history at all, despite a recorded last_run_at.
        await _add_periodic_task(
            celery_beat_session,
            name="no-history",
            task_name="no-history-task",
            last_run_at=ran_at,
        )

    def test_list_reports_last_run_status(self, periodic_test_client, seeded_matrix):
        """Assert each scenario resolves to the expected last_run_status."""
        response = periodic_test_client.get("/periodic/")
        assert response.status_code == status.HTTP_200_OK
        statuses = {row["name"]: row["last_run_status"] for row in response.json()}

        assert statuses["never-run"] is None
        assert statuses["succeeded"] == "success"
        assert statuses["failed"] == "failed"
        assert statuses["running"] == "running"
        assert statuses["manual-only"] is None
        assert statuses["no-history"] is None

    @pytest_asyncio.fixture
    async def seeded_two_schedules(
        self,
        celery_beat_session: AsyncSession,
        tasks_session: AsyncSession,
    ) -> None:
        """Seed two schedules bound to the same task name with one system run."""
        ran_at = utc_now()
        await _add_periodic_task(
            celery_beat_session,
            name="schedule-one",
            task_name="shared-task",
            last_run_at=ran_at,
        )
        await _add_periodic_task(
            celery_beat_session,
            name="schedule-two",
            task_name="shared-task",
            last_run_at=ran_at,
        )
        await _add_history(
            tasks_session,
            task_name="shared-task",
            task_status=TaskHistoryStatusEnum.SUCCESS,
        )

    def test_two_schedules_same_task_agree(
        self, periodic_test_client, seeded_two_schedules
    ):
        """Assert two schedules on one task name report the same last_run_status."""
        response = periodic_test_client.get("/periodic/")
        assert response.status_code == status.HTTP_200_OK
        statuses = {row["name"]: row["last_run_status"] for row in response.json()}

        assert statuses["schedule-one"] == "success"
        assert statuses["schedule-two"] == "success"

    @pytest_asyncio.fixture
    async def seeded_retrieve(
        self,
        celery_beat_session: AsyncSession,
        tasks_session: AsyncSession,
    ) -> PeriodicTask:
        """Seed a single run periodic task for the retrieve route."""
        task = await _add_periodic_task(
            celery_beat_session,
            name="retrieve-me",
            task_name="retrieve-task",
            last_run_at=utc_now(),
        )
        await _add_history(
            tasks_session,
            task_name="retrieve-task",
            task_status=TaskHistoryStatusEnum.SUCCESS,
        )
        return task

    def test_retrieve_reports_last_run_status(
        self, periodic_test_client, seeded_retrieve
    ):
        """Assert the retrieve route also carries last_run_status."""
        response = periodic_test_client.get(f"/periodic/{seeded_retrieve.id}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["last_run_status"] == "success"

    def test_update_preserves_last_run_status(
        self, periodic_test_client, seeded_retrieve
    ):
        """Assert editing a previously-run schedule still reports its last result.

        Regression: the update route defaulted ``last_run_status`` to ``None``
        because it returned the raw ORM row without enrichment, making an edited
        schedule look never-run.
        """
        update_data = {
            "name": "retrieve-me",
            "task": "retrieve-task",
            "start_time": None,
            "enabled": False,
            "description": "edited",
            "interval": {"every": 30, "period": "minutes"},
        }
        response = periodic_test_client.put(
            f"/periodic/{seeded_retrieve.id}",
            json=update_data,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["last_run_status"] == "success"

    @pytest_asyncio.fixture
    async def seeded_false_attribution(
        self,
        celery_beat_session: AsyncSession,
        tasks_session: AsyncSession,
    ) -> None:
        """Seed a schedule whose own run is older than an unrelated later run.

        The schedule dispatched at ``ran_at`` and succeeded; a separate later
        system run of the same task name (e.g. a chain child) then failed. The
        schedule must report its own success, not the later failure.
        """
        ran_at = utc_now()
        await _add_periodic_task(
            celery_beat_session,
            name="own-run",
            task_name="shared-run",
            last_run_at=ran_at,
        )
        task = await TaskManager.create(
            tasks_session,
            TaskWrite.model_validate(TaskFactory.build(name="shared-run")),
        )
        await _add_history_row(
            tasks_session,
            task,
            task_status=TaskHistoryStatusEnum.SUCCESS,
            created_at=ran_at + timedelta(seconds=1),
        )
        await _add_history_row(
            tasks_session,
            task,
            task_status=TaskHistoryStatusEnum.FAILED,
            created_at=ran_at + timedelta(minutes=5),
        )

    def test_later_unrelated_run_not_attributed(
        self, periodic_test_client, seeded_false_attribution
    ):
        """Assert a later same-name system run does not clobber the schedule's result."""
        response = periodic_test_client.get("/periodic/")
        assert response.status_code == status.HTTP_200_OK
        row = next(row for row in response.json() if row["name"] == "own-run")
        assert row["last_run_status"] == "success"

    @pytest_asyncio.fixture
    async def seeded_prior_run(
        self,
        celery_beat_session: AsyncSession,
        tasks_session: AsyncSession,
    ) -> None:
        """Seed a schedule preceded by an older, unrelated same-name system run.

        A separate system run of the same task name failed before the schedule
        dispatched at ``ran_at``. The schedule must report its own later success,
        not the earlier failure that predates ``last_run_at``.
        """
        ran_at = utc_now()
        await _add_periodic_task(
            celery_beat_session,
            name="later-run",
            task_name="prior-run",
            last_run_at=ran_at,
        )
        task = await TaskManager.create(
            tasks_session,
            TaskWrite.model_validate(TaskFactory.build(name="prior-run")),
        )
        await _add_history_row(
            tasks_session,
            task,
            task_status=TaskHistoryStatusEnum.FAILED,
            created_at=ran_at - timedelta(minutes=5),
        )
        await _add_history_row(
            tasks_session,
            task,
            task_status=TaskHistoryStatusEnum.SUCCESS,
            created_at=ran_at + timedelta(seconds=1),
        )

    def test_earlier_unrelated_run_not_attributed(
        self, periodic_test_client, seeded_prior_run
    ):
        """Assert a same-name system run before last_run_at is not attributed."""
        response = periodic_test_client.get("/periodic/")
        assert response.status_code == status.HTTP_200_OK
        row = next(row for row in response.json() if row["name"] == "later-run")
        assert row["last_run_status"] == "success"


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

    @pytest.mark.asyncio
    async def test_update_periodic_task_with_chain_unchanged(
        self,
        periodic_test_client,
        celery_beat_session,
        tasks_session,
    ):
        """Assert updating only cron preserves existing chain and succeeds.

        This is a regression test for the bug where editing a periodic task
        with existing chained tasks would fail validation even if the chain
        was not being modified. The PUT request should include the execute_request
        with chain_task_names, and validation should not fail for unchanged chains.
        """
        shared = {"owner": "BACKUPS", "data": {"Constraints": [{"RTarget": "n"}]}}
        await TaskManager.create(
            tasks_session,
            TaskWrite.model_validate(TaskFactory.build(name="task-a", **shared)),
        )
        await TaskManager.create(
            tasks_session,
            TaskWrite.model_validate(TaskFactory.build(name="task-b", **shared)),
        )

        schedule = IntervalSchedule(every=10, period=Period.MINUTES)
        celery_beat_session.add(schedule)
        await celery_beat_session.flush()

        periodic_task = PeriodicTask(
            name="chained-periodic",
            task=CELERY_TASK_NAME,
            kwargs=json.dumps(
                {
                    "task_name": "task-a",
                    "execution_data": {
                        "chain_task_names": ["task-b"],
                        "meta": {},
                    },
                }
            ),
            enabled=True,
            description="A periodic task with chain",
            schedule_model=schedule,
        )
        celery_beat_session.add(periodic_task)
        await celery_beat_session.commit()
        await celery_beat_session.refresh(periodic_task)

        update_data = {
            "name": "chained-periodic",
            "task": "task-a",
            "start_time": None,
            "enabled": True,
            "description": "A periodic task with chain",
            "execute_request": {
                "chain_task_names": ["task-b"],
                "meta": {},
            },
            "crontab": {
                "minute": "0",
                "hour": "*/2",
                "day_of_month": "*",
                "month_of_year": "*",
                "day_of_week": "*",
                "timezone": "UTC",
            },
        }
        response = periodic_test_client.put(
            f"/periodic/{periodic_task.id}",
            json=update_data,
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # Chain should be preserved
        assert data["execute_request"]["chain_task_names"] == ["task-b"]

    @pytest.mark.asyncio
    async def test_update_periodic_task_without_execute_request_preserves_chain(
        self,
        periodic_test_client,
        celery_beat_session,
        tasks_session,
    ):
        """Assert updating without execute_request in body preserves existing chain.

        This is a regression test for the bug where kwargs reconstruction
        did not update the kwargs field, causing execution_data to be dropped
        from the persisted row when execute_request was omitted from the PUT body.
        """
        shared = {"owner": "BACKUPS", "data": {"Constraints": [{"RTarget": "n"}]}}
        await TaskManager.create(
            tasks_session,
            TaskWrite.model_validate(TaskFactory.build(name="task-a", **shared)),
        )
        await TaskManager.create(
            tasks_session,
            TaskWrite.model_validate(TaskFactory.build(name="task-b", **shared)),
        )

        schedule = IntervalSchedule(every=10, period=Period.MINUTES)
        celery_beat_session.add(schedule)
        await celery_beat_session.flush()

        periodic_task = PeriodicTask(
            name="chained-periodic",
            task=CELERY_TASK_NAME,
            kwargs=json.dumps(
                {
                    "task_name": "task-a",
                    "execution_data": {
                        "chain_task_names": ["task-b"],
                        "meta": {},
                    },
                }
            ),
            enabled=True,
            description="A periodic task with chain",
            schedule_model=schedule,
        )
        celery_beat_session.add(periodic_task)
        await celery_beat_session.commit()
        await celery_beat_session.refresh(periodic_task)

        update_data = {
            "name": "chained-periodic",
            "task": "task-a",
            "start_time": None,
            "enabled": True,
            "description": "Updated description",
            "crontab": {
                "minute": "0",
                "hour": "*/4",
                "day_of_month": "*",
                "month_of_year": "*",
                "day_of_week": "*",
                "timezone": "UTC",
            },
        }
        response = periodic_test_client.put(
            f"/periodic/{periodic_task.id}",
            json=update_data,
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["execute_request"]["chain_task_names"] == ["task-b"]
        assert data["description"] == "Updated description"


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
