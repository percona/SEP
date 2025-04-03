"""Define fixtures for plugins tests."""

import pytest

from app.tasks.models import TaskWrite
from tests.app.factories import TaskWriteFactory


@pytest.fixture
def generated_task() -> TaskWrite:
    """Return a fake generated task while creating alters."""
    return TaskWriteFactory.build(data={"task": "mock-task"})
