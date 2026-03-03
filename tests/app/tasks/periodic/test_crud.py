"""Define test cases for periodic task CRUD operations."""

import json

import pytest
import pytest_asyncio
from sqlalchemy_celery_beat import IntervalSchedule
from sqlalchemy_celery_beat.models import Period, PeriodicTask
from sqlmodel.ext.asyncio.session import AsyncSession

from app.tasks.periodic.crud import PeriodicTaskManager

CELERY_TASK_NAME = "app.tasks.celery.execute_task_by_name"


@pytest_asyncio.fixture
async def periodic_tasks(celery_beat_session: AsyncSession) -> list[PeriodicTask]:
    """Create multiple periodic tasks for testing."""
    schedule = IntervalSchedule(every=10, period=Period.MINUTES)
    celery_beat_session.add(schedule)
    await celery_beat_session.flush()

    tasks = []
    for name in ("backup-daily", "restore-weekly"):
        task = PeriodicTask(
            name=f"periodic-{name}",
            task=CELERY_TASK_NAME,
            kwargs=json.dumps({"task_name": name, "execution_data": None}),
            enabled=True,
            description=f"Test {name}",
            schedule_model=schedule,
        )
        celery_beat_session.add(task)
        tasks.append(task)

    other_task = PeriodicTask(
        name="other-celery-task",
        task="some.other.celery.task",
        kwargs=json.dumps({"task_name": "unrelated"}),
        enabled=True,
        description="Not managed by SEP",
        schedule_model=schedule,
    )
    celery_beat_session.add(other_task)

    await celery_beat_session.commit()
    for task in tasks:
        await celery_beat_session.refresh(task)
    return tasks


class TestPeriodicTaskManagerFilterQuery:
    """Test the _filter_query method of PeriodicTaskManager."""

    @pytest.mark.asyncio
    async def test_filter_query_only_returns_execute_task_by_name(
        self, celery_beat_session, periodic_tasks
    ):
        """Assert _filter_query always filters by the execute_task_by_name task."""
        results = await PeriodicTaskManager.list(celery_beat_session)
        task_names = {t.task for t in results}
        assert task_names == {CELERY_TASK_NAME}
        assert len(results) == len(periodic_tasks)


class TestPeriodicTaskManagerSave:
    """Test the save method of PeriodicTaskManager."""

    @pytest.mark.asyncio
    async def test_save_sets_task_to_celery_name(self, celery_beat_session):
        """Assert save forces the task field to execute_task_by_name."""
        schedule = IntervalSchedule(every=5, period=Period.HOURS)
        celery_beat_session.add(schedule)
        await celery_beat_session.flush()

        instance = PeriodicTask(
            name="save-test",
            task="wrong.task.name",
            kwargs=json.dumps({"task_name": "test"}),
            enabled=True,
            description="",
            schedule_model=schedule,
        )
        saved = await PeriodicTaskManager.save(celery_beat_session, instance)
        assert saved.task == CELERY_TASK_NAME


class TestPeriodicTaskManagerListByTaskNames:
    """Test the list_by_task_names method of PeriodicTaskManager."""

    @pytest.mark.asyncio
    async def test_list_by_single_task_name(self, celery_beat_session, periodic_tasks):
        """Assert filtering by a single task name returns matching tasks."""
        results = await PeriodicTaskManager.list_by_task_names(
            celery_beat_session, "backup-daily"
        )
        assert len(results) == 1
        assert results[0].name == "periodic-backup-daily"

    @pytest.mark.asyncio
    async def test_list_by_multiple_task_names(
        self, celery_beat_session, periodic_tasks
    ):
        """Assert filtering by multiple task names returns all matches."""
        results = await PeriodicTaskManager.list_by_task_names(
            celery_beat_session, "backup-daily", "restore-weekly"
        )
        assert len(results) == len(periodic_tasks)
        result_names = {t.name for t in results}
        assert result_names == {"periodic-backup-daily", "periodic-restore-weekly"}

    @pytest.mark.asyncio
    async def test_list_by_nonexistent_task_name(
        self, celery_beat_session, periodic_tasks
    ):
        """Assert filtering by a non-existent task name returns empty list."""
        results = await PeriodicTaskManager.list_by_task_names(
            celery_beat_session, "nonexistent-task"
        )
        assert results == []


class TestPeriodicTaskManagerBuildWhereClause:
    """Test the build_where_clause_by_task_names static method."""

    def test_returns_clause(self):
        """Assert build_where_clause_by_task_names returns a valid SQLAlchemy clause."""
        clause = PeriodicTaskManager.build_where_clause_by_task_names(
            "task-a", "task-b"
        )
        assert clause is not None
        compiled = str(clause.compile())
        assert "IN" in compiled
