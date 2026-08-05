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

"""Legacy ``data['_form']`` reconstruction for the Alters plugin."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from app.inventory.models import ServiceTypeEnum
from app.sep.apps.alters.deps import parse_alters_task_args
from app.sep.apps.alters.models import AltersCreate, OWNER
from app.sep.apps.framework.form_backfill_inventory import resolve_service_from_meta
from app.sep.apps.framework.form_backfill_registry import FormBackfillEntry

if TYPE_CHECKING:
    from app.sep.apps.framework.form_backfill import FormBackfillContext
    from app.tasks.models import Task

__all__ = ["FORM_BACKFILL_ENTRIES", "reconstruct_alters_form"]


def _non_empty_str(value: Any) -> str | None:
    """Return a stripped string when ``value`` is a non-empty string, else ``None``."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def reconstruct_alters_form(
    task: Task,
    ctx: FormBackfillContext,
) -> dict[str, Any] | None:
    """Rebuild an :class:`~app.sep.apps.alters.models.AltersCreate` body from a legacy task.

    Reads the parent execute task's ``meta`` — the resolved ``_schema_name`` /
    ``_table_name`` become the collapsed free-solo ``db_schema`` / ``db_table``
    values, ``target`` supplies the executor host, and the source MySQL
    ``service_id`` is resolved from the persisted host/port/name — then folds in
    the pt-osc arguments parsed by :func:`parse_alters_task_args`. Returns ``None``
    for a satellite task (``-dry-run`` / ``-pre-checks``), a non-``run-command``
    row, or when the schema/table/host/service cannot be resolved.

    .. note::

       ``continue_on_pre_check_failure`` is not recoverable here — it is baked
       into the pre-checks satellite's ``on_failure`` wiring, not the parent
       execute task's ``meta`` — so a backfilled ``_form`` always defaults it to
       ``False``. A legacy task that ran continue-on-failure therefore prefills
       the Edit toggle as off. This is an accepted best-effort limitation.

    :param task: The persisted alters task row.
    :param ctx: Shared backfill context carrying the inventory lookup table.
    :return: A create-model-shaped dict, or ``None`` when reconstruction fails.
    """
    data = task.data
    meta = data.get("meta")
    if (
        data.get("task") != "run-command"
        or data.get("parent")
        or not isinstance(meta, dict)
    ):
        return None

    schema_name = _non_empty_str(meta.get("_schema_name"))
    table_name = _non_empty_str(meta.get("_table_name"))
    hostname = _non_empty_str(meta.get("target"))
    if schema_name is None or table_name is None or hostname is None:
        return None

    service_id = resolve_service_from_meta(ctx, meta, ServiceTypeEnum.MYSQL)
    if service_id is None:
        return None

    body = parse_alters_task_args(meta)
    body.update(
        {
            "task_name": task.name,
            "hostname": hostname,
            "service_id": service_id,
            "db_schema": schema_name,
            "db_table": table_name,
            "alert_on_fail": task.alert_on_fail,
        }
    )
    mysql_config_file = _non_empty_str(meta.get("_pre_checks_mysql_config_file"))
    if mysql_config_file is not None:
        body["pre_checks_mysql_config_file"] = mysql_config_file
    return body


FORM_BACKFILL_ENTRIES = [
    FormBackfillEntry(
        app_key="alters",
        owner=OWNER,
        create_model=AltersCreate,
        reconstructor=reconstruct_alters_form,
    ),
]
