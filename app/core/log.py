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

"""Define contextual logging utilities with ContextVar-backed log enrichment."""

from contextvars import ContextVar
from logging import Filter, LogRecord
from logging import Formatter as _Formatter

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")
user_var: ContextVar[str] = ContextVar("user", default="-")
endpoint_var: ContextVar[str] = ContextVar("endpoint", default="-")
task_id_var: ContextVar[str] = ContextVar("task_id", default="-")
task_name_var: ContextVar[str] = ContextVar("task_name", default="-")

_CONTEXT_VARS: dict[str, ContextVar[str]] = {
    "request_id": request_id_var,
    "correlation_id": correlation_id_var,
    "user": user_var,
    "endpoint": endpoint_var,
    "task_id": task_id_var,
    "task_name": task_name_var,
}


class ContextFilter(Filter):
    """Inject context variables into log records.

    Read all registered ``ContextVar`` values and set them as attributes on the
    ``LogRecord``, defaulting to ``"-"`` when unset.
    """

    def filter(self, record: LogRecord) -> bool:
        """Enrich ``record`` with context variable attributes.

        :param record: The log record to enrich.
        :type record: LogRecord
        :return: Always ``True`` to allow the record through.
        :rtype: bool
        """
        for attr, var in _CONTEXT_VARS.items():
            setattr(record, attr, var.get())
        return True


class ContextFormatter(_Formatter):
    """Format logs with all populated context fields appended.

    ``ContextFilter`` injects attributes on every ``LogRecord``. The configured
    base formatter is expected to already render the ``correlation_id`` in its
    human-oriented position; this formatter only appends the other context
    fields whose value differs from the default ``"-"``.
    """

    _DEFAULT_SENTINEL = "-"

    def format(self, record: LogRecord) -> str:
        """Format a log record and append non-default context fields.

        :param record: The log record to format.
        :type record: LogRecord
        :return: Base formatted line plus appended context ``key=value`` pairs.
        :rtype: str
        """
        base = super().format(record)
        parts: list[str] = []

        # Stable order: follow insertion order from `_CONTEXT_VARS`, but never
        # duplicate the correlation_id because it's rendered in the base format.
        for key in _CONTEXT_VARS:
            if key == "correlation_id":
                continue
            value = getattr(record, key, self._DEFAULT_SENTINEL)
            if value != self._DEFAULT_SENTINEL:
                parts.append(f"{key}={value}")

        if not parts:
            return base

        return f"{base} " + " ".join(parts)


def set_log_context(**kwargs: str) -> None:
    """Set one or more context variables for log enrichment.

    Unknown keys are silently ignored.

    :param kwargs: Mapping of context variable names to values.
    :type kwargs: str
    """
    for key, value in kwargs.items():
        if key in _CONTEXT_VARS:
            _CONTEXT_VARS[key].set(value)


def clear_log_context() -> None:
    """Reset all context variables to their default value."""
    for var in _CONTEXT_VARS.values():
        var.set("-")
