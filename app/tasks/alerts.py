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

"""Build owner-specific detail blocks for task failure alerts.

This module lives in the tasks service and must never import from
``app/sep``: the tasks API and the Celery worker that runs
``alert_for_status`` cannot depend on the SEP plugin package. The archiver
config parser here is the single source of truth for the
``PURGE_LIST`` -> (source, condition, target) mapping; the SEP archives
plugin imports it rather than duplicating the field-extraction logic.
"""

import logging
import re
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

import yaml

from app.tasks.anonymizer import anonymize_text
from app.tasks.anonymizer.entities import PIIEntity
from app.tasks.logs.constants import STDERR_ERROR_MARKER as _ERROR_MARKER

if TYPE_CHECKING:
    from app.tasks.models import TaskHistory

logger = logging.getLogger(__name__)

#: Shown for the Error Details section when no trace can be extracted. AC #2
#: forbids a silently null/empty Error Details block.
ARCHIVER_TRACE_PLACEHOLDER = "No error trace captured from STDERR."

#: Shown for a configuration field that cannot be resolved from the task config.
ARCHIVER_FIELD_PLACEHOLDER = "unavailable"

#: Hard cap on the emitted error trace, protecting the downstream alert payload.
MAX_TRACE_BYTES = 4096

#: Replacement token substituted for any redacted credential.
_REDACTION_MASK = "***"

#: ``scheme://user[:password]@`` userinfo prefix of a connection URI.
_URI_USERINFO_RE = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*://)[^/\s@]+@")

#: Sensitive ``key=value`` / ``key: value`` credential pairs. Covers query-string
#: and config forms (``password``/``passwd``/``pwd``).
_KV_SECRET_RE = re.compile(
    r"(?i)(?P<key>password|passwd|pwd)\s*[=:]\s*(?P<val>[^&\s,;\"']+)"
)

#: pt-archiver / Perl-DBI DSN password component ``p=<val>``. Case-sensitive: in a
#: DBI DSN lowercase ``p`` is the password while uppercase ``P`` is the port, so
#: only lowercase ``p`` is masked. The look-behind avoids matching the tail of a
#: longer token (e.g. ``...,p=`` matches, ``help=`` does not).
_DSN_PASSWORD_RE = re.compile(r"(?<![A-Za-z0-9_])(?P<key>p)=(?P<val>[^,\s\"']+)")

#: CLI password flags: ``--password=val``, ``--password val``, ``-pVAL``.
_CLI_PASSWORD_RE = re.compile(r"(?i)(?P<flag>--password(?:[=\s])|-p)(?P<val>[^\s\"']+)")


def redact_secrets(text: str) -> str:
    """Mask credentials embedded in a free-text error trace.

    Runs unconditionally (independent of the opt-in PII mask) so a connection
    string or password echoed by pt-archiver/MySQL into STDERR cannot leave the
    platform in a failure alert. Masks: URI userinfo (``scheme://user:pass@``),
    ``password``/``passwd``/``pwd`` key/value pairs, the Perl-DBI DSN ``p=``
    component, and the ``--password``/``-p`` CLI flags.

    :param text: The text that may contain credentials.
    :type text: str
    :return: The text with any detected credential replaced by ``***``.
    :rtype: str
    """
    text = _URI_USERINFO_RE.sub(rf"\g<scheme>{_REDACTION_MASK}@", text)
    text = _KV_SECRET_RE.sub(rf"\g<key>={_REDACTION_MASK}", text)
    text = _DSN_PASSWORD_RE.sub(rf"\g<key>={_REDACTION_MASK}", text)
    return _CLI_PASSWORD_RE.sub(rf"\g<flag>{_REDACTION_MASK}", text)


@dataclass(frozen=True)
class ArchiverPurgeFields:
    """Hold the archiver fields extracted from a ``PURGE_LIST`` entry.

    :param source_db: The source database name (``SOURCE_DB``).
    :type source_db: str | None
    :param source_table: The source table name (``SOURCE_TABLE``).
    :type source_table: str | None
    :param where: The archiving ``WHERE`` condition.
    :type where: str | None
    :param dest_db: The destination database name (``DEST_DB``).
    :type dest_db: str | None
    :param dest_table: The destination table name (``DEST_TABLE``).
    :type dest_table: str | None
    :param dest_file: The destination file/storage path (``DEST_FILE``).
    :type dest_file: str | None
    :param source_query: An optional source query (``SOURCE_QUERY``).
    :type source_query: str | None
    """

    source_db: str | None
    source_table: str | None
    where: str | None
    dest_db: str | None
    dest_table: str | None
    dest_file: str | None
    source_query: str | None

    @property
    def source(self) -> str | None:
        """Return the ``SOURCE_DB.SOURCE_TABLE`` display string.

        :return: The composed source identifier, or ``None`` when either part
            is missing.
        :rtype: str | None
        """
        if self.source_db and self.source_table:
            return f"{self.source_db}.{self.source_table}"
        return None

    @property
    def condition(self) -> str | None:
        """Return the archiving ``WHERE`` condition.

        :return: The ``WHERE`` clause, or ``None`` when not set.
        :rtype: str | None
        """
        return self.where

    @property
    def dest_table_display(self) -> str | None:
        """Return the destination table as ``DB.TABLE``.

        The database falls back to ``SOURCE_DB`` when ``DEST_DB`` is absent,
        mirroring the SEP archives ``get_archives_task_info`` behaviour.

        :return: The composed destination table identifier, or ``None`` when
            no destination table is set.
        :rtype: str | None
        """
        if not self.dest_table:
            return None
        display_db = self.dest_db or self.source_db
        if display_db:
            return f"{display_db}.{self.dest_table}"
        return self.dest_table

    @property
    def target(self) -> str | None:
        """Return the archiving target: destination table or file.

        :return: The destination table (``DB.TABLE``) when present, else the
            destination file path, else ``None``.
        :rtype: str | None
        """
        return self.dest_table_display or self.dest_file


def parse_archiver_purge_config(config_yaml: str | None) -> ArchiverPurgeFields | None:
    """Parse an archiver config YAML into its first-entry purge fields.

    Only the first ``PURGE_LIST`` entry is represented. The function never
    raises: a missing, non-string, scalar, or unparseable config returns
    ``None`` so the failure-alert path can fall back to placeholders.

    :param config_yaml: The serialized archiver config (``meta["config"]``).
    :type config_yaml: str | None
    :return: The extracted fields, or ``None`` when no entry can be parsed.
    :rtype: ArchiverPurgeFields | None
    """
    if not config_yaml:
        return None
    try:
        config = yaml.safe_load(config_yaml)
    except (yaml.YAMLError, TypeError):
        return None
    if not isinstance(config, dict):
        return None
    purge_list = config.get("PURGE_LIST")
    if not isinstance(purge_list, list) or not purge_list:
        return None
    purge_item = purge_list[0]
    if not isinstance(purge_item, dict):
        return None
    return ArchiverPurgeFields(
        source_db=purge_item.get("SOURCE_DB"),
        source_table=purge_item.get("SOURCE_TABLE"),
        where=purge_item.get("WHERE"),
        dest_db=purge_item.get("DEST_DB"),
        dest_table=purge_item.get("DEST_TABLE"),
        dest_file=purge_item.get("DEST_FILE"),
        source_query=purge_item.get("SOURCE_QUERY"),
    )


def extract_last_error_trace(stderr: str | None) -> str:
    """Extract the last error block from a failed execution's STDERR.

    The trace is the contiguous run of lines from the last blank-line boundary
    preceding the final ``ERROR`` line through the end of the log, capped to
    :data:`MAX_TRACE_BYTES` (keeping the tail). When the log is empty or has no
    ``ERROR`` marker, :data:`ARCHIVER_TRACE_PLACEHOLDER` is returned so the
    Error Details section is never silently empty.

    :param stderr: The decoded STDERR content, or ``None``.
    :type stderr: str | None
    :return: The extracted error block, or the placeholder.
    :rtype: str
    """
    if not stderr or not stderr.strip():
        return ARCHIVER_TRACE_PLACEHOLDER

    lines = stderr.splitlines()
    last_error_idx = None
    for idx, line in enumerate(lines):
        if _ERROR_MARKER in line:
            last_error_idx = idx
    if last_error_idx is None:
        return ARCHIVER_TRACE_PLACEHOLDER

    start = 0
    for idx in range(last_error_idx, -1, -1):
        if not lines[idx].strip():
            start = idx + 1
            break
    block = "\n".join(lines[start:]).strip()
    if not block:
        return ARCHIVER_TRACE_PLACEHOLDER

    encoded = block.encode()
    if len(encoded) > MAX_TRACE_BYTES:
        block = encoded[-MAX_TRACE_BYTES:].decode(errors="ignore")
    return block


def build_archiver_description(
    fields: ArchiverPurgeFields | None,
    error_trace: str,
    entities: set[PIIEntity],
) -> str:
    """Render the combined archiver failure description block.

    The block always carries the four labeled lines (Error Details, Source,
    Condition, Target); unresolved config fields render
    :data:`ARCHIVER_FIELD_PLACEHOLDER`. The assembled text is first passed
    through :func:`redact_secrets` (always-on credential masking, independent of
    the PII mask) and then :func:`anonymize_text` so the configured PII entities
    are scrubbed before the detail leaves for the external alerting provider. An
    empty ``entities`` set skips only the PII pass; credential redaction still
    runs.

    :param fields: The parsed archiver fields, or ``None`` when unavailable.
    :type fields: ArchiverPurgeFields | None
    :param error_trace: The extracted error trace or placeholder.
    :type error_trace: str
    :param entities: The PII entities to scrub from the assembled block.
    :type entities: set[PIIEntity]
    :return: The rendered (and anonymized) description block.
    :rtype: str
    """
    source = (fields.source if fields else None) or ARCHIVER_FIELD_PLACEHOLDER
    condition = (fields.condition if fields else None) or ARCHIVER_FIELD_PLACEHOLDER
    target = (fields.target if fields else None) or ARCHIVER_FIELD_PLACEHOLDER

    block = (
        "=== ERROR DETAILS ===\n"
        f"{error_trace}\n"
        "\n"
        "=== ARCHIVER CONFIGURATION ===\n"
        f"Source: {source}\n"
        f"Condition: {condition}\n"
        f"Target: {target}"
    )
    return anonymize_text(redact_secrets(block), entities)


@dataclass(frozen=True)
class OwnerAlertDetails:
    """Hold the owner-specific additions to a task failure alert.

    :param source_node: The source database node name used in the alert
        summary (Short Description).
    :type source_node: str
    :param custom_details: The provider-agnostic detail payload attached to the
        alert; surfaces through ``PagerDutyAlert.custom_details``.
    :type custom_details: dict[str, Any]
    """

    source_node: str
    custom_details: dict[str, Any]


def _effective_entities(history: "TaskHistory") -> set[PIIEntity]:
    """Return the PII entities to scrub, preferring the history-level mask.

    Falls back to the owning task's mask when the history has none, matching
    the documented :attr:`TaskHistory.anonymize_mask` semantics. A missing mask
    on both yields an empty set: PII scrubbing is opt-in (auto-masking the
    archiver DB/table/WHERE by default would gut the alert's usefulness). Note
    this only disables the *PII* pass — credential redaction in
    :func:`build_archiver_description` runs unconditionally regardless of mask.

    :param history: The task execution history.
    :type history: TaskHistory
    :return: The set of PII entities to anonymize.
    :rtype: set[PIIEntity]
    """
    mask = history.anonymize_mask
    if mask is None:
        mask = history.task.anonymize_mask
    return PIIEntity.decode_selection(mask or 0)


async def _read_last_stderr(task_history_id: int) -> str | None:
    """Read the failed execution's trailing STDERR in an isolated session.

    Delegates to :meth:`TaskHistoryLogManager.get_last_error_log`, which may
    span multiple chunks so an error block straddling a chunk boundary is fully
    captured. Opens its own session so the read works identically in the Celery
    worker and the tasks API, and swallows any error: a log-read failure must
    never prevent the failure alert itself from firing.

    :param task_history_id: The ``TaskHistory`` identifier.
    :type task_history_id: int
    :return: The trailing STDERR content, or ``None`` when unavailable.
    :rtype: str | None
    """
    from app.tasks.crud import TaskHistoryLogManager
    from app.tasks.db import get_async_session_maker

    try:
        async_session = get_async_session_maker()
        async with async_session() as session:
            return await TaskHistoryLogManager.get_last_error_log(
                session, task_history_id
            )
    except Exception:
        logger.exception(
            "Failed to read STDERR for task history %s while building alert detail.",
            task_history_id,
        )
        return None


async def build_owner_alert_details(
    history: "TaskHistory",
) -> OwnerAlertDetails | None:
    """Build owner-specific failure-alert details for the given history.

    Returns ``None`` for any non-archiver task, leaving the generic alert path
    unchanged. For :attr:`TaskOwner.ARCHIVER` failures, resolve the source
    database node and assemble the combined ``custom_details`` description block
    (error trace plus Source/Condition/Target).

    The config is taken from the dispatch-time snapshot
    (``execution_request.meta``) so the alert describes what actually ran rather
    than a later edit to the mutable ``task.data["meta"]``; the task data is used
    only when the snapshot is empty (legacy histories). The source node
    (``meta["_pmm_node_name"]``, falling back to ``execution_request.target``) is
    the actionable identifier the summary exists to surface and is deliberately
    not PII-scrubbed; sensitive content lives in the redacted detail block.

    :param history: The failed task execution history.
    :type history: TaskHistory
    :return: The owner-specific alert additions, or ``None`` for non-archiver
        tasks.
    :rtype: OwnerAlertDetails | None
    """
    from app.tasks.models import TaskOwner

    if history.task.owner != TaskOwner.ARCHIVER:
        return None

    meta = history.execution_request.meta or (history.task.data or {}).get("meta") or {}
    source_node = meta.get("_pmm_node_name") or history.execution_request.target

    stderr = await _read_last_stderr(history.id)
    error_trace = extract_last_error_trace(stderr)
    fields = parse_archiver_purge_config(meta.get("config"))
    description = build_archiver_description(
        fields, error_trace, _effective_entities(history)
    )

    return OwnerAlertDetails(
        source_node=source_node,
        custom_details={"description": description},
    )
