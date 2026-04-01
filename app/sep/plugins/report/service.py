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

"""Orchestrate report data collection from PMM.

This module replaces the legacy GAS ``report.py`` CLI by delegating all HTTP
calls to :class:`~app.sep.clients.pmm.PMMRemoteAPI` and returning structured
:mod:`~app.sep.plugins.report.models` objects.
"""

import logging
from typing import Any

from app.sep.clients.pmm import PMMRemoteAPI

from .models import (
    AdvisorCheck,
    AdvisorFamily,
    AdvisorSection,
    FailedCheck,
    InventorySection,
    InventoryServiceEntry,
    ServiceStatus,
)

logger = logging.getLogger(__name__)

SERVICE_NAMES: dict[str, str] = {
    "agent": "Agent",
    "backup": "Backup",
    "external": "External",
    "generic": "Generic",
    "haproxy": "HAProxy",
    "mongodb": "MongoDB",
    "mysql": "MySQL",
    "remote": "Remote",
    "postgresql": "PostgreSQL",
    "proxysql": "ProxySQL",
}

_PMM_SERVER_FILTER = {"pmm-server", "pmm-server-postgresql"}

def _find_labels(schema_fields: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract PMM labels from Grafana frame schema fields."""
    for field in schema_fields:
        labels = {
            k: v
            for k, v in field.get("labels", {}).items()
            if field.get("name") != "Time"
        }
        if labels:
            return labels
    return {}


def _interval_ms(start: str, end: str) -> tuple[int, int]:
    """Convert relative time strings (``now-7d``, ``now``) to epoch milliseconds."""
    now_ms = int(time.time() * 1000)

    def _parse(value: str) -> int:
        if value == "now":
            return now_ms
        if value.startswith("now-"):
            offset_str = value[4:]
            multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(offset_str[-1], 1)
            return now_ms - int(offset_str[:-1]) * multiplier * 1000
        raise ValueError(f"Unsupported time format: {value}")

    return _parse(start), _parse(end)


async def _get_metrics_datasource(
    pmm_api: PMMRemoteAPI,
) -> tuple[int, str]:
    """Return (datasource_id, datasource_uid) for the ``Metrics`` datasource."""
    datasources = await pmm_api.get_grafana_datasources()
    for ds in datasources:
        if ds.get("name") == "Metrics":
            return ds["id"], ds["uid"]
    raise LookupError("Metrics datasource not found in Grafana")


def _parse_failed_checks(
    raw_failed: list[dict[str, Any]],
    nodes: dict[str, dict[str, Any]],
    services: dict[str, dict[str, Any]],
) -> dict[str, list[FailedCheck]]:
    """Parse raw failed check results into structured objects grouped by name."""
    failed_by_name: dict[str, list[FailedCheck]] = {}
    for result in raw_failed:
        labels = result.get("labels", {})
        node_info = nodes.get(labels.get("node_id", ""), {})
        svc_info = services.get(labels.get("service_id", ""), {})
        fc = FailedCheck(
            name=result["check_name"],
            description=result.get("description", ""),
            summary=result.get("summary", ""),
            severity=result.get("severity", "SEVERITY_WARNING"),
            node_name=node_info.get("name"),
            node_id=labels.get("node_id"),
            service_name=svc_info.get("name"),
            service_id=labels.get("service_id"),
            read_more_url=result.get("read_more_url", ""),
        )
        failed_by_name.setdefault(fc.name, []).append(fc)
    return failed_by_name


def _build_allowed_check_prefixes(active_service_types: set[str]) -> set[str]:
    """Build the set of allowed check name prefixes from active service types."""
    extra: set[str] = set()
    if "mysql" in active_service_types:
        extra |= {"innodb", "replica"}
    if "mongodb" in active_service_types:
        extra.add("mongo")
    return active_service_types | extra


async def _refresh_checks(
    pmm_api: PMMRemoteAPI,
    raw_checks: list[dict[str, Any]],
) -> list[str]:
    """Trigger a refresh for each enabled check and return names that timed out."""
    issues: list[str] = []
    for raw in raw_checks:
        if raw.get("disabled"):
            continue
        try:
            await pmm_api.start_advisor_checks(names=[raw["name"]])
        except (KeyError, IndexError, OSError):
            logger.warning("Refresh timeout for check %s", raw["name"])
            issues.append(raw["name"])
    return issues


async def collect_advisors(
    pmm_api: PMMRemoteAPI,
    active_service_types: set[str],
    nodes: dict[str, dict[str, Any]],
    services: dict[str, dict[str, Any]],
    *,
    refresh: bool = False,
) -> AdvisorSection:
    """Fetch advisor checks and failed results from PMM.

    :param pmm_api: PMM API client.
    :param active_service_types: Set of service type keys present in the inventory
        (e.g. ``{"mysql", "mongodb"}``).
    :param nodes: Mapping of ``node_id`` to node info dicts.
    :param services: Mapping of ``service_id`` to service info dicts.
    :param refresh: When ``True``, trigger a refresh of each check before
        fetching failed results.
    :return: Populated advisor section.
    """
    raw_checks = await pmm_api.get_advisor_checks()
    refresh_issues = await _refresh_checks(pmm_api, raw_checks) if refresh else []
    raw_failed = await pmm_api.get_failed_advisor_checks()
    allowed = _build_allowed_check_prefixes(active_service_types)

    families: dict[str, AdvisorFamily] = {}
    checks: list[AdvisorCheck] = []

    for raw in raw_checks:
        if raw.get("disabled"):
            continue
        family = raw.get("family")
        if family:
            if family.split("_")[-1].lower() not in active_service_types:
                continue
        elif raw["name"].split("_")[0].lower() not in allowed:
            continue

        check = AdvisorCheck(
            name=raw["name"],
            description=raw.get("description", ""),
            summary=raw.get("summary", ""),
            family=family,
        )
        checks.append(check)

        if family and family not in families:
            display = SERVICE_NAMES.get(
                family.split("_")[-1].lower(),
                family.split("_")[-1].capitalize(),
            )
            families[family] = AdvisorFamily(family_key=family, display_name=display)
        if family:
            families[family].checks.append(check)

    checks.sort(key=lambda c: c.name)
    failed_by_name = _parse_failed_checks(raw_failed, nodes, services)

    for fam in families.values():
        fam.failed = {
            k: v
            for k, v in failed_by_name.items()
            if any(c.name == k for c in fam.checks)
        }

    return AdvisorSection(
        total_checks=len(checks),
        total_failed=len(failed_by_name),
        refresh_issues=refresh_issues,
        families=list(families.values()),
    )


async def collect_inventory(
    pmm_api: PMMRemoteAPI,
) -> InventorySection:
    """Fetch the inventory service list with agent status from PMM.

    :param pmm_api: PMM API client.
    :return: Populated inventory section.
    """
    raw_services = await pmm_api.get_inventory_services_with_agents()

    entries: list[InventoryServiceEntry] = []
    sorted_services = sorted(
        raw_services,
        key=lambda s: (s.get("service_type", ""), s.get("service_name", "")),
    )

    for svc in sorted_services:
        if svc.get("service_name") in _PMM_SERVER_FILTER:
            continue
        if svc.get("node_id") == "pmm-server":
            continue

        status = ServiceStatus.OK
        for agent in svc.get("agents", []):
            if agent.get("agent_type") == "pmm-agent" and not agent.get("is_connected"):
                status = ServiceStatus.NOT_OK
                break
            if agent.get("agent_type") != "pmm-agent" and agent.get("status") not in (
                "RUNNING",
                "DONE",
                "AGENT_STATUS_RUNNING",
                "AGENT_STATUS_DONE",
            ):
                status = ServiceStatus.NOT_OK
                break

        entries.append(
            InventoryServiceEntry(
                service_name=svc.get("service_name", ""),
                service_type=svc.get("service_type", ""),
                node_name=svc.get("node_name", ""),
                status=status,
            )
        )

    return InventorySection(entries=entries)


async def _fetch_base_inventory(
    pmm_api: PMMRemoteAPI,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], set[str]]:
    """Fetch nodes and services from PMM, filtering out internal entries.

    :return: Tuple of (nodes_raw, services_raw, active_service_types).
    """
    nodes_raw: dict[str, dict[str, Any]] = {}
    services_raw: dict[str, dict[str, Any]] = {}
    active_types: set[str] = set()

    if await pmm_api.is_older_than_v3():
        nodes_data = await pmm_api.post("/v1/inventory/Nodes/List", json={})
    else:
        nodes_data = await pmm_api.get("/v1/inventory/nodes")
    for node_type, node_list in nodes_data.items():
        for node in node_list:
            nid = node.get("node_id", "")
            nname = node.get("node_name", "")
            if nid in _PMM_SERVER_FILTER or nname in _PMM_SERVER_FILTER:
                continue
            nodes_raw[nid] = {"name": nname, "type": node_type, "id": nid}

    if await pmm_api.is_older_than_v3():
        svc_data = await pmm_api.post("/v1/inventory/Services/List", json={})
    else:
        svc_data = await pmm_api.get("/v1/inventory/services")
    for svc_type, svc_list in svc_data.items():
        for svc in svc_list:
            sid = svc.get("service_id", "")
            sname = svc.get("service_name", "")
            if sname in _PMM_SERVER_FILTER or svc.get("node_id") == "pmm-server":
                continue
            services_raw[sid] = {
                "name": sname,
                "type": svc_type,
                "id": sid,
                "node_id": svc.get("node_id", ""),
            }
            active_types.add(svc_type)

    return nodes_raw, services_raw, active_types
