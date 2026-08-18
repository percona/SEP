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

"""Define test fixtures for tasks tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import undefer
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.pool import StaticPool
from starlette.testclient import TestClient

from app.api.deps import get_current_user, require_admin_for_unsafe_methods
from app.core.auth.providers.casdoor.models import CasdoorUser
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils import json_serializer
from app.tasks.crud import TaskHistoryManager, TaskManager
from app.tasks.deps import get_request_executor, get_session
from app.tasks.execution.models import BaseExecutor
from app.tasks.main import tasks_app
from app.tasks.models import TaskHistory, TaskWrite
from tests.app.factories import build_task_history, TaskFactory


@pytest_asyncio.fixture(name="session")
async def session_fixture() -> AsyncSession:
    """Create an async db session for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session_maker = get_async_session_maker_from_engine(engine)
    try:
        async with async_session_maker() as session:
            yield session
    finally:
        await engine.dispose()


@pytest.fixture
def mock_executor() -> AsyncMock:
    """Return a mock executor with spec of BaseExecutor."""
    executor = AsyncMock(spec=BaseExecutor)
    executor.get_hosts = MagicMock(return_value={"node1": "10.0.0.1"})
    executor.preflight_stream_logs = MagicMock(return_value=None)
    executor.get_events = MagicMock(return_value=[])
    return executor


@pytest.fixture
def test_client(
    regular_user: CasdoorUser, session: AsyncSession, mock_executor: AsyncMock
) -> TestClient:
    """Create an authenticated test client for the app.

    Mirrors the SEP ``test_client``'s ``require_admin_for_unsafe_methods``
    override so the non-admin fixture user can exercise a mutating route.
    """
    tasks_app.dependency_overrides[require_admin_for_unsafe_methods] = lambda: None
    tasks_app.dependency_overrides[get_current_user] = lambda: regular_user
    tasks_app.dependency_overrides[get_session] = lambda: session
    tasks_app.dependency_overrides[get_request_executor] = lambda: mock_executor
    yield TestClient(tasks_app)
    tasks_app.dependency_overrides = {}


@pytest_asyncio.fixture
async def created_task_with_history(session: AsyncSession) -> TaskHistory:
    """Return a task with a related task history record saved in the database."""
    task = await TaskManager.create(
        session,
        TaskWrite.model_validate(
            TaskFactory.build(name="history-task", output_files_path="/output")
        ),
    )
    saved = await TaskHistoryManager.save(session, build_task_history(task))
    return await TaskHistoryManager.get_or_404(
        session,
        select_related=(TaskHistory.task,),
        query_options=[undefer(TaskHistory.execution_request)],
        id=saved.id,
    )
