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

"""Legacy ``data['_form']`` reconstruction for the Checksums plugin."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from app.inventory.models import ServiceTypeEnum
from app.sep.apps.checksums.deps import parse_checksums_task_args
from app.sep.apps.framework.form_backfill_inventory import resolve_service_from_meta
from app.sep.apps.framework.form_dsl import DSN_TABLE_DEFAULT

if TYPE_CHECKING:
    from app.sep.apps.framework.form_backfill import FormBackfillContext
    from app.tasks.models import Task

__all__ = ["reconstruct_checksums_form"]


def _split_checksums_dsn_recursion(recursion_method: str) -> tuple[str, str]:
    """Split a persisted ``--recursion-method`` value into method and DSN table.

    Legacy checksum tasks store ``dsn`` recursion expanded as
    ``dsn=<service-dsn>,<dsn-table>`` (see
    :func:`~app.sep.apps.checksums.spec.build_checksums_arg_prefix`). The
    create form keeps ``recursion_method="dsn"`` and ``dsn_table`` separately.

    :param recursion_method: The value produced by
        :func:`~app.sep.apps.checksums.deps.parse_checksums_task_args`.
    :return: ``(recursion_method, dsn_table)`` suitable for :class:`~app.sep.apps.checksums.models.ChecksumsForm`.
    """
    if recursion_method in {"", "dsn"}:
        return "dsn", ""
    if not recursion_method.startswith("dsn="):
        return recursion_method, ""

    payload = recursion_method.removeprefix("dsn=")
    if payload.startswith("D="):
        return "dsn", payload
    if payload.startswith(",D="):
        return "dsn", payload[1:]

    d_index = payload.find(",D=")
    if d_index >= 0:
        return "dsn", payload[d_index + 1 :]

    return "dsn", ""


def _normalize_dsn_table(dsn_table: str) -> str:
    """Return ``""`` when ``dsn_table`` matches the Percona Toolkit default."""
    normalized = dsn_table.strip()
    if normalized == DSN_TABLE_DEFAULT:
        return ""
    return normalized


def reconstruct_checksums_form(
    task: Task,
    ctx: FormBackfillContext,
) -> dict[str, Any] | None:
    """Rebuild a :class:`~app.sep.apps.checksums.models.ChecksumsForm` body from a legacy task.

    Combines ``task.name``, ``meta['target']``, inventory service resolution, and
    :func:`~app.sep.apps.checksums.deps.parse_checksums_task_args`. Returns
    ``None`` when the task is not a checksums run-command row or service lookup
    is ambiguous.

    :param task: The persisted checksums task row.
    :param ctx: Shared backfill context carrying the inventory lookup table.
    :return: A create-model-shaped dict, or ``None`` when reconstruction fails.
    """
    meta = task.data.get("meta")
    if not isinstance(meta, dict):
        return None
    if meta.get("command") != "pt-table-checksum":
        return None

    hostname = meta.get("target")
    if not isinstance(hostname, str) or not hostname.strip():
        return None

    service_id = resolve_service_from_meta(ctx, meta, ServiceTypeEnum.MYSQL)
    if service_id is None:
        return None

    parsed = parse_checksums_task_args(meta)
    recursion_method, dsn_table = _split_checksums_dsn_recursion(
        parsed.pop("recursion_method", "processlist")
    )
    parsed.pop("extra_args", None)

    return {
        "task_name": task.name,
        "hostname": hostname.strip(),
        "service_id": service_id,
        "recursion_method": recursion_method,
        "dsn_table": _normalize_dsn_table(dsn_table),
        "alert_on_fail": task.alert_on_fail,
        **parsed,
    }
