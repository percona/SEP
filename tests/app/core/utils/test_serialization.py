"""Define tests for the app.core.utils.serialization module."""

from datetime import UTC

from app.core.utils import json_serializer


def test_json_serializer():
    """Test json_serializer utility for converting data to JSON strings."""
    data = {"name": "Alice", "age": 30, "is_active": True}
    json_str = json_serializer(data)
    assert json_str == '{"name": "Alice", "age": 30, "is_active": true}'

    data = {
        "users": [
            {"id": 1, "name": "Bob"},
            {"id": 2, "name": "Charlie"},
        ],
        "count": 2,
    }
    json_str = json_serializer(data)
    assert (
        json_str
        == '{"users": [{"id": 1, "name": "Bob"}, {"id": 2, "name": "Charlie"}], "count": 2}'
    )

    from datetime import datetime

    data = {"timestamp": datetime(2024, 1, 1, tzinfo=UTC)}
    json_str = json_serializer(data)
    assert json_str == '{"timestamp": "2024-01-01T00:00:00+00:00"}'

    class Custom:
        """Custom class for testing JSON serialization."""

        def __init__(self, value):
            self.value = value

    data = {"custom": Custom(10)}
    json_str = json_serializer(data)
    assert json_str == '{"custom": {"value": 10}}'
