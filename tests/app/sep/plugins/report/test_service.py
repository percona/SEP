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

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.sep.clients.pmm import PMMRemoteAPI
from app.sep.plugins.report.models import (
    InventorySection,
    ReportData,
    ReportMetadata,
    ServiceStatus,
)
from app.sep.plugins.report.service import (
    _build_allowed_check_prefixes,
    _collect_section,
    _fetch_base_inventory,
    _find_labels,
    _get_metrics_datasource,
    _interval_ms,
    _parse_failed_checks,
    _refresh_checks,
    collect_advisors,
    collect_inventory,
    collect_storage,
    collect_uptime,
    generate_report,
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


# _parse_failed_checks
class TestParseFailedChecks:
    """Test the ``_parse_failed_checks`` helper."""

    _NODES = {"n1": {"name": "node-a"}}
    _SERVICES = {"s1": {"name": "mysql-prod"}}

    def test_groups_results_by_check_name(self):
        """Assert results are grouped into lists keyed by check_name."""
        raw = [
            {
                "check_name": "check_a",
                "labels": {"node_id": "n1", "service_id": "s1"},
                "severity": "SEVERITY_WARNING",
            },
            {
                "check_name": "check_a",
                "labels": {"node_id": "n1", "service_id": "s1"},
                "severity": "SEVERITY_CRITICAL",
            },
            {
                "check_name": "check_b",
                "labels": {},
            },
        ]
        result = _parse_failed_checks(raw, self._NODES, self._SERVICES)
        expected_check_a_count = 2
        assert len(result["check_a"]) == expected_check_a_count
        assert len(result["check_b"]) == 1

    def test_resolves_node_and_service_names(self):
        """Assert node_name and service_name are resolved from lookup dicts."""
        raw = [
            {
                "check_name": "c",
                "labels": {"node_id": "n1", "service_id": "s1"},
            },
        ]
        result = _parse_failed_checks(raw, self._NODES, self._SERVICES)
        fc = result["c"][0]
        assert fc.node_name == "node-a"
        assert fc.service_name == "mysql-prod"

    def test_handles_missing_node_and_service(self):
        """Assert None when node_id/service_id are not in lookup dicts."""
        raw = [
            {
                "check_name": "c",
                "labels": {"node_id": "unknown", "service_id": "unknown"},
            },
        ]
        result = _parse_failed_checks(raw, self._NODES, self._SERVICES)
        fc = result["c"][0]
        assert fc.node_name is None
        assert fc.service_name is None

    def test_returns_empty_dict_for_empty_input(self):
        """Assert empty dict when no failed checks are provided."""
        assert _parse_failed_checks([], {}, {}) == {}


# _build_allowed_check_prefixes
class TestBuildAllowedCheckPrefixes:
    """Test the ``_build_allowed_check_prefixes`` helper."""

    def test_includes_base_types(self):
        """Assert active types are included as-is."""
        result = _build_allowed_check_prefixes({"postgresql"})
        assert "postgresql" in result

    def test_mysql_adds_innodb_and_replica(self):
        """Assert mysql adds extra prefixes innodb and replica."""
        result = _build_allowed_check_prefixes({"mysql"})
        assert "innodb" in result
        assert "replica" in result
        assert "mysql" in result

    def test_mongodb_adds_mongo(self):
        """Assert mongodb adds the extra mongo prefix."""
        result = _build_allowed_check_prefixes({"mongodb"})
        assert "mongo" in result
        assert "mongodb" in result

    def test_combined_types(self):
        """Assert all extras are combined for multiple service types."""
        result = _build_allowed_check_prefixes({"mysql", "mongodb", "postgresql"})
        expected_count = 6
        assert len(result) == expected_count
        assert {
            "mysql",
            "mongodb",
            "postgresql",
            "innodb",
            "replica",
            "mongo",
        } == result

    def test_empty_set(self):
        """Assert empty input returns empty set."""
        assert _build_allowed_check_prefixes(set()) == set()


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


# collect_advisors
class TestCollectAdvisors:
    """Test the ``collect_advisors`` collector."""

    _ACTIVE_TYPES = {"mysql"}
    _NODES = {"n1": {"name": "node-a"}}
    _SERVICES = {"s1": {"name": "mysql-prod"}}

    @pytest.mark.asyncio
    async def test_counts_enabled_checks(self, pmm_api):
        """Assert total_checks reflects only enabled, relevant checks."""
        pmm_api.get_advisor_checks.return_value = [
            {
                "name": "mysql_check1",
                "family": "ADVISOR_mysql",
                "description": "d",
                "summary": "s",
            },
            {"name": "mysql_check2", "family": "ADVISOR_mysql", "disabled": True},
            {"name": "pg_check", "family": "ADVISOR_postgresql"},
        ]
        pmm_api.get_failed_advisor_checks.return_value = []
        result = await collect_advisors(
            pmm_api, self._ACTIVE_TYPES, self._NODES, self._SERVICES
        )
        assert result.total_checks == 1
        assert result.total_failed == 0

    @pytest.mark.asyncio
    async def test_groups_checks_into_families(self, pmm_api):
        """Assert checks are grouped by family key."""
        pmm_api.get_advisor_checks.return_value = [
            {"name": "mysql_c1", "family": "ADVISOR_mysql"},
            {"name": "mysql_c2", "family": "ADVISOR_mysql"},
        ]
        pmm_api.get_failed_advisor_checks.return_value = []
        result = await collect_advisors(
            pmm_api, self._ACTIVE_TYPES, self._NODES, self._SERVICES
        )
        assert len(result.families) == 1
        expected_checks_in_family = 2
        assert len(result.families[0].checks) == expected_checks_in_family
        assert result.families[0].display_name == "MySQL"

    @pytest.mark.asyncio
    async def test_assigns_failed_checks_to_families(self, pmm_api):
        """Assert failed checks are matched to the correct family."""
        pmm_api.get_advisor_checks.return_value = [
            {"name": "mysql_c1", "family": "ADVISOR_mysql"},
        ]
        pmm_api.get_failed_advisor_checks.return_value = [
            {
                "check_name": "mysql_c1",
                "labels": {"node_id": "n1"},
                "severity": "SEVERITY_WARNING",
            },
        ]
        result = await collect_advisors(
            pmm_api, self._ACTIVE_TYPES, self._NODES, self._SERVICES
        )
        assert result.total_failed == 1
        assert "mysql_c1" in result.families[0].failed

    @pytest.mark.asyncio
    async def test_filters_by_allowed_prefix_when_no_family(self, pmm_api):
        """Assert checks without family are filtered by name prefix."""
        pmm_api.get_advisor_checks.return_value = [
            {"name": "mysql_standalone"},
            {"name": "innodb_buffer"},
            {"name": "pg_stat"},
        ]
        pmm_api.get_failed_advisor_checks.return_value = []
        result = await collect_advisors(
            pmm_api, self._ACTIVE_TYPES, self._NODES, self._SERVICES
        )
        expected_checks = 2
        assert result.total_checks == expected_checks

    @pytest.mark.asyncio
    async def test_refresh_triggers_start_advisor_checks(self, pmm_api):
        """Assert refresh=True triggers check refreshes."""
        pmm_api.get_advisor_checks.return_value = [
            {"name": "mysql_c1", "family": "ADVISOR_mysql"},
        ]
        pmm_api.get_failed_advisor_checks.return_value = []
        result = await collect_advisors(
            pmm_api, self._ACTIVE_TYPES, self._NODES, self._SERVICES, refresh=True
        )
        pmm_api.start_advisor_checks.assert_awaited_once()
        assert result.refresh_issues == []

    @pytest.mark.asyncio
    async def test_no_refresh_by_default(self, pmm_api):
        """Assert refresh is not triggered by default."""
        pmm_api.get_advisor_checks.return_value = []
        pmm_api.get_failed_advisor_checks.return_value = []
        await collect_advisors(pmm_api, self._ACTIVE_TYPES, self._NODES, self._SERVICES)
        pmm_api.start_advisor_checks.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_checks(self, pmm_api):
        """Assert empty response yields zero-count section."""
        pmm_api.get_advisor_checks.return_value = []
        pmm_api.get_failed_advisor_checks.return_value = []
        result = await collect_advisors(
            pmm_api, self._ACTIVE_TYPES, self._NODES, self._SERVICES
        )
        assert result.total_checks == 0
        assert result.families == []


# collect_storage
class TestCollectStorage:
    """Test the ``collect_storage`` collector."""

    _DS_ID = 42
    _DS_UID = "metrics-uid"

    def _make_used_frame(self, *, node_id="node-1", mountpoint="/", values=None):
        if values is None:
            values = [[100, 200, 300], [500_000, 600_000, 700_000]]
        return {
            "schema": {
                "fields": [
                    {"name": "Time"},
                    {
                        "name": "Value",
                        "labels": {"node_id": node_id, "mountpoint": mountpoint},
                    },
                ],
            },
            "data": {"values": values},
        }

    def _make_total_frame(self, *, total_bytes=1_000_000):
        return {
            "schema": {"fields": [{"name": "Time"}, {"name": "Value"}]},
            "data": {"values": [[100], [total_bytes]]},
        }

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_node_ids(self, pmm_api):
        """Assert empty StorageSection when no node IDs are provided."""
        result = await collect_storage(
            pmm_api, [], "now-7d", "now", self._DS_ID, self._DS_UID
        )
        assert result.entries == []
        pmm_api.query_grafana_datasource.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_calculates_usage_percentage(self, pmm_api):
        """Assert usage_percentage is correctly computed."""
        total_bytes = 1_000_000
        pmm_api.query_grafana_datasource.return_value = {
            "A": {"frames": [self._make_used_frame()]},
            "B": {"frames": [self._make_total_frame(total_bytes=total_bytes)]},
        }
        result = await collect_storage(
            pmm_api, ["node-1"], "now-7d", "now", self._DS_ID, self._DS_UID
        )
        assert len(result.entries) == 1
        expected_pct = 70
        assert result.entries[0].usage_percentage == expected_pct

    @pytest.mark.asyncio
    async def test_entries_sorted_by_usage_descending(self, pmm_api):
        """Assert entries are sorted by usage_percentage highest first."""
        total = 1_000_000
        pmm_api.query_grafana_datasource.return_value = {
            "A": {
                "frames": [
                    self._make_used_frame(
                        node_id="n1", mountpoint="/a", values=[[1], [300_000]]
                    ),
                    self._make_used_frame(
                        node_id="n2", mountpoint="/b", values=[[1], [900_000]]
                    ),
                ],
            },
            "B": {
                "frames": [
                    self._make_total_frame(total_bytes=total),
                    self._make_total_frame(total_bytes=total),
                ],
            },
        }
        result = await collect_storage(
            pmm_api, ["n1", "n2"], "now-7d", "now", self._DS_ID, self._DS_UID
        )
        assert result.entries[0].usage_percentage > result.entries[1].usage_percentage

    @pytest.mark.asyncio
    async def test_skips_frames_without_node_id(self, pmm_api):
        """Assert frames missing node_id label are skipped."""
        frame = self._make_used_frame(node_id="")
        pmm_api.query_grafana_datasource.return_value = {
            "A": {"frames": [frame]},
            "B": {"frames": []},
        }
        result = await collect_storage(
            pmm_api, ["n1"], "now-7d", "now", self._DS_ID, self._DS_UID
        )
        assert result.entries == []

    @pytest.mark.asyncio
    async def test_zero_pct_when_no_total(self, pmm_api):
        """Assert 0% usage when total_bytes is unavailable."""
        pmm_api.query_grafana_datasource.return_value = {
            "A": {"frames": [self._make_used_frame()]},
            "B": {"frames": []},
        }
        result = await collect_storage(
            pmm_api, ["node-1"], "now-7d", "now", self._DS_ID, self._DS_UID
        )
        assert result.entries[0].usage_percentage == 0


# collect_uptime
class TestCollectUptime:
    """Test the ``collect_uptime`` collector."""

    _DS_ID = 42
    _DS_UID = "metrics-uid"

    def _make_uptime_frame(self, *, svc_name="mysql-prod", seconds=86400):
        return {
            "schema": {
                "fields": [
                    {"name": "Time"},
                    {"name": "Value", "labels": {"service_name": svc_name}},
                ],
            },
            "data": {"values": [[100], [seconds]]},
        }

    @pytest.mark.asyncio
    async def test_parses_uptime_entries(self, pmm_api):
        """Assert uptime entries are parsed from datasource frames."""
        one_day_seconds = 86400
        pmm_api.query_grafana_datasource.return_value = {
            "A": {"frames": [self._make_uptime_frame(seconds=one_day_seconds)]},
            "B": {"frames": []},
            "C": {"frames": []},
        }
        result = await collect_uptime(
            pmm_api, "now-7d", "now", self._DS_ID, self._DS_UID
        )
        assert len(result.entries) == 1
        assert result.entries[0].service_name == "mysql-prod"
        assert result.entries[0].uptime == timedelta(days=1)

    @pytest.mark.asyncio
    async def test_excludes_pmm_server_postgresql(self, pmm_api):
        """Assert pmm-server-postgresql is filtered out."""
        pmm_api.query_grafana_datasource.return_value = {
            "A": {
                "frames": [self._make_uptime_frame(svc_name="pmm-server-postgresql")]
            },
            "B": {"frames": []},
            "C": {"frames": []},
        }
        result = await collect_uptime(
            pmm_api, "now-7d", "now", self._DS_ID, self._DS_UID
        )
        assert result.entries == []

    @pytest.mark.asyncio
    async def test_entries_sorted_by_uptime_descending(self, pmm_api):
        """Assert entries are sorted by uptime highest first."""
        short_uptime = 100
        long_uptime = 90000
        pmm_api.query_grafana_datasource.return_value = {
            "A": {
                "frames": [
                    self._make_uptime_frame(svc_name="svc-short", seconds=short_uptime),
                    self._make_uptime_frame(svc_name="svc-long", seconds=long_uptime),
                ],
            },
            "B": {"frames": []},
            "C": {"frames": []},
        }
        result = await collect_uptime(
            pmm_api, "now-7d", "now", self._DS_ID, self._DS_UID
        )
        assert result.entries[0].service_name == "svc-long"

    @pytest.mark.asyncio
    async def test_collects_across_all_ref_ids(self, pmm_api):
        """Assert frames from A, B, and C ref IDs are all collected."""
        seconds = 3600
        pmm_api.query_grafana_datasource.return_value = {
            "A": {
                "frames": [self._make_uptime_frame(svc_name="mongo-1", seconds=seconds)]
            },
            "B": {
                "frames": [self._make_uptime_frame(svc_name="pg-1", seconds=seconds)]
            },
            "C": {
                "frames": [self._make_uptime_frame(svc_name="mysql-1", seconds=seconds)]
            },
        }
        result = await collect_uptime(
            pmm_api, "now-7d", "now", self._DS_ID, self._DS_UID
        )
        expected_count = 3
        assert len(result.entries) == expected_count

    @pytest.mark.asyncio
    async def test_empty_frames(self, pmm_api):
        """Assert empty frames yield empty section."""
        pmm_api.query_grafana_datasource.return_value = {
            "A": {"frames": []},
            "B": {"frames": []},
            "C": {"frames": []},
        }
        result = await collect_uptime(
            pmm_api, "now-7d", "now", self._DS_ID, self._DS_UID
        )
        assert result.entries == []


# collect_inventory
class TestCollectInventory:
    """Test the ``collect_inventory`` collector."""

    def _make_service(
        self,
        *,
        name="mysql-prod",
        svc_type="mysql",
        node_name="host-1",
        node_id="n1",
        agents=None,
    ):
        return {
            "service_name": name,
            "service_type": svc_type,
            "node_name": node_name,
            "node_id": node_id,
            "agents": agents or [],
        }

    @pytest.mark.asyncio
    async def test_returns_inventory_entries(self, pmm_api):
        """Assert services are returned as InventoryServiceEntry."""
        pmm_api.get_inventory_services_with_agents.return_value = [
            self._make_service(),
        ]
        result = await collect_inventory(pmm_api)
        assert len(result.entries) == 1
        assert result.entries[0].service_name == "mysql-prod"
        assert result.entries[0].status == ServiceStatus.OK

    @pytest.mark.asyncio
    async def test_filters_pmm_server_services(self, pmm_api):
        """Assert pmm-server and pmm-server-postgresql are filtered out."""
        pmm_api.get_inventory_services_with_agents.return_value = [
            self._make_service(name="pmm-server"),
            self._make_service(name="pmm-server-postgresql"),
            self._make_service(name="mysql-prod"),
        ]
        result = await collect_inventory(pmm_api)
        assert len(result.entries) == 1
        assert result.entries[0].service_name == "mysql-prod"

    @pytest.mark.asyncio
    async def test_filters_pmm_server_node_id(self, pmm_api):
        """Assert services with node_id='pmm-server' are filtered out."""
        pmm_api.get_inventory_services_with_agents.return_value = [
            self._make_service(name="internal-svc", node_id="pmm-server"),
        ]
        result = await collect_inventory(pmm_api)
        assert result.entries == []

    @pytest.mark.asyncio
    async def test_not_ok_when_pmm_agent_disconnected(self, pmm_api):
        """Assert NOT_OK when pmm-agent is not connected."""
        pmm_api.get_inventory_services_with_agents.return_value = [
            self._make_service(
                agents=[
                    {"agent_type": "pmm-agent", "is_connected": False},
                ]
            ),
        ]
        result = await collect_inventory(pmm_api)
        assert result.entries[0].status == ServiceStatus.NOT_OK

    @pytest.mark.asyncio
    async def test_not_ok_when_non_pmm_agent_bad_status(self, pmm_api):
        """Assert NOT_OK when a non-pmm-agent has a non-running status."""
        pmm_api.get_inventory_services_with_agents.return_value = [
            self._make_service(
                agents=[
                    {"agent_type": "mysqld_exporter", "status": "WAITING"},
                ]
            ),
        ]
        result = await collect_inventory(pmm_api)
        assert result.entries[0].status == ServiceStatus.NOT_OK

    @pytest.mark.asyncio
    async def test_ok_when_agent_running(self, pmm_api):
        """Assert OK when agent status is RUNNING."""
        pmm_api.get_inventory_services_with_agents.return_value = [
            self._make_service(
                agents=[
                    {"agent_type": "mysqld_exporter", "status": "RUNNING"},
                ]
            ),
        ]
        result = await collect_inventory(pmm_api)
        assert result.entries[0].status == ServiceStatus.OK

    @pytest.mark.asyncio
    async def test_ok_when_agent_status_done(self, pmm_api):
        """Assert OK when agent status is AGENT_STATUS_DONE (v3 format)."""
        pmm_api.get_inventory_services_with_agents.return_value = [
            self._make_service(
                agents=[
                    {"agent_type": "mysqld_exporter", "status": "AGENT_STATUS_DONE"},
                ]
            ),
        ]
        result = await collect_inventory(pmm_api)
        assert result.entries[0].status == ServiceStatus.OK

    @pytest.mark.asyncio
    async def test_sorted_by_type_and_name(self, pmm_api):
        """Assert entries are sorted by service_type then service_name."""
        pmm_api.get_inventory_services_with_agents.return_value = [
            self._make_service(name="z-mysql", svc_type="mysql"),
            self._make_service(name="a-pg", svc_type="postgresql"),
            self._make_service(name="a-mysql", svc_type="mysql"),
        ]
        result = await collect_inventory(pmm_api)
        names = [e.service_name for e in result.entries]
        assert names == ["a-mysql", "z-mysql", "a-pg"]

    @pytest.mark.asyncio
    async def test_empty_services(self, pmm_api):
        """Assert empty input yields empty section."""
        pmm_api.get_inventory_services_with_agents.return_value = []
        result = await collect_inventory(pmm_api)
        assert result.entries == []


# _fetch_base_inventory
class TestFetchBaseInventory:
    """Test the ``_fetch_base_inventory`` helper."""

    @pytest.mark.asyncio
    async def test_v3_endpoints(self, pmm_api):
        """Assert v3 GET endpoints are used when PMM >= v3."""
        pmm_api.is_older_than_v3.return_value = False
        pmm_api.get.side_effect = [
            {"generic": [{"node_id": "n1", "node_name": "host-a"}]},
            {
                "mysql": [
                    {"service_id": "s1", "service_name": "mysql-a", "node_id": "n1"}
                ]
            },
        ]
        nodes, services, active_types = await _fetch_base_inventory(pmm_api)
        assert "n1" in nodes
        assert "s1" in services
        assert "mysql" in active_types
        pmm_api.get.assert_any_await("/v1/inventory/nodes")
        pmm_api.get.assert_any_await("/v1/inventory/services")

    @pytest.mark.asyncio
    async def test_v2_endpoints(self, pmm_api):
        """Assert v2 POST endpoints are used when PMM < v3."""
        pmm_api.is_older_than_v3.return_value = True
        pmm_api.post.side_effect = [
            {"generic": [{"node_id": "n1", "node_name": "host-a"}]},
            {
                "mysql": [
                    {"service_id": "s1", "service_name": "mysql-a", "node_id": "n1"}
                ]
            },
        ]
        nodes, services, _types = await _fetch_base_inventory(pmm_api)
        assert "n1" in nodes
        assert "s1" in services
        pmm_api.post.assert_any_await("/v1/inventory/Nodes/List", json={})
        pmm_api.post.assert_any_await("/v1/inventory/Services/List", json={})

    @pytest.mark.asyncio
    async def test_filters_pmm_server_nodes(self, pmm_api):
        """Assert nodes with pmm-server IDs or names are excluded."""
        pmm_api.is_older_than_v3.return_value = False
        pmm_api.get.side_effect = [
            {
                "generic": [
                    {"node_id": "pmm-server", "node_name": "pmm-server"},
                    {"node_id": "n1", "node_name": "host-a"},
                ],
            },
            {"mysql": []},
        ]
        nodes, _, _ = await _fetch_base_inventory(pmm_api)
        assert "pmm-server" not in nodes
        assert "n1" in nodes

    @pytest.mark.asyncio
    async def test_filters_pmm_server_services(self, pmm_api):
        """Assert services named pmm-server* or on pmm-server node are excluded."""
        pmm_api.is_older_than_v3.return_value = False
        pmm_api.get.side_effect = [
            {"generic": []},
            {
                "mysql": [
                    {
                        "service_id": "s1",
                        "service_name": "pmm-server-postgresql",
                        "node_id": "n1",
                    },
                    {
                        "service_id": "s2",
                        "service_name": "my-svc",
                        "node_id": "pmm-server",
                    },
                    {"service_id": "s3", "service_name": "prod-mysql", "node_id": "n2"},
                ],
            },
        ]
        _, services, _ = await _fetch_base_inventory(pmm_api)
        assert "s1" not in services
        assert "s2" not in services
        assert "s3" in services

    @pytest.mark.asyncio
    async def test_collects_active_service_types(self, pmm_api):
        """Assert active types are collected from non-filtered services."""
        pmm_api.is_older_than_v3.return_value = False
        pmm_api.get.side_effect = [
            {"generic": []},
            {
                "mysql": [{"service_id": "s1", "service_name": "a", "node_id": "n1"}],
                "postgresql": [
                    {"service_id": "s2", "service_name": "b", "node_id": "n2"}
                ],
            },
        ]
        _, _, types = await _fetch_base_inventory(pmm_api)
        assert types == {"mysql", "postgresql"}


# _collect_section
class TestCollectSection:
    """Test the ``_collect_section`` dispatcher."""

    @pytest.mark.asyncio
    async def test_populates_section_on_report(self, pmm_api):
        """Assert a successful collector result is set on the report object."""
        report = ReportData(
            metadata=ReportMetadata(title="t", generated_at="2026-01-01T00:00:00Z"),
        )
        section = InventorySection(entries=[])
        with patch(
            "app.sep.plugins.report.service.collect_inventory",
            new_callable=AsyncMock,
            return_value=section,
        ):
            await _collect_section(
                "inventory",
                report,
                pmm_api=pmm_api,
                start_ts=0,
                stop_ts=0,
                since="now-7d",
                until="now",
                ds_id=1,
                ds_uid="u",
                nodes_raw={},
                services_raw={},
                active_types=set(),
                refresh=False,
            )
        assert report.inventory is section

    @pytest.mark.asyncio
    async def test_ignores_unknown_section(self, pmm_api):
        """Assert unknown section names are silently skipped."""
        report = ReportData(
            metadata=ReportMetadata(title="t", generated_at="2026-01-01T00:00:00Z"),
        )
        await _collect_section(
            "nonexistent",
            report,
            pmm_api=pmm_api,
            start_ts=0,
            stop_ts=0,
            since="now-7d",
            until="now",
            ds_id=1,
            ds_uid="u",
            nodes_raw={},
            services_raw={},
            active_types=set(),
            refresh=False,
        )

    @pytest.mark.asyncio
    async def test_logs_and_continues_on_error(self, pmm_api):
        """Assert collector errors are caught and logged."""
        report = ReportData(
            metadata=ReportMetadata(title="t", generated_at="2026-01-01T00:00:00Z"),
        )
        with patch(
            "app.sep.plugins.report.service.collect_inventory",
            new_callable=AsyncMock,
            side_effect=OSError("connection failed"),
        ):
            await _collect_section(
                "inventory",
                report,
                pmm_api=pmm_api,
                start_ts=0,
                stop_ts=0,
                since="now-7d",
                until="now",
                ds_id=1,
                ds_uid="u",
                nodes_raw={},
                services_raw={},
                active_types=set(),
                refresh=False,
            )
        assert report.inventory.entries == []


# generate_report
class TestGenerateReport:
    """Test the top-level ``generate_report`` orchestrator."""

    @pytest.mark.asyncio
    async def test_returns_report_data(self, pmm_api):
        """Assert a ReportData object is returned."""
        pmm_api.is_older_than_v3.return_value = False
        pmm_api.get.side_effect = [
            {"generic": [{"node_id": "n1", "node_name": "host-a"}]},
            {"mysql": [{"service_id": "s1", "service_name": "m", "node_id": "n1"}]},
        ]
        pmm_api.get_grafana_datasources.return_value = [
            {"name": "Metrics", "id": 1, "uid": "u1"},
        ]
        with patch(
            "app.sep.plugins.report.service._collect_section",
            new_callable=AsyncMock,
        ):
            report = await generate_report(pmm_api)
        assert isinstance(report, ReportData)
        assert report.metadata.title == "Health and Security Report"

    @pytest.mark.asyncio
    async def test_sets_full_and_refresh_flags(self, pmm_api):
        """Assert full and refresh flags are propagated to the report."""
        pmm_api.is_older_than_v3.return_value = False
        pmm_api.get.side_effect = [{"g": []}, {"m": []}]
        pmm_api.get_grafana_datasources.return_value = [
            {"name": "Metrics", "id": 1, "uid": "u1"},
        ]
        with patch(
            "app.sep.plugins.report.service._collect_section",
            new_callable=AsyncMock,
        ):
            report = await generate_report(pmm_api, full=True, refresh=True)
        assert report.full is True
        assert report.refresh is True

    @pytest.mark.asyncio
    async def test_handles_inventory_fetch_failure(self, pmm_api):
        """Assert report is still generated when base inventory fetch fails."""
        pmm_api.is_older_than_v3.return_value = False
        pmm_api.get.side_effect = OSError("connection refused")
        pmm_api.get_grafana_datasources.return_value = []
        with patch(
            "app.sep.plugins.report.service._collect_section",
            new_callable=AsyncMock,
        ):
            report = await generate_report(pmm_api)
        assert report.monitored.total_nodes == 0
        assert report.monitored.total_services == 0

