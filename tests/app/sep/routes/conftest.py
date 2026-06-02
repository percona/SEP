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

"""Shared pytest fixtures for ``app.sep.routes`` tests."""

import pytest
from faker import Faker

from app.tasks.models import (
    Task,
    TaskExecutionRequest,
    TaskHistoryResponse,
    TaskHistoryStatusEnum,
)
from tests.app.factories import TaskFactory


@pytest.fixture
def created_task() -> Task:
    """Return a fake created task."""
    return TaskFactory.build()


@pytest.fixture
def task_history_response(faker: Faker, created_task: Task) -> TaskHistoryResponse:
    """Return a fake task history response."""
    started_at = faker.past_datetime(start_date="-15d")
    return TaskHistoryResponse(
        id=faker.random_int(min=1),
        execution_request=TaskExecutionRequest(
            task="example-task",
            target="example-target",
            meta={"key": "value"},
            tracking={"allocation_id": "12345", "evaluation_id": "67890"},
        ),
        status=TaskHistoryStatusEnum.SUCCESS,
        task=created_task,
        started_at=started_at,
        finished_at=started_at + faker.time_delta(end_datetime="+1h"),
        executed_by=None,
    )
