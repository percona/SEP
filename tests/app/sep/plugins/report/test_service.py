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
from app.sep.plugins.report.service import (
    _get_metrics_datasource,
    _refresh_checks,
)


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
# _get_metrics_datasource
class TestGetMetricsDatasource:
    """Test the ``_get_metrics_datasource`` helper."""

    @pytest.mark.asyncio
    async def test_returns_id_and_uid(self, pmm_api):
        """Assert the correct (id, uid) tuple is returned."""
        ds_id = 42
        pmm_api.get_grafana_datasources.return_value = [
            {"name": "Logs", "id": 1, "uid": "logs-uid"},
            {"name": "Metrics", "id": ds_id, "uid": "metrics-uid"},
        ]
        result = await _get_metrics_datasource(pmm_api)
        assert result == (ds_id, "metrics-uid")

    @pytest.mark.asyncio
    async def test_raises_when_not_found(self, pmm_api):
        """Assert LookupError when Metrics datasource is absent."""
        pmm_api.get_grafana_datasources.return_value = [
            {"name": "Logs", "id": 1, "uid": "logs-uid"},
        ]
        with pytest.raises(LookupError, match="Metrics datasource not found"):
            await _get_metrics_datasource(pmm_api)

    @pytest.mark.asyncio
    async def test_raises_for_empty_list(self, pmm_api):
        """Assert LookupError when datasource list is empty."""
        pmm_api.get_grafana_datasources.return_value = []
        with pytest.raises(LookupError):
            await _get_metrics_datasource(pmm_api)


# _refresh_checks
class TestRefreshChecks:
    """Test the ``_refresh_checks`` helper."""

    @pytest.mark.asyncio
    async def test_calls_start_for_each_enabled_check(self, pmm_api):
        """Assert start_advisor_checks is called for each enabled check."""
        raw = [
            {"name": "check_a"},
            {"name": "check_b", "disabled": True},
            {"name": "check_c"},
        ]
        issues = await _refresh_checks(pmm_api, raw)
        expected_call_count = 2
        assert pmm_api.start_advisor_checks.await_count == expected_call_count
        assert issues == []

    @pytest.mark.asyncio
    async def test_records_timed_out_checks(self, pmm_api):
        """Assert names of checks that raise OSError are returned."""
        pmm_api.start_advisor_checks.side_effect = OSError("timeout")
        raw = [{"name": "check_a"}, {"name": "check_b"}]
        issues = await _refresh_checks(pmm_api, raw)
        assert issues == ["check_a", "check_b"]

    @pytest.mark.asyncio
    async def test_skips_disabled_checks(self, pmm_api):
        """Assert disabled checks are not refreshed."""
        raw = [{"name": "check_a", "disabled": True}]
        issues = await _refresh_checks(pmm_api, raw)
        pmm_api.start_advisor_checks.assert_not_awaited()
        assert issues == []

    @pytest.mark.asyncio
    async def test_empty_list(self, pmm_api):
        """Assert empty input returns empty issues."""
        assert await _refresh_checks(pmm_api, []) == []
