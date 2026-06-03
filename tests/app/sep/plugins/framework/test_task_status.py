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

"""Tests for the shared ``extract_latest_task_status`` helper."""

from app.sep.plugins.framework import extract_latest_task_status
from app.tasks.models import TaskHistoryStatusEnum


class TestExtractLatestTaskStatus:
    """Test suite for ``extract_latest_task_status``."""

    def test_empty_iterable_returns_none(self) -> None:
        """Return ``None`` when no histories are provided."""
        assert extract_latest_task_status([]) is None

    def test_returns_first_non_none_status(self) -> None:
        """Return the first non-``None`` status encountered."""
        result = extract_latest_task_status([{"status": "success"}])
        assert result == TaskHistoryStatusEnum.SUCCESS

    def test_skips_leading_none_entries(self) -> None:
        """Skip leading entries with ``status=None`` and return the next status."""
        result = extract_latest_task_status([{"status": None}, {"status": "failed"}])
        assert result == TaskHistoryStatusEnum.FAILED

    def test_skips_entries_missing_status_key(self) -> None:
        """Treat a missing ``status`` key as ``None`` and continue."""
        result = extract_latest_task_status([{}, {"status": "running"}])
        assert result == TaskHistoryStatusEnum.RUNNING

    def test_all_none_returns_none(self) -> None:
        """Return ``None`` when every history entry has ``status=None``."""
        assert extract_latest_task_status([{"status": None}, {"status": None}]) is None
