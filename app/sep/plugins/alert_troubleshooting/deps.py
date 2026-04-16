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
from collections.abc import Iterable
from contextlib import suppress
from typing import Annotated, Any

from fastapi import Depends, Request
from pydantic import BaseModel, model_validator, ValidationError

from app.core.exceptions import (
    HTTPBadRequestException,
    HTTPNotFoundException,
    HTTPRedirectException,
)
from app.core.utils.fields import NonEmptyStr
from app.sep.deps import DefaultContext, ExecutorHostsCtx, SessionDep
from app.sep.models import AlertServiceType
from app.sep.plugins.snippets.deps import (
    get_snippet_execution_request_meta,
    get_snippet_source,
    get_validated_execution_args,
    SnippetDep,
)
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models.snippet import (
    BaseSnippetArgs,
    Snippet,
    SnippetExecutionMeta,
)

logger = logging.getLogger(__name__)

_COMPOUND_NAMES = {
    "MySQL": "MySQL",
    "PostgreSQL": "PostgreSQL",
    "MongoDB": "MongoDB",
    "ProxySQL": "ProxySQL",
}

_KNOWN_ACRONYMS = frozenset({"SQL", "CPU", "IO", "PK", "DB", "PG"})

_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


class AlertInfo(BaseModel):
    """Represent a normalized alert entry with its identifier and display label.

    Accept a plain string identifier, a dict with ``name`` (required) and
    optional ``label`` and ``service_type``, or keyword arguments.  Invalid
    inputs raise ``ValidationError``.  The ``service_type`` field is optional
    and, when absent, callers fall back to the snippet-level ``service_type``.

    :param name: The alert identifier as declared in snippet frontmatter.
    :type name: NonEmptyStr
    :param label: The human-readable display label for the alert.
    :type label: str
    :param service_type: The service type the alert applies to, overriding
        the snippet-level ``service_type``.  ``None`` means "fall back to the
        snippet-level value".
    :type service_type: AlertServiceType | None
    """

    name: NonEmptyStr
    label: str
    service_type: AlertServiceType | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_entry(cls, data: Any) -> Any:
        """Normalize flexible alert frontmatter into model fields.

        :param data: Raw alert entry — string, dict, or keyword dict.
        :type data: Any
        :return: A dict with ``name``, ``label``, and optional
            ``service_type`` keys.
        :rtype: Any
        """
        if isinstance(data, str):
            return {"name": data, "label": camel_case_to_title(data)}
        if isinstance(data, dict):
            name = data.get("name", "")
            label = data.get("label") or (camel_case_to_title(name) if name else "")
            service_type = data.get("service_type")
            return {"name": name, "label": label, "service_type": service_type}
        return data


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
    with suppress(ValidationError):
        return AlertInfo.model_validate(entry)
    return None


def _parse_service_type(snippet: Snippet) -> AlertServiceType | None:
    """Parse the service type from a snippet's metadata.

    :param snippet: A snippet object with a ``meta`` attribute.
    :type snippet: Snippet
    :return: The parsed service type, or ``None`` for unrecognized values.
    :rtype: AlertServiceType | None
    """
    raw = snippet.meta.get("service_type")
    if raw is None:
        return AlertServiceType.GENERIC
    try:
        return AlertServiceType(raw)
    except ValueError:
        logger.warning("Unknown service_type %r in snippet, skipping", raw)
        return None


def _resolve_alert_service_type(
    alert_info: AlertInfo,
    snippet: Snippet,
) -> AlertServiceType | None:
    """Resolve the effective service type for an alert on a snippet.

    Prefer the alert-level ``service_type`` when set; otherwise fall back to
    the snippet-level ``service_type``.

    :param alert_info: The normalized alert entry.
    :type alert_info: AlertInfo
    :param snippet: The snippet declaring the alert.
    :type snippet: Snippet
    :return: The resolved service type, or ``None`` if neither resolves to a
        valid value.
    :rtype: AlertServiceType | None
    """
    if alert_info.service_type is not None:
        return alert_info.service_type
    return _parse_service_type(snippet)


def collect_grouped_alerts(
    snippets: Iterable[Snippet],
) -> dict[AlertServiceType, list[AlertInfo]]:
    """Collect and group alerts from snippet metadata by service type.

    Iterate over snippets, extract ``alerts`` from each snippet's ``meta``
    dict, normalize entries, resolve each alert's effective ``service_type``
    (alert-level override wins over the snippet-level default), deduplicate
    by alert name within each service type, and return a mapping sorted by
    label.

    :param snippets: An iterable of snippet objects with a ``meta`` attribute.
    :type snippets: Iterable[Snippet]
    :return: A mapping from service type to a sorted list of unique alerts.
    :rtype: dict[AlertServiceType, list[AlertInfo]]
    """
    grouped = {}
    for snippet in snippets:
        alerts = _get_normalized_alerts(snippet)
        if not alerts:
            continue
        for info in alerts:
            service_type = _resolve_alert_service_type(info, snippet)
            if service_type is None:
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


def _get_normalized_alerts(snippet: Snippet) -> list[AlertInfo]:
    """Extract and normalize all alert entries from a snippet's metadata.

    :param snippet: A snippet object with a ``meta`` attribute.
    :type snippet: Snippet
    :return: A list of normalized alert entries, excluding invalid ones.
    :rtype: list[AlertInfo]
    """
    alerts_raw = snippet.meta.get("alerts", [])
    if isinstance(alerts_raw, str | dict):
        alerts_raw = [alerts_raw]
    return [
        info
        for raw_entry in alerts_raw
        if (info := normalize_alert_entry(raw_entry)) is not None
    ]


def _find_alert_in_snippet(snippet: Snippet, alert_name: str) -> AlertInfo | None:
    """Find a specific alert entry in a snippet's metadata.

    :param snippet: A snippet object with a ``meta`` attribute.
    :type snippet: Snippet
    :param alert_name: The alert identifier to look for.
    :type alert_name: str
    :return: The matching ``AlertInfo``, or ``None`` if not found.
    :rtype: AlertInfo | None
    """
    for info in _get_normalized_alerts(snippet):
        if info.name == alert_name:
            return info
    return None


def filter_snippets_for_alert(
    snippets: Iterable[Snippet],
    alert_name: str,
    service_type: AlertServiceType | None = None,
) -> tuple[list[Snippet], AlertInfo]:
    """Filter snippets to those declaring a specific alert.

    Return the matched snippets and the ``AlertInfo`` from the first match,
    avoiding a second traversal to extract the alert label.  When
    ``service_type`` is provided, the effective service type of each alert
    entry (alert-level override, else snippet-level) must equal it for the
    snippet to match.

    :param snippets: An iterable of snippet objects with a ``meta`` attribute.
    :type snippets: Iterable[Snippet]
    :param alert_name: The alert identifier to filter by.
    :type alert_name: str
    :param service_type: Optional service type to restrict matches.
    :type service_type: AlertServiceType | None
    :return: A tuple of (matched snippets, alert info from first match).
    :rtype: tuple[list[Snippet], AlertInfo]
    :raises HTTPNotFoundException: If no snippets match the alert name.
    """
    matched = []
    first_alert_info = None
    for snippet in snippets:
        info = _find_alert_in_snippet(snippet, alert_name)
        if info is None:
            continue
        if (
            service_type is not None
            and _resolve_alert_service_type(info, snippet) != service_type
        ):
            continue
        matched.append(snippet)
        if first_alert_info is None:
            first_alert_info = info
    if not matched or first_alert_info is None:
        raise HTTPNotFoundException(detail=f"Alert '{alert_name}' not found")
    return matched, first_alert_info


async def get_snippets_for_alert(
    session: SessionDep,
    alert_name: str,
    service_type: AlertServiceType,
) -> tuple[list[Snippet], AlertInfo]:
    """Load all snippets and filter to those declaring a specific alert.

    :param session: The database session.
    :type session: SessionDep
    :param alert_name: The alert identifier to filter by.
    :type alert_name: str
    :param service_type: The service type to restrict matches.
    :type service_type: AlertServiceType
    :return: A tuple of (matched snippets, alert info from first match).
    :rtype: tuple[list[Snippet], AlertInfo]
    :raises HTTPNotFoundException: If no snippets match the alert name.
    """
    snippets = await SnippetManager.list(session)
    return filter_snippets_for_alert(snippets, alert_name, service_type)


AlertSnippetsDep = Annotated[
    tuple[list[Snippet], AlertInfo], Depends(get_snippets_for_alert)
]


async def get_troubleshooting_detail_context(
    context: DefaultContext,
    snippets_and_alert: AlertSnippetsDep,
    executor_hosts_ctx: ExecutorHostsCtx,
) -> dict[str, Any]:
    """Assemble the template context for the Alert Troubleshooting detail page.

    :param context: The default template context with user and base URI.
    :type context: DefaultContext
    :param snippets_and_alert: The snippets and alert info from filtering.
    :type snippets_and_alert: AlertSnippetsDep
    :param executor_hosts_ctx: The executor hosts context with display names.
    :type executor_hosts_ctx: ExecutorHostsCtx
    :return: The updated context dictionary for the detail template.
    :rtype: dict[str, Any]
    """
    snippets, alert_info = snippets_and_alert
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


def get_ajax_executable_snippet(
    snippet: SnippetDep,
) -> Snippet:
    """Verify snippet executability and return a JSON error on failure.

    Wrap the standard executable snippet check for AJAX endpoints by
    raising an ``HTTPBadRequestException`` instead of an
    ``HTTPRedirectException``.

    :param snippet: The snippet to verify.
    :type snippet: SnippetDep
    :return: The verified executable snippet.
    :rtype: Snippet
    :raises HTTPBadRequestException: If the snippet cannot be executed.
    """
    if snippet.can_execute:
        return snippet
    raise HTTPBadRequestException(detail=f"Snippet {snippet} cannot be executed")


AjaxExecutableSnippet = Annotated[Snippet, Depends(get_ajax_executable_snippet)]


async def get_ajax_validated_execution_args(
    request: Request,
    snippet: AjaxExecutableSnippet,
) -> BaseSnippetArgs:
    """Validate execution arguments and return JSON errors on failure.

    Wrap the standard argument validation for AJAX endpoints by catching
    ``HTTPRedirectException`` and raising ``HTTPBadRequestException``
    instead.

    :param request: The HTTP request object.
    :type request: Request
    :param snippet: The executable snippet.
    :type snippet: AjaxExecutableSnippet
    :return: The validated execution arguments.
    :rtype: BaseSnippetArgs
    :raises HTTPBadRequestException: If the execution arguments are invalid.
    """
    try:
        return await get_validated_execution_args(request, snippet)
    except HTTPRedirectException:
        raise HTTPBadRequestException(
            detail="Invalid execution parameters",
        ) from None


def get_ajax_execution_request_meta(
    snippet: AjaxExecutableSnippet,
    snippet_source: Annotated[str, Depends(get_snippet_source)],
    execution_args: Annotated[
        BaseSnippetArgs, Depends(get_ajax_validated_execution_args)
    ],
) -> SnippetExecutionMeta:
    """Prepare execution metadata for an AJAX snippet execution request.

    Delegate to the standard snippet execution metadata builder but use
    AJAX-safe dependency validation that returns JSON errors instead of
    redirect responses.

    :param snippet: The executable snippet.
    :type snippet: AjaxExecutableSnippet
    :param snippet_source: The signed URL to download the snippet artifact.
    :type snippet_source: str
    :param execution_args: The validated execution arguments.
    :type execution_args: BaseSnippetArgs
    :return: The prepared execution metadata.
    :rtype: SnippetExecutionMeta
    """
    return get_snippet_execution_request_meta(snippet, snippet_source, execution_args)


ExecutionRequestMeta = Annotated[
    SnippetExecutionMeta,
    Depends(get_ajax_execution_request_meta),
]
