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

"""Define test fixtures for periodic task tests."""

import json

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy_celery_beat import IntervalSchedule
from sqlalchemy_celery_beat.models import Period, PeriodicTask
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.pool import StaticPool
from starlette.testclient import TestClient

from app.api.deps import get_current_user
from app.core.celery.deps import get_session as get_celery_beat_session
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils import json_serializer
from app.models import CasdoorUser
from app.tasks.db.utils import json_deserialize
from app.tasks.deps import get_session as get_tasks_session
from app.tasks.main import tasks_app

CELERY_TASK_NAME = "app.tasks.celery.execute_task_by_name"


@pytest_asyncio.fixture(name="celery_beat_session")
async def celery_beat_session_fixture() -> AsyncSession:
    """Create an async db session for celery beat tables."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        json_serializer=json_serializer,
        json_deserializer=json_deserialize,
        poolclass=StaticPool,
    )
    engine = engine.execution_options(schema_translate_map={"celery_schema": None})
    metadata = PeriodicTask.__table__.metadata
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    async_session_maker = get_async_session_maker_from_engine(engine)
    async with async_session_maker() as session:
        yield session


@pytest_asyncio.fixture(name="tasks_session")
async def tasks_session_fixture() -> AsyncSession:
    """Create an async db session for tasks tables."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        json_serializer=json_serializer,
        json_deserializer=json_deserialize,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session_maker = get_async_session_maker_from_engine(engine)
    async with async_session_maker() as session:
        yield session


@pytest.fixture
def periodic_test_client(
    regular_user: CasdoorUser,
    celery_beat_session: AsyncSession,
    tasks_session: AsyncSession,
) -> TestClient:
    """Create an authenticated test client with both celery beat and tasks sessions."""
    tasks_app.dependency_overrides[get_current_user] = lambda: regular_user
    tasks_app.dependency_overrides[get_celery_beat_session] = (
        lambda: celery_beat_session
    )
    tasks_app.dependency_overrides[get_tasks_session] = lambda: tasks_session
    yield TestClient(tasks_app)
    tasks_app.dependency_overrides = {}


@pytest_asyncio.fixture
async def created_periodic_task(celery_beat_session: AsyncSession) -> PeriodicTask:
    """Create and return a periodic task in the celery beat database."""
    schedule = IntervalSchedule(every=10, period=Period.MINUTES)
    celery_beat_session.add(schedule)
    await celery_beat_session.flush()

    task = PeriodicTask(
        name="test-periodic-task",
        task=CELERY_TASK_NAME,
        kwargs=json.dumps(
            {"task_name": "my-backup-task", "execution_data": {"meta": {}}}
        ),
        enabled=True,
        description="A test periodic task",
        schedule_model=schedule,
    )
    celery_beat_session.add(task)
    await celery_beat_session.commit()
    await celery_beat_session.refresh(task)
    return task
