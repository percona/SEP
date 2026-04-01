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

from app.sep.clients.pmm import PMMRemoteAPI

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
