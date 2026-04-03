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

"""Test the alert troubleshooting plugin dependencies."""

from types import SimpleNamespace

import pytest

from app.core.exceptions import HTTPNotFoundException
from app.sep.models import AlertServiceType
from app.sep.plugins.alert_troubleshooting.deps import (
    AlertInfo,
    camel_case_to_title,
    collect_grouped_alerts,
    filter_snippets_for_alert,
    normalize_alert_entry,
)

EXPECTED_BOTH_SNIPPETS = 2


class TestCamelCaseToTitle:
    """Test the CamelCase-to-title-case conversion utility."""

    def test_basic_camel_case(self):
        """Assert basic CamelCase is split correctly."""
        assert camel_case_to_title("HighCPUUsage") == "High CPU Usage"

    def test_postgresql_acronym(self):
        """Assert PostgreSQL is kept as a single compound name."""
        assert (
            camel_case_to_title("PostgreSQLLockConflicts")
            == "PostgreSQL Lock Conflicts"
        )

    def test_mysql_prefix(self):
        """Assert MySQL is kept as a single compound name."""
        assert camel_case_to_title("MySQLTablesWithoutPK") == "MySQL Tables Without PK"

    def test_single_word(self):
        """Assert a single word is returned unchanged."""
        assert camel_case_to_title("Alert") == "Alert"

    def test_all_uppercase_acronym(self):
        """Assert a standalone acronym is preserved."""
        assert camel_case_to_title("IO") == "IO"

    def test_acronym_at_end(self):
        """Assert an acronym at the end is split correctly."""
        assert camel_case_to_title("HighIO") == "High IO"

    def test_multiple_acronyms(self):
        """Assert multiple acronyms in one identifier are handled."""
        assert camel_case_to_title("MySQLIOCheck") == "MySQL IO Check"

    def test_mongodb_prefix(self):
        """Assert MongoDB is kept as a single compound name."""
        assert camel_case_to_title("MongoDBReplicaLag") == "MongoDB Replica Lag"

    def test_already_single_word_lowercase(self):
        """Assert a lowercase word is returned unchanged."""
        assert camel_case_to_title("alert") == "alert"


class TestNormalizeAlertEntry:
    """Test normalization of flexible alert frontmatter entries."""

    def test_string_entry(self):
        """Assert a string entry produces an AlertInfo with derived label."""
        result = normalize_alert_entry("HighCPUUsage")
        assert result == AlertInfo(name="HighCPUUsage", label="High CPU Usage")

    def test_dict_with_label(self):
        """Assert a dict with explicit label uses that label."""
        result = normalize_alert_entry({"name": "abc", "label": "Custom Label"})
        assert result == AlertInfo(name="abc", label="Custom Label")

    def test_dict_without_label(self):
        """Assert a dict without label derives label from name."""
        result = normalize_alert_entry({"name": "HighCPU"})
        assert result == AlertInfo(name="HighCPU", label="High CPU")

    def test_invalid_type_returns_none(self):
        """Assert a non-string, non-dict entry returns None."""
        assert normalize_alert_entry(42) is None

    def test_none_returns_none(self):
        """Assert None input returns None."""
        assert normalize_alert_entry(None) is None

    def test_dict_missing_name_returns_none(self):
        """Assert a dict missing the name key returns None."""
        assert normalize_alert_entry({"label": "foo"}) is None

    def test_empty_string_returns_none(self):
        """Assert an empty string returns None."""
        assert normalize_alert_entry("") is None


class TestCollectGroupedAlerts:
    """Test the snippet-to-grouped-alerts collection logic."""

    @staticmethod
    def _make_snippet(meta):
        """Create a mock snippet object with the given meta dict."""
        return SimpleNamespace(meta=meta)

    def test_basic_grouping(self):
        """Assert alerts are grouped by service type."""
        snippets = [
            self._make_snippet(
                {
                    "alerts": ["PostgreSQLLockConflicts"],
                    "service_type": "postgresql",
                }
            ),
            self._make_snippet(
                {
                    "alerts": ["HighCPUUsage"],
                    "service_type": "generic",
                }
            ),
        ]
        result = collect_grouped_alerts(snippets)
        assert AlertServiceType.POSTGRESQL in result
        assert AlertServiceType.GENERIC in result
        assert len(result[AlertServiceType.POSTGRESQL]) == 1
        assert result[AlertServiceType.POSTGRESQL][0].name == "PostgreSQLLockConflicts"

    def test_snippet_without_alerts_skipped(self):
        """Assert snippets without alerts metadata are skipped."""
        snippets = [
            self._make_snippet({"title": "some snippet"}),
        ]
        result = collect_grouped_alerts(snippets)
        assert len(result) == 0

    def test_empty_alerts_list_skipped(self):
        """Assert snippets with empty alerts list are skipped."""
        snippets = [
            self._make_snippet({"alerts": [], "service_type": "mysql"}),
        ]
        result = collect_grouped_alerts(snippets)
        assert len(result) == 0

    def test_missing_service_type_defaults_to_generic(self):
        """Assert missing service_type defaults to GENERIC."""
        snippets = [
            self._make_snippet({"alerts": ["TimeDrift"]}),
        ]
        result = collect_grouped_alerts(snippets)
        assert AlertServiceType.GENERIC in result
        assert result[AlertServiceType.GENERIC][0].name == "TimeDrift"

    def test_unknown_service_type_skipped(self):
        """Assert unknown service_type values are skipped."""
        snippets = [
            self._make_snippet(
                {
                    "alerts": ["SomeAlert"],
                    "service_type": "redis",
                }
            ),
        ]
        result = collect_grouped_alerts(snippets)
        assert len(result) == 0

    def test_dedup_alerts_across_snippets(self):
        """Assert duplicate alert names are deduplicated."""
        snippets = [
            self._make_snippet(
                {
                    "alerts": ["HighCPUUsage"],
                    "service_type": "generic",
                }
            ),
            self._make_snippet(
                {
                    "alerts": ["HighCPUUsage"],
                    "service_type": "generic",
                }
            ),
        ]
        result = collect_grouped_alerts(snippets)
        assert len(result[AlertServiceType.GENERIC]) == 1

    def test_dict_alert_entries(self):
        """Assert dict alert entries are normalized alongside strings."""
        snippets = [
            self._make_snippet(
                {
                    "alerts": [
                        {"name": "custom", "label": "Custom Alert"},
                        "HighCPUUsage",
                    ],
                    "service_type": "generic",
                }
            ),
        ]
        result = collect_grouped_alerts(snippets)
        alerts = result[AlertServiceType.GENERIC]
        names = {a.name for a in alerts}
        assert names == {"custom", "HighCPUUsage"}

    def test_invalid_alert_entries_skipped(self):
        """Assert invalid alert entries are skipped gracefully."""
        snippets = [
            self._make_snippet(
                {
                    "alerts": [42, None, "ValidAlert"],
                    "service_type": "mysql",
                }
            ),
        ]
        result = collect_grouped_alerts(snippets)
        assert len(result[AlertServiceType.MYSQL]) == 1
        assert result[AlertServiceType.MYSQL][0].name == "ValidAlert"

    def test_alerts_sorted_by_label(self):
        """Assert alerts within a group are sorted by label."""
        snippets = [
            self._make_snippet(
                {
                    "alerts": ["ZebraAlert", "AlphaAlert"],
                    "service_type": "generic",
                }
            ),
        ]
        result = collect_grouped_alerts(snippets)
        labels = [a.label for a in result[AlertServiceType.GENERIC]]
        assert labels == sorted(labels)

    def test_no_snippets(self):
        """Assert empty snippet list produces empty result."""
        result = collect_grouped_alerts([])
        assert len(result) == 0


class TestFilterSnippetsForAlert:
    """Test filtering snippets by alert name."""

    @staticmethod
    def _make_snippet(meta):
        """Create a mock snippet object with the given meta dict."""
        return SimpleNamespace(meta=meta)

    def test_filters_matching_snippets(self):
        """Assert only snippets declaring the alert are returned."""
        s1 = self._make_snippet({"alerts": ["HighCPU"]})
        s2 = self._make_snippet({"alerts": ["LowDisk"]})
        s3 = self._make_snippet({"alerts": ["HighCPU", "LowDisk"]})
        matched, alert_info = filter_snippets_for_alert([s1, s2, s3], "HighCPU")
        assert matched == [s1, s3]
        assert alert_info.name == "HighCPU"

    def test_no_match_raises_not_found(self):
        """Assert ``HTTPNotFoundException`` when no snippet matches."""
        s1 = self._make_snippet({"alerts": ["HighCPU"]})
        with pytest.raises(HTTPNotFoundException):
            filter_snippets_for_alert([s1], "NonExistentAlert")

    def test_empty_snippets_raises_not_found(self):
        """Assert ``HTTPNotFoundException`` for empty snippet list."""
        with pytest.raises(HTTPNotFoundException):
            filter_snippets_for_alert([], "AnyAlert")

    def test_dict_alert_entries_matched(self):
        """Assert dict-style alert entries are matched by name."""
        s1 = self._make_snippet({"alerts": [{"name": "HighCPU", "label": "High CPU"}]})
        matched, alert_info = filter_snippets_for_alert([s1], "HighCPU")
        assert matched == [s1]
        assert alert_info.label == "High CPU"

    def test_snippets_without_alerts_skipped(self):
        """Assert snippets with no alerts metadata are skipped."""
        s1 = self._make_snippet({"title": "no alerts"})
        s2 = self._make_snippet({"alerts": ["HighCPU"]})
        matched, _ = filter_snippets_for_alert([s1, s2], "HighCPU")
        assert matched == [s2]

    def test_mixed_approved_unapproved_all_returned(self):
        """Assert both approved and unapproved snippets are returned."""
        s1 = SimpleNamespace(meta={"alerts": ["HighCPU"]}, is_approved=True)
        s2 = SimpleNamespace(meta={"alerts": ["HighCPU"]}, is_approved=False)
        matched, _ = filter_snippets_for_alert([s1, s2], "HighCPU")
        assert len(matched) == EXPECTED_BOTH_SNIPPETS


class TestFilterSnippetsForAlertAlertInfo:
    """Test that ``filter_snippets_for_alert`` returns correct ``AlertInfo``."""

    @staticmethod
    def _make_snippet(meta):
        """Create a mock snippet object with the given meta dict."""
        return SimpleNamespace(meta=meta)

    def test_string_alert_returns_derived_label(self):
        """Assert ``AlertInfo`` label is derived from a string alert entry."""
        s = self._make_snippet({"alerts": ["HighCPUUsage"]})
        _, alert_info = filter_snippets_for_alert([s], "HighCPUUsage")
        assert alert_info == AlertInfo(name="HighCPUUsage", label="High CPU Usage")

    def test_dict_alert_returns_explicit_label(self):
        """Assert ``AlertInfo`` uses the explicit label from a dict entry."""
        s = self._make_snippet(
            {"alerts": [{"name": "HighCPU", "label": "Custom Label"}]}
        )
        _, alert_info = filter_snippets_for_alert([s], "HighCPU")
        assert alert_info == AlertInfo(name="HighCPU", label="Custom Label")

    def test_first_matching_snippet_provides_info(self):
        """Assert the first snippet's alert metadata is used for the label."""
        s1 = self._make_snippet(
            {"alerts": [{"name": "Alert1", "label": "First Label"}]}
        )
        s2 = self._make_snippet(
            {"alerts": [{"name": "Alert1", "label": "Second Label"}]}
        )
        _, alert_info = filter_snippets_for_alert([s1, s2], "Alert1")
        assert alert_info.label == "First Label"
