"""Define fixtures for plugins tests."""

import pytest

from app.sep.deps import check_for_conflicted_running_tasks
from app.sep.main import sep_app
from app.tasks.models import GeneratedTask
from tests.app.factories import GeneratedTaskFactory


@pytest.fixture
def generated_task() -> GeneratedTask:
    """Return a fake generated task while creating alters."""
    return GeneratedTaskFactory.build()


@pytest.fixture
def _mock_check_for_conflicted_running_tasks() -> None:
    """Mock check_for_conflicted_running_tasks."""
    sep_app.dependency_overrides[check_for_conflicted_running_tasks] = lambda: None
    yield
    sep_app.dependency_overrides = {}
