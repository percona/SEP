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

"""Define dependencies for the Alert Troubleshooting plugin."""

import logging
import re
from typing import Annotated, Any, NamedTuple

from fastapi import Depends

from app.core.exceptions import HTTPNotFoundException
from app.sep.deps import DefaultContext, ExecutorHostsCtx, SessionDep
from app.sep.models import AlertServiceType
from app.sep.plugins.snippets.deps import get_snippet_execution_request_meta
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models.snippet import SnippetExecutionMeta

logger = logging.getLogger(__name__)

_COMPOUND_NAMES = {
    "MySQL": "MySQL",
    "PostgreSQL": "PostgreSQL",
    "MongoDB": "MongoDB",
    "ProxySQL": "ProxySQL",
}

_KNOWN_ACRONYMS = frozenset({"SQL", "CPU", "IO", "PK", "DB", "PG"})

_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


class AlertInfo(NamedTuple):
    """Represent a normalized alert entry with its identifier and display label.

    :param name: The alert identifier as declared in snippet frontmatter.
    :type name: str
    :param label: The human-readable display label for the alert.
    :type label: str
    """

    name: str
    label: str


def camel_case_to_title(s: str) -> str:
    """Split a CamelCase identifier into a title-cased display string.

    Recognize compound product names (MySQL, PostgreSQL, MongoDB) and known
    acronyms (CPU, IO, PK) to produce correct display labels.

    :param s: The CamelCase identifier to split.
    :type s: str
    :return: The title-cased display string.
    :rtype: str
    """
    for compound, replacement in _COMPOUND_NAMES.items():
        if compound in s:
            prefix = s[: s.index(compound)]
            suffix = s[s.index(compound) + len(compound) :]
            parts = []
            if prefix:
                parts.extend(camel_case_to_title(prefix).split())
            parts.append(replacement)
            if suffix:
                parts.extend(camel_case_to_title(suffix).split())
            return " ".join(parts)
    words = _CAMEL_SPLIT_RE.split(s)
    result = []
    for word in words:
        if word.upper() in _KNOWN_ACRONYMS:
            result.append(word.upper())
        else:
            result.append(word)
    return " ".join(result)


def normalize_alert_entry(entry: Any) -> AlertInfo | None:
    """Normalize a flexible alert frontmatter entry into an ``AlertInfo``.

    Accept either a plain string identifier or a dict with ``name`` (required)
    and optional ``label``. Return ``None`` for invalid entries.

    :param entry: The raw alert entry from snippet frontmatter.
    :type entry: Any
    :return: The normalized alert info, or ``None`` if the entry is invalid.
    :rtype: AlertInfo | None
    """
    if isinstance(entry, str):
        if not entry:
            return None
        return AlertInfo(name=entry, label=camel_case_to_title(entry))
    if isinstance(entry, dict):
        name = entry.get("name")
        if not name:
            return None
        label = entry.get("label") or camel_case_to_title(name)
        return AlertInfo(name=name, label=label)
    return None


def collect_grouped_alerts(
    snippets: Any,
) -> dict[AlertServiceType, list[AlertInfo]]:
    """Collect and group alerts from snippet metadata by service type.

    Iterate over snippets, extract ``alerts`` and ``service_type`` from each
    snippet's ``meta`` dict, normalize entries, deduplicate by alert name
    within each service type, and return a mapping sorted by label.

    :param snippets: An iterable of snippet objects with a ``meta`` attribute.
    :type snippets: Any
    :return: A mapping from service type to a sorted list of unique alerts.
    :rtype: dict[AlertServiceType, list[AlertInfo]]
    """
    grouped = {}
    for snippet in snippets:
        alerts_raw = snippet.meta.get("alerts", [])
        if isinstance(alerts_raw, str | dict):
            alerts_raw = [alerts_raw]
        if not alerts_raw:
            continue
        raw_service_type = snippet.meta.get("service_type")
        if raw_service_type is None:
            service_type = AlertServiceType.GENERIC
        else:
            try:
                service_type = AlertServiceType(raw_service_type)
            except ValueError:
                logger.warning(
                    "Unknown service_type %r in snippet, skipping",
                    raw_service_type,
                )
                continue
        for raw_entry in alerts_raw:
            info = normalize_alert_entry(raw_entry)
            if info is None:
                continue
            grouped.setdefault(service_type, {})[info.name] = info
    return {
        svc: sorted(alerts.values(), key=lambda a: a.label)
        for svc, alerts in grouped.items()
    }


async def get_grouped_alerts(
    session: SessionDep,
) -> dict[AlertServiceType, list[AlertInfo]]:
    """Load all snippets and collect grouped alerts from their metadata.

    :param session: The database session.
    :type session: SessionDep
    :return: A mapping from service type to a sorted list of unique alerts.
    :rtype: dict[AlertServiceType, list[AlertInfo]]
    """
    snippets = await SnippetManager.list(session)
    return collect_grouped_alerts(snippets)


GroupedAlertsDep = Annotated[
    dict[AlertServiceType, list[AlertInfo]],
    Depends(get_grouped_alerts),
]


async def get_troubleshooting_index_context(
    context: DefaultContext,
    grouped_alerts: GroupedAlertsDep,
) -> dict[str, Any]:
    """Assemble the template context for the Alert Troubleshooting index page.

    :param context: The default template context with user and base URI.
    :type context: DefaultContext
    :param grouped_alerts: Alerts grouped by service type.
    :type grouped_alerts: GroupedAlertsDep
    :return: The updated context dictionary for the index template.
    :rtype: dict[str, Any]
    """
    context["grouped_alerts"] = grouped_alerts
    context["alert_service_types"] = list(AlertServiceType)
    return context


TroubleshootingIndexContext = Annotated[
    dict[str, Any],
    Depends(get_troubleshooting_index_context),
]


def _snippet_has_alert(snippet: Any, alert_name: str) -> bool:
    """Check whether a snippet's metadata declares the given alert.

    :param snippet: A snippet object with a ``meta`` attribute.
    :type snippet: Any
    :param alert_name: The alert identifier to look for.
    :type alert_name: str
    :return: ``True`` if the snippet declares the alert, ``False`` otherwise.
    :rtype: bool
    """
    alerts_raw = snippet.meta.get("alerts", [])
    if isinstance(alerts_raw, str | dict):
        alerts_raw = [alerts_raw]
    for raw_entry in alerts_raw:
        info = normalize_alert_entry(raw_entry)
        if info is not None and info.name == alert_name:
            return True
    return False


def filter_snippets_for_alert(snippets: Any, alert_name: str) -> list:
    """Filter snippets to those declaring a specific alert.

    :param snippets: An iterable of snippet objects with a ``meta`` attribute.
    :type snippets: Any
    :param alert_name: The alert identifier to filter by.
    :type alert_name: str
    :return: A list of snippets that declare the given alert.
    :rtype: list
    :raises HTTPNotFoundException: If no snippets match the alert name.
    """
    matched = [s for s in snippets if _snippet_has_alert(s, alert_name)]
    if not matched:
        raise HTTPNotFoundException(detail=f"Alert '{alert_name}' not found")
    return matched


def get_alert_info_from_snippets(alert_name: str, snippets: Any) -> AlertInfo:
    """Extract ``AlertInfo`` for a given alert from the first matching snippet.

    :param alert_name: The alert identifier to look up.
    :type alert_name: str
    :param snippets: An iterable of snippets that declare the alert.
    :type snippets: Any
    :return: The normalized alert info with name and label.
    :rtype: AlertInfo
    """
    for snippet in snippets:
        alerts_raw = snippet.meta.get("alerts", [])
        if isinstance(alerts_raw, str | dict):
            alerts_raw = [alerts_raw]
        for raw_entry in alerts_raw:
            info = normalize_alert_entry(raw_entry)
            if info is not None and info.name == alert_name:
                return info
    return AlertInfo(name=alert_name, label=camel_case_to_title(alert_name))


async def get_snippets_for_alert(
    session: SessionDep,
    alert_name: str,
) -> list:
    """Load all snippets and filter to those declaring a specific alert.

    :param session: The database session.
    :type session: SessionDep
    :param alert_name: The alert identifier to filter by.
    :type alert_name: str
    :return: A list of snippets that declare the given alert.
    :rtype: list
    :raises HTTPNotFoundException: If no snippets match the alert name.
    """
    snippets = await SnippetManager.list(session)
    return filter_snippets_for_alert(snippets, alert_name)


AlertSnippetsDep = Annotated[list, Depends(get_snippets_for_alert)]


async def get_troubleshooting_detail_context(
    context: DefaultContext,
    alert_name: str,
    snippets: AlertSnippetsDep,
    executor_hosts_ctx: ExecutorHostsCtx,
) -> dict[str, Any]:
    """Assemble the template context for the Alert Troubleshooting detail page.

    :param context: The default template context with user and base URI.
    :type context: DefaultContext
    :param alert_name: The alert identifier from the URL path.
    :type alert_name: str
    :param snippets: The snippets associated with this alert.
    :type snippets: AlertSnippetsDep
    :param executor_hosts_ctx: The executor hosts context with display names.
    :type executor_hosts_ctx: ExecutorHostsCtx
    :return: The updated context dictionary for the detail template.
    :rtype: dict[str, Any]
    """
    alert_info = get_alert_info_from_snippets(alert_name, snippets)
    context |= {
        "alert_info": alert_info,
        "snippets": snippets,
        "executor_hosts": executor_hosts_ctx.as_template_list(),
    }
    return context


TroubleshootingDetailContext = Annotated[
    dict[str, Any],
    Depends(get_troubleshooting_detail_context),
]

ExecutionRequestMeta = Annotated[
    SnippetExecutionMeta,
    Depends(get_snippet_execution_request_meta),
]
