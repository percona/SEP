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
