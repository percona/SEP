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

"""Define tests for the app.tasks.db.utils module."""

import json

import pytest

from app.tasks.db.utils import json_deserialize
from app.tasks.models import TaskExecutionRequest


class TestJsonDeserialize:
    """Test the json_deserialize function."""

    def test_valid_task_execution_request(self):
        """Assert valid TaskExecutionRequest JSON returns a model instance."""
        data = {"task": "backup", "target": "node-1"}
        result = json_deserialize(json.dumps(data))
        assert isinstance(result, TaskExecutionRequest)
        assert result.task == "backup"
        assert result.target == "node-1"

    def test_valid_request_with_optional_fields(self):
        """Assert valid JSON with optional fields returns a populated model."""
        data = {
            "task": "backup",
            "target": "node-1",
            "meta": {"key": "value"},
            "payload": "some-payload",
        }
        result = json_deserialize(json.dumps(data))
        assert isinstance(result, TaskExecutionRequest)
        assert result.meta == {"key": "value"}
        assert result.payload == "some-payload"

    def test_invalid_json_returns_dict(self):
        """Assert JSON missing required fields returns a raw dict."""
        data = {"not_a_task": "value"}
        result = json_deserialize(json.dumps(data))
        assert isinstance(result, dict)
        assert result == data

    def test_array_json_raises_type_error(self):
        """Assert JSON array raises TypeError since it cannot be unpacked."""
        data = [1, 2, 3]
        with pytest.raises(TypeError):
            json_deserialize(json.dumps(data))

    def test_nested_json_without_required_fields(self):
        """Assert nested JSON without required fields returns a dict."""
        data = {"nested": {"key": "value"}, "other": 42}
        result = json_deserialize(json.dumps(data))
        assert isinstance(result, dict)
        assert result == data

    def test_partial_fields_returns_dict(self):
        """Assert JSON with only one required field returns a dict."""
        data = {"task": "backup"}
        result = json_deserialize(json.dumps(data))
        assert isinstance(result, dict)

    def test_invalid_json_raises_error(self):
        """Assert malformed JSON raises a json.JSONDecodeError."""
        with pytest.raises(json.JSONDecodeError):
            json_deserialize("not valid json")
