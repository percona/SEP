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

"""Define tests for the app.sep.plugins.report.service module."""

from unittest.mock import AsyncMock, patch

import pytest

from app.sep.clients.pmm import PMMRemoteAPI


@pytest.fixture
def pmm_api() -> AsyncMock:
    """Return a mock PMMRemoteAPI."""
    return AsyncMock(spec=PMMRemoteAPI)


# _find_labels
class TestFindLabels:
    """Test the ``_find_labels`` helper."""

    def test_returns_labels_from_non_time_field(self):
        """Assert labels are extracted from a field that is not named Time."""
        fields = [
            {"name": "Time", "labels": {"should": "skip"}},
            {"name": "Value", "labels": {"node_name": "host-1", "mountpoint": "/"}},
        ]
        result = _find_labels(fields)
        assert result == {"node_name": "host-1", "mountpoint": "/"}

    def test_returns_empty_dict_when_no_labels(self):
        """Assert empty dict when no fields have labels."""
        fields = [{"name": "Time"}, {"name": "Value"}]
        assert _find_labels(fields) == {}

    def test_returns_empty_dict_for_empty_list(self):
        """Assert empty dict for an empty fields list."""
        assert _find_labels([]) == {}

    def test_skips_time_field_labels(self):
        """Assert labels on a Time field are treated as empty."""
        fields = [{"name": "Time", "labels": {"a": "1"}}]
        assert _find_labels(fields) == {}

    def test_returns_first_non_empty_labels(self):
        """Assert the first field with non-empty labels wins."""
        fields = [
            {"name": "A"},
            {"name": "B", "labels": {"x": "1"}},
            {"name": "C", "labels": {"y": "2"}},
        ]
        assert _find_labels(fields) == {"x": "1"}


# _interval_ms
class TestIntervalMs:
    """Test the ``_interval_ms`` helper."""

    def test_now_returns_current_epoch_ms(self):
        """Assert 'now' resolves to approximately the current time."""
        start, end = _interval_ms("now", "now")
        assert start == end
        assert start > 0

    def test_now_minus_7d_offset(self):
        """Assert 'now-7d' is 7 days before 'now'."""
        start, end = _interval_ms("now-7d", "now")
        seven_days_ms = 7 * 86400 * 1000
        assert end - start == seven_days_ms

    def test_now_minus_1h_offset(self):
        """Assert 'now-1h' is 1 hour before 'now'."""
        start, end = _interval_ms("now-1h", "now")
        one_hour_ms = 3600 * 1000
        assert end - start == one_hour_ms

    def test_now_minus_30m_offset(self):
        """Assert 'now-30m' is 30 minutes before 'now'."""
        start, end = _interval_ms("now-30m", "now")
        thirty_min_ms = 30 * 60 * 1000
        assert end - start == thirty_min_ms

    def test_now_minus_seconds(self):
        """Assert 'now-120s' is 120 seconds before 'now'."""
        start, end = _interval_ms("now-120s", "now")
        expected_ms = 120 * 1000
        assert end - start == expected_ms

    def test_raises_for_unsupported_format(self):
        """Assert ValueError for an unsupported time string."""
        with pytest.raises(ValueError, match="Unsupported time format"):
            _interval_ms("yesterday", "now")
