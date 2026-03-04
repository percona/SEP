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

"""Define tests for the app.sep.routes.periodic_tasks module."""

import datetime

import pytest
from fastapi import status
from sqlalchemy_celery_beat import PeriodicTask

from tests.app.factories import PeriodicTaskFactory


@pytest.fixture
def created_periodic_task() -> PeriodicTask:
    """Return a fake created periodic task."""
    return PeriodicTaskFactory.build()


@pytest.mark.parametrize(
    "extra_data",
    [
        {
            "cron_expression": "* * * * *",
            "cron_timezone": lambda faker: faker.timezone(),
        },
        {
            "interval_every": 10,
            "interval_period": "days",
        },
    ],
)
def test_periodic_task_create(test_client, mock_task_api_dep, faker, extra_data):
    """Test creating a new periodic task."""
    task_name = "run-python"
    start_time = faker.date_time_this_year()
    task_data = {
        "task": task_name,
        "start_time": start_time.replace(tzinfo=datetime.UTC),
        "enabled": True,
        **{
            key: (value(faker) if callable(value) else value)
            for key, value in extra_data.items()
        },
    }

    response = test_client.post("/periodic/", data=task_data, follow_redirects=False)
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/tasks"


def test_periodic_task_delete(
    test_client,
    created_periodic_task,
    mock_task_api_dep,
):
    """Test deleting a periodic task."""
    response = test_client.post(
        f"/periodic/{created_periodic_task.id}/delete", follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/tasks"
    mock_task_api_dep.delete.assert_awaited_once_with(
        f"/periodic/{created_periodic_task.id}"
    )


def test_periodic_task_update(test_client, mock_task_api_dep, created_periodic_task):
    """Test updating a periodic task."""
    updated_task_data = {
        "enabled": "false",
    }
    response = test_client.post(
        f"/periodic/{created_periodic_task.id}/update",
        data=updated_task_data,
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/tasks"
