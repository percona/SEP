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

"""Record a completed MySQL backup run into the catalog.

This module owns the map from a terminal backup run onto one persisted
:class:`~app.sep.apps.mysql_backups.catalog_models.MysqlBackupRun`. The tasks service
resolves it lazily through :func:`app.tasks.hook_resolver.resolve_hook`,
following the ``"module:function"`` path the backup task carries in
``Task.run_result_recorder`` (stamped at creation from
:data:`RUN_RESULT_RECORDER`), so this catalog knowledge stays inside the plugin
rather than leaking into ``app/tasks``.

The recorder is invoked at every terminal status with the payload-reported
result (``None`` when a run reported nothing — an older payload, or a
non-success run). It records exactly one row per *successful* mydumper or
xtrabackup run and nothing for anything else: binlog runs, non-success
terminals, and unknown tools leave no record. A success that reported no result
(or a partial one) still records the run, leaving the unreported fields empty.
"""

import logging
from typing import Any, TypeVar

import yaml
from sqlmodel.ext.asyncio.session import AsyncSession

from app.sep.apps.mysql_backups.catalog_models import MysqlBackupRun
from app.sep.apps.mysql_backups.crud import MysqlBackupRunManager
from app.sep.db import get_async_session_maker
from app.tasks.models import TaskHistory, TaskHistoryStatusEnum

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: Importable ``"module:function"`` path of this module's run-result recorder.
#: The backups app stamps it onto every backup task (``Task.run_result_recorder``)
#: at creation so the tasks service resolves the recorder lazily without
#: statically importing the plugin.
RUN_RESULT_RECORDER = f"{__name__}:record_backup_run"

#: ``BACKUP_TYPE`` markers for the tools that produce a per-run artifact worth
#: cataloguing (``BackupType.MYDUMPER`` / ``BackupType.XTRABACKUP``). Binlog
#: (``"B"``) runs continuously and has no per-run completion to record. Kept as
#: raw markers so this recorder stays free of the plugin's heavy form-model
#: import, which the tasks service would otherwise pull in when resolving it.
_CATALOGUED_TYPES = frozenset({"M", "X"})


def _backup_type(task_data: dict[str, Any] | None) -> str | None:
    """Return the ``BACKUP_TYPE`` from a task's YAML config, or ``None``.

    Reads the value defensively: a missing meta, unparseable YAML, or an absent
    key all resolve to ``None`` rather than raising.

    :param task_data: The task's ``data`` dict (``meta`` carries the YAML config).
    :return: The raw backup-type marker (``"M"``/``"X"``/``"B"``), or ``None``.
    """
    meta = task_data.get("meta") if task_data else None
    raw_config = meta.get("config") if isinstance(meta, dict) else None
    if not raw_config:
        return None
    try:
        config = yaml.safe_load(raw_config)
    except yaml.YAMLError:
        return None
    if not isinstance(config, dict):
        return None
    server_list = config.get("SERVER_LIST")
    if not isinstance(server_list, list) or not server_list:
        return None
    first = server_list[0]
    if not isinstance(first, dict):
        return None
    raw_type = first.get("BACKUP_TYPE")
    return raw_type if isinstance(raw_type, str) else None


def _coerce(value: Any, expected: type[T], field: str) -> T | None:
    """Return ``value`` only when it is exactly ``expected``, else ``None``.

    The result dict is written by a payload on a remote host, so every field is
    untrusted: a wrong-typed value is dropped rather than stored. ``bool`` is
    rejected for an ``int`` field, since ``True``/``False`` are ``int`` subclasses
    and never a valid size. A *present* value of the wrong type is a contract
    violation and is logged before being dropped; an absent field (``None``)
    passes through silently.

    :param value: The candidate value pulled from the reported result.
    :param expected: The type the field must be to be kept.
    :param field: The field name, used only in the drop warning.
    :return: ``value`` when it matches ``expected``, otherwise ``None``.
    """
    if expected is int and isinstance(value, bool):
        kept: T | None = None
    else:
        kept = value if isinstance(value, expected) else None
    if kept is None and value is not None:
        logger.warning(
            "Dropping malformed run-result field %r: expected %s, got %r.",
            field,
            expected.__name__,
            value,
        )
    return kept


async def record_backup_run(
    session: AsyncSession,  # noqa: ARG001 — seam contract; see below
    history: TaskHistory,
    result: dict[str, Any] | None,
) -> None:
    """Persist one catalog record for a successful mydumper/xtrabackup run.

    No-ops for every case that must leave no record: a non-success terminal
    (failed, stopped, lost), a binlog or unknown-tool run, and a run already
    catalogued (idempotent on ``task_history_id``, so a re-invocation or a
    concurrent second call cannot create a duplicate). For a success worth
    recording, writes one row filling only the fields the run actually reported;
    a ``None`` or partial ``result`` leaves ``location``/``size_bytes``/
    ``upload_destination`` empty rather than failing.

    The ``mysql_backup_run`` table is owned by the **sep** database, but the
    recorder seam opens and passes a *tasks*-database session — the two are
    distinct engines under SQLite (and only coincidentally the same shared
    database under Postgres). So the write is done on a fresh sep session this
    function opens itself; the passed ``session`` is intentionally unused (all
    reads come off the already-loaded ``history``), kept only to satisfy the
    seam's ``(session, history, result)`` contract.

    :param session: The tasks-database session opened by the recorder seam;
        unused — kept for the seam contract (see above).
    :param history: The terminal ``TaskHistory``, with ``task`` loaded.
    :param result: The payload-reported result, or ``None`` when none was read.
    """
    if history.status != TaskHistoryStatusEnum.SUCCESS:
        return

    task = history.task
    task_data = task.data if task else None
    backup_type = _backup_type(task_data)
    if backup_type not in _CATALOGUED_TYPES:
        return

    meta = task_data.get("meta") if isinstance(task_data, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    reported = result if isinstance(result, dict) else {}

    record = MysqlBackupRun(
        task_history_id=history.id,
        service_name=_coerce(meta.get("_service_name"), str, "_service_name"),
        hostname=_coerce(meta.get("target"), str, "target"),
        backup_type=backup_type,
        location=_coerce(reported.get("backup_dir"), str, "backup_dir"),
        upload_destination=_coerce(
            reported.get("upload_destination"), str, "upload_destination"
        ),
        size_bytes=_coerce(reported.get("size_bytes"), int, "size_bytes"),
        started_at=history.started_at,
        finished_at=history.finished_at,
    )

    async with get_async_session_maker()() as sep_session:
        if await MysqlBackupRunManager.first(sep_session, task_history_id=history.id):
            return
        await MysqlBackupRunManager.save(sep_session, record)
