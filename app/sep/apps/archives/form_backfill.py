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

"""Legacy ``data['_form']`` reconstruction for the Archives plugin."""

from __future__ import annotations

from datetime import date
from typing import Any, TYPE_CHECKING

import yaml

from app.inventory.models import ServiceTypeEnum
from app.sep.apps.archives.models import ArchivesCreate, OWNER
from app.sep.apps.framework.form_backfill_guards import require_run_python_meta
from app.sep.apps.framework.form_backfill_inventory import resolve_service_from_meta
from app.sep.apps.framework.form_backfill_registry import FormBackfillEntry

if TYPE_CHECKING:
    from app.sep.apps.framework.form_backfill_registry import FormBackfillContext
    from app.tasks.models import Task

__all__ = ["FORM_BACKFILL_ENTRIES", "reconstruct_archives_form"]


def _case_get(mapping: dict[str, Any], key: str) -> Any:
    """Return ``mapping[key]`` using a case-insensitive key match."""
    if key in mapping:
        return mapping[key]
    normalized = key.upper()
    for candidate, value in mapping.items():
        if isinstance(candidate, str) and candidate.upper() == normalized:
            return value
    return None


def _int_flag_to_bool(value: Any) -> bool | None:
    """Map a legacy integer flag (0/1/None) to the create model's tri-state bool."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    return None


def _load_archives_config(
    config_yaml: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Parse archiver YAML into ``(ALL, PURGE_LIST[0])`` when possible."""
    try:
        config = yaml.safe_load(config_yaml)
    except yaml.YAMLError:
        return None
    if not isinstance(config, dict):
        return None

    all_section = _case_get(config, "all")
    if not isinstance(all_section, dict):
        all_section = {}

    purge_list = _case_get(config, "purge_list")
    if not isinstance(purge_list, list) or not purge_list:
        return None
    purge_item = purge_list[0]
    if not isinstance(purge_item, dict):
        return None
    return all_section, purge_item


def _non_empty_str(value: Any) -> str | None:
    """Return a stripped string when ``value`` is a non-empty string."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _build_source(purge_item: dict[str, Any]) -> dict[str, Any] | None:
    """Fold ``PURGE_LIST`` source fields into the ``source`` one-of branch."""
    source_query = _non_empty_str(_case_get(purge_item, "source_query"))
    if source_query is not None:
        return {"mode": "query", "source_query": source_query}

    source_db = _non_empty_str(_case_get(purge_item, "source_db"))
    source_table = _non_empty_str(_case_get(purge_item, "source_table"))
    if source_db is None or source_table is None:
        return None
    return {
        "mode": "table",
        "source_db": source_db,
        "source_table": source_table,
    }


def _build_destination(purge_item: dict[str, Any]) -> dict[str, Any] | None:
    """Fold ``PURGE_LIST`` destination fields into the ``destination`` one-of branch."""
    dest_file = _non_empty_str(_case_get(purge_item, "dest_file"))
    if dest_file is not None:
        return {"mode": "file", "dest_file": dest_file}

    dest_table = _non_empty_str(_case_get(purge_item, "dest_table"))
    if dest_table is None:
        return None

    destination: dict[str, Any] = {
        "mode": "table",
        "dest_table": dest_table,
    }
    dest_db = _non_empty_str(_case_get(purge_item, "dest_db"))
    if dest_db is not None:
        destination["dest_db"] = dest_db
    return destination


def _build_host(
    purge_item: dict[str, Any],
    ctx: FormBackfillContext,
) -> dict[str, Any] | None:
    """Fold ``DEST_HOST`` / ``DEST_PORT`` into the ``host`` one-of branch."""
    dest_host = _non_empty_str(_case_get(purge_item, "dest_host"))
    if dest_host is None:
        return None

    dest_port = _case_get(purge_item, "dest_port")
    resolved_port = dest_port if isinstance(dest_port, int) else None
    dest_service_id = ctx.service_lookup.resolve(
        service_type=ServiceTypeEnum.MYSQL,
        host=dest_host,
        port=resolved_port,
        service_name=None,
    )
    if dest_service_id is not None:
        return {"mode": "service", "dest_service": dest_service_id}
    return {
        "mode": "manual",
        "dest_host": dest_host,
        "dest_port": resolved_port,
    }


def _resolve_source_service_id(
    all_section: dict[str, Any],
    meta: dict[str, Any],
    ctx: FormBackfillContext,
) -> int | None:
    """Resolve the source MySQL ``service_id`` from config ``ALL`` and task meta."""
    config_source_host = _case_get(all_section, "source_host")
    config_source_port = _case_get(all_section, "source_port")
    explicit_host = config_source_host if isinstance(config_source_host, str) else None
    explicit_port = config_source_port if isinstance(config_source_port, int) else None
    resolve_meta = meta
    if isinstance(config_source_host, str) and config_source_host.strip():
        resolve_meta = {**meta, "_service_name": None}
    return resolve_service_from_meta(
        ctx,
        resolve_meta,
        ServiceTypeEnum.MYSQL,
        host=explicit_host,
        port=explicit_port,
    )


def _apply_purge_options(body: dict[str, Any], purge_item: dict[str, Any]) -> None:
    """Merge optional purge-entry fields into a create-model body in place."""
    where = _non_empty_str(_case_get(purge_item, "where"))
    if where is not None:
        body["where"] = where

    swp_table_suffix = _case_get(purge_item, "swp_table_suffix")
    if isinstance(swp_table_suffix, date):
        body["swp_table_suffix"] = swp_table_suffix

    for field_name, purge_key in (
        ("use_index", "use_index"),
        ("extra_args", "extra_args"),
        ("limit", "limit"),
        ("sleep", "sleep"),
    ):
        value = _case_get(purge_item, purge_key)
        if value is not None:
            body[field_name] = value

    for field_name, purge_key in (
        ("disable_binlog", "disable_binlog"),
        ("disable_bulk_insert", "disable_bulk_insert"),
        ("delete_data", "delete_data"),
    ):
        bool_value = _int_flag_to_bool(_case_get(purge_item, purge_key))
        if bool_value is not None:
            body[field_name] = bool_value


def _build_archives_form_body(
    task: Task,
    meta: dict[str, Any],
    all_section: dict[str, Any],
    purge_item: dict[str, Any],
    ctx: FormBackfillContext,
) -> dict[str, Any] | None:
    """Assemble an ``ArchivesCreate`` body from parsed config sections."""
    hostname = meta.get("target")
    if not isinstance(hostname, str) or not hostname.strip():
        return None

    service_id = _resolve_source_service_id(all_section, meta, ctx)
    if service_id is None:
        return None

    source = _build_source(purge_item)
    if source is None:
        return None

    swap_drop = _case_get(purge_item, "swap_drop")
    if not isinstance(swap_drop, int):
        return None

    delete_data = _int_flag_to_bool(_case_get(purge_item, "delete_data"))
    if delete_data:
        destination = None
    else:
        destination = _build_destination(purge_item)
        if destination is None:
            return None

    body: dict[str, Any] = {
        "task_name": task.name,
        "hostname": hostname.strip(),
        "service_id": service_id,
        "swap_drop": swap_drop,
        "source": source,
        "alert_on_fail": task.alert_on_fail,
    }
    if destination is not None:
        body["destination"] = destination

    host_oneof = _build_host(purge_item, ctx)
    if host_oneof is not None:
        body["host"] = host_oneof

    _apply_purge_options(body, purge_item)
    return body


def reconstruct_archives_form(
    task: Task,
    ctx: FormBackfillContext,
) -> dict[str, Any] | None:
    """Rebuild an :class:`~app.sep.apps.archives.models.ArchivesCreate` body from a legacy task.

    Parses ``meta['config']`` ``ALL`` / ``PURGE_LIST`` YAML, resolves ``service_id``
    from the source host/port, and maps the first purge entry into the create model's
    discriminated-union fields. Returns ``None`` when the task is not an archiver
    ``run-python`` row or inventory resolution is ambiguous.

    :param task: The persisted archives task row.
    :param ctx: Shared backfill context carrying the inventory lookup table.
    :return: A create-model-shaped dict, or ``None`` when reconstruction fails.
    """
    meta = require_run_python_meta(task)
    if meta is None:
        return None

    config_raw = meta["config"]
    if not isinstance(config_raw, str) or not config_raw.strip():
        return None

    loaded = _load_archives_config(config_raw)
    if loaded is None:
        return None
    return _build_archives_form_body(task, meta, *loaded, ctx)


FORM_BACKFILL_ENTRIES = [
    FormBackfillEntry(
        app_key="archives",
        owner=OWNER,
        create_model=ArchivesCreate,
        reconstructor=reconstruct_archives_form,
    ),
]
