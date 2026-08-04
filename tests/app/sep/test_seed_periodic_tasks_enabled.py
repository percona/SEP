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

"""Regression lock: re-seeding periodic tasks must not reset ``enabled``.

The gate writes ``PeriodicTask.enabled`` directly; a later
:func:`app.core.celery.utils.init_periodic_tasks_db` re-seed (e.g. a live
snippet re-seed) must leave that bit untouched, or a disabled schedule would
silently resume.
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy_celery_beat.models import Period, PeriodicTask

from app.core.celery import utils as celery_utils
from app.core.celery.crud import BasePeriodicTaskManager
from app.core.celery.models import IntervalSchedule
from app.core.celery.utils import (
    init_periodic_tasks_db,
    SystemPeriodicTaskData,
    SystemPeriodicTaskSchedule,
)
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils import json_serializer

TASK_NAME = "sep__sync_snippets"


@pytest_asyncio.fixture(name="beat_maker")
async def beat_maker_fixture():
    """Provide a session maker bound to an in-memory celery-beat DB."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    engine = engine.execution_options(schema_translate_map={"celery_schema": None})
    async with engine.begin() as conn:
        await conn.run_sync(PeriodicTask.__table__.metadata.create_all)
    try:
        yield get_async_session_maker_from_engine(engine)
    finally:
        await engine.dispose()


def _schedule(every: int) -> list[SystemPeriodicTaskSchedule]:
    """Build a one-task system schedule with the given interval."""
    return [
        SystemPeriodicTaskSchedule(
            schedule=IntervalSchedule(every=every, period=Period.MINUTES),
            tasks=[
                SystemPeriodicTaskData(
                    name=TASK_NAME,
                    task_name="app.sep.snippets.celery.sync_snippets",
                ),
            ],
        ),
    ]


@pytest.mark.asyncio
async def test_reseed_preserves_disabled_flag(mocker, beat_maker) -> None:
    """A re-seed with a changed schedule leaves a disabled task disabled."""
    mocker.patch.object(
        celery_utils, "get_async_session_maker", return_value=beat_maker
    )

    await init_periodic_tasks_db(_schedule(every=10), "sep__")

    async with beat_maker() as session:
        task = await BasePeriodicTaskManager.first(session, name=TASK_NAME)
        task.enabled = False
        session.add(task)
        await session.commit()

    await init_periodic_tasks_db(_schedule(every=30), "sep__")

    async with beat_maker() as session:
        task = await BasePeriodicTaskManager.first(session, name=TASK_NAME)
        assert task.enabled is False
