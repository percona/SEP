"""Define tests for the app.tasks.execution.exceptions module."""

import pytest

from app.tasks.execution.exceptions import TaskDataNotFoundInExecutorError


class TestTaskDataNotFoundInExecutorError:
    """Test the TaskDataNotFoundInExecutorError exception."""

    def test_is_exception_subclass(self):
        """Assert TaskDataNotFoundInExecutorError is an Exception subclass."""
        assert issubclass(TaskDataNotFoundInExecutorError, Exception)

    def test_construction_with_message(self):
        """Assert exception stores the provided message."""
        exc = TaskDataNotFoundInExecutorError("task data missing")
        assert str(exc) == "task data missing"

    def test_construction_without_message(self):
        """Assert exception can be constructed without a message."""
        exc = TaskDataNotFoundInExecutorError()
        assert str(exc) == ""

    def test_raise_and_catch(self):
        """Assert exception can be raised and caught."""
        with pytest.raises(TaskDataNotFoundInExecutorError, match="not found"):
            raise TaskDataNotFoundInExecutorError("not found")
