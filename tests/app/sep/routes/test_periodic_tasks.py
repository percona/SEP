"""Define tests for the app.sep.routes.periodic_tasks module."""

import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import status
from sqlalchemy_celery_beat import PeriodicTask

from app.core.requests import RemoteAPI
from app.sep.deps import get_tasks_api
from app.sep.main import sep_app
from tests.app.factories import PeriodicTaskFactory


@pytest.fixture
def mock_task_api() -> AsyncMock:
    """Mock the TaskAPI dependency."""
    mock = AsyncMock(spec=RemoteAPI)
    sep_app.dependency_overrides[get_tasks_api] = lambda: mock
    yield mock
    sep_app.dependency_overrides = {}


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
def test_create_periodic_task(test_client, mock_task_api, faker, extra_data):
    """Test creating a new periodic task."""
    task_name = "run-python"
    start_time = faker.date_time_this_year()
    expires = faker.date_time_between_dates(datetime_start=start_time)
    task_data = {
        "task": task_name,
        "start_time": start_time.replace(tzinfo=datetime.UTC),
        "expires": expires.replace(tzinfo=datetime.UTC),
        "enabled": True,
        **{
            key: (value(faker) if callable(value) else value)
            for key, value in extra_data.items()
        },
    }

    response = test_client.post("/periodic/", data=task_data, follow_redirects=False)
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/tasks"


def test_delete_periodic_task(
    test_client,
    created_periodic_task,
    mock_task_api,
):
    """Test deleting a periodic task."""
    response = test_client.post(
        f"/periodic/{created_periodic_task.id}/delete", follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/tasks"
    mock_task_api.delete.assert_awaited_once_with(
        f"/periodic/{created_periodic_task.id}"
    )


def test_update_periodic_task(test_client, mock_task_api, created_periodic_task):
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
