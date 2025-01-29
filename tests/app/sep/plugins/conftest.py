"""Define fixtures for plugins tests."""

import pytest

from app.tasks.models import GeneratedTask
from tests.app.factories import GeneratedTaskFactory


@pytest.fixture
def generated_task() -> GeneratedTask:
    """Return a fake generated task while creating alters."""
    return GeneratedTaskFactory.build()
