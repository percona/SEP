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

"""Define tests for the TaskExecutionRequestJSON type decorator."""

import pytest
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.dialects.postgresql import JSONB

from app.tasks.models import TaskExecutionRequest, TaskExecutionRequestJSON


@pytest.fixture(name="type_decorator")
def type_decorator_fixture() -> TaskExecutionRequestJSON:
    """Return a TaskExecutionRequestJSON instance for testing."""
    return TaskExecutionRequestJSON()


class TestProcessResultValue:
    """Test the process_result_value method."""

    def test_valid_task_execution_request(self, type_decorator):
        """Assert valid dict returns a TaskExecutionRequest instance."""
        data = {"task": "backup", "target": "node-1"}
        result = type_decorator.process_result_value(data, dialect=None)
        assert isinstance(result, TaskExecutionRequest)
        assert result.task == "backup"
        assert result.target == "node-1"

    def test_valid_request_with_optional_fields(self, type_decorator):
        """Assert dict with optional fields returns a populated model."""
        data = {
            "task": "backup",
            "target": "node-1",
            "meta": {"key": "value"},
            "payload": "some-payload",
        }
        result = type_decorator.process_result_value(data, dialect=None)
        assert isinstance(result, TaskExecutionRequest)
        assert result.meta == {"key": "value"}
        assert result.payload == "some-payload"

    def test_invalid_dict_returns_raw_value(self, type_decorator):
        """Assert dict missing required fields returns the raw dict."""
        data = {"not_a_task": "value"}
        result = type_decorator.process_result_value(data, dialect=None)
        assert isinstance(result, dict)
        assert result == data

    def test_none_returns_none(self, type_decorator):
        """Assert None input returns None."""
        result = type_decorator.process_result_value(None, dialect=None)
        assert result is None

    def test_list_returns_raw_value(self, type_decorator):
        """Assert list input returns the raw value."""
        data = [1, 2, 3]
        result = type_decorator.process_result_value(data, dialect=None)
        assert result == data

    def test_nested_dict_without_required_fields(self, type_decorator):
        """Assert nested dict without required fields returns the raw dict."""
        data = {"nested": {"key": "value"}, "other": 42}
        result = type_decorator.process_result_value(data, dialect=None)
        assert isinstance(result, dict)
        assert result == data

    def test_partial_fields_returns_dict(self, type_decorator):
        """Assert dict with only one required field returns the raw dict."""
        data = {"task": "backup"}
        result = type_decorator.process_result_value(data, dialect=None)
        assert isinstance(result, dict)


class TestProcessBindParam:
    """Test the process_bind_param method."""

    def test_none_returns_none(self, type_decorator):
        """Assert None input returns None."""
        result = type_decorator.process_bind_param(None, dialect=None)
        assert result is None

    def test_task_execution_request_returns_dict(self, type_decorator):
        """Assert TaskExecutionRequest is serialized to a dict."""
        request = TaskExecutionRequest(task="backup", target="node-1")
        result = type_decorator.process_bind_param(request, dialect=None)
        assert isinstance(result, dict)
        assert result["task"] == "backup"
        assert result["target"] == "node-1"

    def test_dict_returns_dict(self, type_decorator):
        """Assert plain dict passes through unchanged."""
        data = {"key": "value"}
        result = type_decorator.process_bind_param(data, dialect=None)
        assert result == data


class TestLoadDialectImpl:
    """Test dialect-specific type resolution for ``TaskExecutionRequestJSON``."""

    def test_postgres_resolves_to_jsonb(self, type_decorator):
        """Assert PostgreSQL dialect returns a ``JSONB`` instance."""
        result = type_decorator.load_dialect_impl(postgresql.dialect())
        assert isinstance(result, JSONB)

    def test_sqlite_resolves_to_non_jsonb_json(self, type_decorator):
        """Assert SQLite dialect returns a non-``JSONB`` JSON type.

        Pin the contract that SQLite stays on plain JSON: asserting the exact
        dialect-specific class is fragile, but asserting it is not ``JSONB``
        is robust and expresses the intent.
        """
        result = type_decorator.load_dialect_impl(sqlite.dialect())
        assert not isinstance(result, JSONB)
