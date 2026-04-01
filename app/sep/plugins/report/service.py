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
