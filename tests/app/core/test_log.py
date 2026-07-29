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

"""Test contextual logging utilities."""

import logging

from app.core.log import (
    _CONTEXT_VARS,
    clear_log_context,
    ContextFilter,
    ContextFormatter,
    correlation_id_var,
    request_id_var,
    set_log_context,
    user_var,
)


def _make_record() -> logging.LogRecord:
    """Create a minimal log record for testing."""
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="test message",
        args=None,
        exc_info=None,
    )


class TestContextFilter:
    """Test the ContextFilter logging filter."""

    def setup_method(self) -> None:
        """Reset context vars before each test."""
        clear_log_context()

    def teardown_method(self) -> None:
        """Reset context vars after each test."""
        clear_log_context()

    def test_defaults(self) -> None:
        """Assert all attributes default to ``"-"`` when no context is set."""
        record = _make_record()
        context_filter = ContextFilter()

        result = context_filter.filter(record)

        assert result is True
        for attr in _CONTEXT_VARS:
            assert getattr(record, attr) == "-"

    def test_with_values(self) -> None:
        """Assert filter reads set ContextVar values into record attributes."""
        request_id_var.set("req-123")
        correlation_id_var.set("corr-456")
        user_var.set("alice")

        record = _make_record()
        context_filter = ContextFilter()
        context_filter.filter(record)

        assert record.request_id == "req-123"
        assert record.correlation_id == "corr-456"
        assert record.user == "alice"
        assert record.endpoint == "-"
        assert record.task_id == "-"
        assert record.task_name == "-"


class TestSetLogContext:
    """Test the set_log_context helper."""

    def setup_method(self) -> None:
        """Reset context vars before each test."""
        clear_log_context()

    def teardown_method(self) -> None:
        """Reset context vars after each test."""
        clear_log_context()

    def test_sets_multiple_vars(self) -> None:
        """Assert set_log_context sets multiple context vars at once."""
        set_log_context(request_id="req-1", user="bob", endpoint="/api/test")

        assert request_id_var.get() == "req-1"
        assert user_var.get() == "bob"

    def test_ignores_unknown_keys(self) -> None:
        """Assert unknown keys are silently ignored."""
        set_log_context(nonexistent_key="value", request_id="req-2")

        assert request_id_var.get() == "req-2"


class TestClearLogContext:
    """Test the clear_log_context helper."""

    def test_resets_all_vars(self) -> None:
        """Assert all context vars reset to ``"-"``."""
        set_log_context(
            request_id="req-1",
            correlation_id="corr-1",
            user="alice",
            endpoint="/test",
            task_id="task-1",
            task_name="my_task",
        )

        clear_log_context()

        for var in _CONTEXT_VARS.values():
            assert var.get() == "-"


class TestContextFormatter:
    """Test the ContextFormatter that appends non-default log context fields."""

    def setup_method(self) -> None:
        """Reset context vars before each test."""
        clear_log_context()

    def teardown_method(self) -> None:
        """Reset context vars after each test."""
        clear_log_context()

    def test_defaults_render_base_only(self) -> None:
        """Assert all ``"-"`` defaults are omitted from the appended context."""
        correlation_id_var.set("corr-456")

        record = _make_record()
        ContextFilter().filter(record)

        formatter = ContextFormatter(
            fmt="%(name)s: [%(correlation_id)s] %(message)s <%(process)d>",
        )
        result = formatter.format(record)

        expected = (
            f"{record.name}: [{record.correlation_id}] "
            f"{record.getMessage()} <{record.process}>"
        )
        assert result == expected

    def test_request_context_appends_fields(self) -> None:
        """Assert request-context fields are appended in stable order."""
        set_log_context(
            request_id="req-123",
            correlation_id="corr-456",
            user="alice",
            endpoint="/api/test",
        )

        record = _make_record()
        ContextFilter().filter(record)

        formatter = ContextFormatter(
            fmt="%(name)s: [%(correlation_id)s] %(message)s <%(process)d>",
        )
        result = formatter.format(record)

        expected_base = (
            f"{record.name}: [{record.correlation_id}] "
            f"{record.getMessage()} <{record.process}>"
        )
        assert result == (
            expected_base + " request_id=req-123 user=alice endpoint=/api/test"
        )
        assert "correlation_id=" not in result

    def test_task_context_appends_fields(self) -> None:
        """Assert task-context fields are appended for Celery-like logs."""
        set_log_context(
            correlation_id="corr-456",
            task_id="task-1",
            task_name="my_task",
        )

        record = _make_record()
        ContextFilter().filter(record)

        formatter = ContextFormatter(
            fmt="%(name)s: [%(correlation_id)s] %(message)s <%(process)d>",
        )
        result = formatter.format(record)

        expected_base = (
            f"{record.name}: [{record.correlation_id}] "
            f"{record.getMessage()} <{record.process}>"
        )
        assert result == expected_base + " task_id=task-1 task_name=my_task"
        assert "request_id=" not in result
        assert "endpoint=" not in result
        assert "user=" not in result

    def test_uvicorn_layout_preserved(self) -> None:
        """Assert the uvicorn base layout remains intact."""
        set_log_context(correlation_id="corr-999", user="alice")

        record = _make_record()
        ContextFilter().filter(record)

        formatter = ContextFormatter(
            fmt="uvicorn: [%(correlation_id)s] %(message)s <%(process)d>",
        )
        result = formatter.format(record)

        expected_base = f"uvicorn: [{record.correlation_id}] {record.getMessage()} <{record.process}>"
        assert result == expected_base + " user=alice"
