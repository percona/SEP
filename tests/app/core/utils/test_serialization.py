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

"""Define tests for the app.core.utils.serialization module."""

from datetime import datetime, UTC

import pytest

from app.core.utils import json_serializer


class Custom:
    """Represent a custom object for JSON serialization tests."""

    def __init__(self, value):
        self.value = value


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (
            {"name": "Alice", "age": 30, "is_active": True},
            '{"name": "Alice", "age": 30, "is_active": true}',
        ),
        (
            {
                "users": [
                    {"id": 1, "name": "Bob"},
                    {"id": 2, "name": "Charlie"},
                ],
                "count": 2,
            },
            '{"users": [{"id": 1, "name": "Bob"}, {"id": 2, "name": "Charlie"}], "count": 2}',
        ),
        (
            {"timestamp": datetime(2024, 1, 1, tzinfo=UTC)},
            '{"timestamp": "2024-01-01T00:00:00+00:00"}',
        ),
        ({"custom": Custom(10)}, '{"custom": {"value": 10}}'),
    ],
    ids=["flat-dict", "nested-dict-and-list", "datetime-utc", "custom-object"],
)
def test_json_serializer(data, expected):
    """Test json_serializer utility for converting data to JSON strings."""
    assert json_serializer(data) == expected
