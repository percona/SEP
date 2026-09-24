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

"""Legacy ``data['_form']`` reconstruction for the MySQL Restores plugin."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TYPE_CHECKING, TypeVar

import yaml
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db.utils import get_async_session_maker_from_engine
from app.extensions.apps.framework.form_backfill_guards import require_run_python_meta
from app.extensions.apps.framework.form_backfill_inventory import (
    resolve_service_from_meta,
)
from app.extensions.apps.framework.form_backfill_registry import FormBackfillEntry
from app.extensions.apps.framework.spec import RESERVED_FORM_KEY
from app.extensions.apps.mysql_backups.crud import MysqlBackupRunManager
from app.extensions.apps.mysql_backups.models import (
    BackupType,
    CatalogServiceKey,
    CataloguedSourceTransport,
)
from app.extensions.apps.mysql_backups.restore.deps import (
    CatalogTransportContext,
    catalogued_transport_for_stamp,
    parse_restore_task_data,
    pending_catalog_transport_lookups,
    transport_cache_key,
)
from app.extensions.apps.mysql_backups.restore.models import (
    OWNER,
    repair_source_declaration,
    RestoreCreate,
)
from app.extensions.db import get_async_session_maker
from app.extensions.db.engine import engine as extensions_engine
from app.inventory.models import ServiceTypeEnum

if TYPE_CHECKING:
    from collections.abc import Coroutine, Sequence

    from app.extensions.apps.framework.form_backfill_registry import FormBackfillContext
    from app.tasks.models import Task

__all__ = [
    "FORM_BACKFILL_ENTRY",
    "prepare_mysql_restores_catalog_transports",
    "reconstruct_mysql_restores_form",
    "repair_mysql_restores_stamp",
]

_log = logging.getLogger(__name__)
_T = TypeVar("_T")

#: ``FormBackfillContext.extras`` key holding the batched catalog transport map.
CATALOG_TRANSPORTS_EXTRA = "catalog_transports"

_RESTORE_FORM_FIELDS = frozenset(RestoreCreate.model_fields)
_EXPLICIT_FORM_KEYS = frozenset(
    {
        "task_name",
        "hostname",
        "backup_type",
        "backup_source",
        "service_id",
        "schema_id",
        "alert_on_fail",
    }
)
_PARSE_ONLY_KEYS = frozenset(
    {
        "name",
        "host",
        "database",
        "dest_host",
        "dest_port",
    }
)


def _resolve_restore_service_id(
    parsed: dict[str, Any],
    meta: dict[str, Any],
    ctx: FormBackfillContext,
) -> str | None:
    """Return the restore form ``service_id``, or ``None`` when unresolved."""
    resolve_meta = meta
    if parsed.get("host"):
        resolve_meta = {**meta, "_service_name": None}
    service_id = resolve_service_from_meta(
        ctx,
        resolve_meta,
        ServiceTypeEnum.MYSQL,
        host=parsed.get("host"),
        port=parsed.get("port"),
    )
    if service_id is None:
        return None
    return str(service_id)


def _resolve_restore_schema_id(
    service_id: str | None,
    database: Any,
    ctx: FormBackfillContext,
) -> str | None:
    """Return the restore form ``schema_id`` when the database name resolves uniquely."""
    if (
        ctx.schema_lookup is None
        or service_id is None
        or not service_id.isdigit()
        or not isinstance(database, str)
        or not database.strip()
    ):
        return None

    schema_id = ctx.schema_lookup.resolve(
        service_id=int(service_id),
        schema_name=database,
    )
    if schema_id is None:
        return None
    return str(schema_id)


def _form_for_catalog_lookup(
    task: Task, ctx: FormBackfillContext
) -> dict[str, Any] | None:
    """Return a form-shaped dict for catalog keying, or ``None`` when none applies.

    Prefers an undeclared stamp. For unstamped (reconstruct) tasks, builds the
    same ``backup_source`` / ``service_id`` shape the reconstructor will hand to
    :func:`catalogued_transport_for_stamp` so the batched prefetch hits.
    """
    data = task.data if isinstance(task.data, dict) else None
    if data is None:
        return None
    stored_form = data.get(RESERVED_FORM_KEY)
    if isinstance(stored_form, dict):
        return None if stored_form.get("source_transport") is not None else stored_form

    meta = require_run_python_meta(task)
    if meta is None:
        return None
    try:
        parsed = parse_restore_task_data({"name": task.name, "data": task.data})
    except (KeyError, TypeError, yaml.YAMLError):
        return None
    backup_source = parsed.get("backup_source")
    if not isinstance(backup_source, str) or not backup_source.strip():
        return None
    body: dict[str, Any] = {"backup_source": backup_source.strip()}
    service_id = _resolve_restore_service_id(parsed, meta, ctx)
    if service_id is not None:
        body["service_id"] = service_id
    return body


def _run_coro_sync(coro: Coroutine[Any, Any, _T]) -> _T:
    """Run ``coro`` to completion from sync code, including under a running loop.

    Used by the sync form-backfill repairer when no batch prefetch was prepared.
    When no loop is running, ``asyncio.run`` is enough; when one is, the
    coroutine runs on a worker thread with its own loop. Callers must open any
    asyncpg work on a throwaway engine for that loop — see
    :func:`_fetch_catalogued_transport`.

    :param coro: The awaitable to drive to completion.
    :return: The coroutine's result.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    def _run() -> _T:
        return asyncio.run(coro)

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_run).result()


async def _fetch_catalogued_transport(
    key: CatalogServiceKey, backup_source: str
) -> CataloguedSourceTransport | None:
    """Open a sep session and return the catalogued transport for ``backup_source``.

    Uses a throwaway ``NullPool`` engine on the sep URL rather than the
    process-wide sep ``AsyncAdaptedQueuePool``. This coroutine may run on a
    worker-thread event loop (see :func:`_run_coro_sync`), and asyncpg
    connections are loop-bound — borrowing from the shared pool would raise or
    poison it for unrelated requests. Same pattern as
    :func:`~app.core.db.utils.try_pg_advisory_xact_lock`.

    :param key: The service the catalog rows are selected for.
    :param backup_source: The restore stamp's ``backup_source``.
    :return: The recorded S3/GCS transport, or ``None``.
    """
    lookup_engine = create_async_engine(extensions_engine.url, poolclass=NullPool)
    try:
        async with get_async_session_maker_from_engine(lookup_engine)() as session:
            return await MysqlBackupRunManager.catalogued_source_transport(
                session, key, backup_source
            )
    finally:
        await lookup_engine.dispose()


def _sync_catalogued_transport_for_stamp(
    task: Task, stored_form: dict[str, Any]
) -> CataloguedSourceTransport | None:
    """Look up a catalogued transport via the NullPool sync bridge.

    Fallback when unit tests call the repairer/reconstructor without running the
    batch preparer. Production backfill always prefetches into ``ctx.extras``.

    :param task: The restore task being repaired or reconstructed.
    :param stored_form: The undeclared form stamp or reconstructed body.
    :return: The catalogued transport, or ``None`` on miss / failure.
    """
    resolved = transport_cache_key(task, stored_form)
    if resolved is None:
        return None
    cache_key, service_key = resolved
    try:
        return _run_coro_sync(
            _fetch_catalogued_transport(service_key, cache_key.backup_source)
        )
    except Exception:  # noqa: BLE001 — catalog being down must never fail backfill
        _log.warning(
            "Catalog source_transport lookup failed for backup_source=%r; "
            "falling back to inference",
            cache_key.backup_source,
            exc_info=True,
        )
        return None


def _catalogued_transport_from_ctx(
    task: Task,
    form: dict[str, Any],
    ctx: FormBackfillContext,
) -> Any:
    """Return the catalogued transport using the batch prefetch when present.

    When :func:`prepare_mysql_restores_catalog_transports` has filled
    ``ctx.extras``, look up there and never open the sync bridge. Absent that
    key (unit tests calling the repairer/reconstructor directly), fall through
    to the NullPool path owned by this module.

    :param task: The restore task being repaired or reconstructed.
    :param form: The undeclared form stamp or reconstructed body.
    :param ctx: Shared backfill context carrying optional catalog prefetch.
    :return: The catalogued transport, or ``None``.
    """
    transports = ctx.extras.get(CATALOG_TRANSPORTS_EXTRA)
    if isinstance(transports, dict):
        context: CatalogTransportContext = transports
        return catalogued_transport_for_stamp(task, form, context=context)
    return _sync_catalogued_transport_for_stamp(task, form)


async def prepare_mysql_restores_catalog_transports(
    tasks: Sequence[Task],
    ctx: FormBackfillContext,
) -> None:
    """Prefetch catalogued S3/GCS transports for this app's active restore tasks.

    Runs once before the per-task loop on the request event loop against the sep
    session maker — one session and one batched SELECT — so the sync
    repairer/reconstructor never pays a per-task thread+loop+NullPool spin-up.
    Stores the map on ``ctx.extras`` under :data:`CATALOG_TRANSPORTS_EXTRA`.

    :param tasks: The active restore tasks for this backfill app.
    :param ctx: Shared backfill context to receive the prefetch map.
    """
    items: list[tuple[Task, dict[str, Any]]] = []
    for task in tasks:
        form = _form_for_catalog_lookup(task, ctx)
        if form is not None:
            items.append((task, form))
    pending = pending_catalog_transport_lookups(items)
    if not pending:
        ctx.extras[CATALOG_TRANSPORTS_EXTRA] = {}
        return

    try:
        async with get_async_session_maker()() as session:
            transports: CatalogTransportContext = (
                await MysqlBackupRunManager.catalogued_source_transports(
                    session, pending
                )
            )
    except Exception:  # noqa: BLE001 — catalog down must not abort the batch
        _log.warning(
            "Catalog source_transport session failed during form backfill; "
            "falling back to inference",
            exc_info=True,
        )
        transports = dict.fromkeys(pending, None)
    ctx.extras[CATALOG_TRANSPORTS_EXTRA] = transports


def reconstruct_mysql_restores_form(
    task: Task,
    ctx: FormBackfillContext,
) -> dict[str, Any] | None:
    """Rebuild a :class:`~app.extensions.apps.mysql_backups.restore.models.RestoreCreate` body from a legacy task.

    Wraps :func:`~app.extensions.apps.mysql_backups.restore.deps.parse_restore_task_data`,
    resolves ``service_id`` / ``schema_id`` from inventory when possible, and drops
    parse keys that are not on the create model (for example ``host`` / ``database`` /
    ``name``).

    :param task: The persisted mysql restores task row.
    :param ctx: Shared backfill context carrying the inventory lookup tables.
    :return: A create-model-shaped dict, or ``None`` when reconstruction fails.
    """
    meta = require_run_python_meta(task)
    if meta is None:
        return None

    try:
        parsed = parse_restore_task_data({"name": task.name, "data": task.data})
    except (KeyError, TypeError, yaml.YAMLError):
        return None

    hostname = parsed.get("hostname")
    backup_type = parsed.get("backup_type")
    backup_source = parsed.get("backup_source")
    if (
        not isinstance(hostname, str)
        or not hostname.strip()
        or not isinstance(backup_type, str)
        or not backup_type.strip()
        or not isinstance(backup_source, str)
        or not backup_source.strip()
    ):
        return None

    normalized_backup_type = backup_type.strip()
    service_id = _resolve_restore_service_id(parsed, meta, ctx)
    if normalized_backup_type == BackupType.MYDUMPER.value and service_id is None:
        return None

    schema_id = _resolve_restore_schema_id(
        service_id,
        parsed.get("database"),
        ctx,
    )

    form_fields = {
        key: value
        for key, value in parsed.items()
        if key in _RESTORE_FORM_FIELDS
        and key not in _EXPLICIT_FORM_KEYS
        and key not in _PARSE_ONLY_KEYS
        and value is not None
    }

    body: dict[str, Any] = {
        "task_name": task.name,
        "hostname": hostname.strip(),
        "backup_type": normalized_backup_type,
        "backup_source": backup_source.strip(),
        "alert_on_fail": task.alert_on_fail,
        **form_fields,
    }
    if service_id is not None:
        body["service_id"] = service_id
    if schema_id is not None:
        body["schema_id"] = schema_id
    # A reconstruction is stored state, not a submission, so it takes the same
    # repair a stamp does rather than only the inference — including a catalogued
    # S3/GCS transport when one is available. Skip the lookup when the body
    # already declares its source (eager args would still evaluate otherwise).
    if body.get("source_transport") is not None:
        return repair_source_declaration(body) or body
    return (
        repair_source_declaration(
            body,
            catalogued_transport=_catalogued_transport_from_ctx(task, body, ctx),
        )
        or body
    )


def repair_mysql_restores_stamp(
    stored_form: dict[str, Any],
    task: Task,
    ctx: FormBackfillContext,
) -> dict[str, Any] | None:
    """Declare the source of a stamp that does not describe its own values.

    The stamp is a full model dump, so one predating the controls carries the
    ``percona`` / ``22`` / ``s3cmd`` defaults the gates now reject, and one
    predating the key-file gate can name a key file its declared format does not
    admit. The shared repair settles both, which is what makes the returned body
    valid on its own terms: a body still carrying values its declarations forbid
    would fail validation, and the orchestrator records that as
    ``skipped_invalid`` rather than surfacing it.

    What this adds over the re-validation the orchestrator performs anyway is the
    decision of whether a repair is owed at all; the repair call keeps the
    returned dict correct without relying on that downstream pass.

    Prefers a matching catalog ``source_transport`` (S3/GCS) over field inference
    — the same path the edit-form response builder uses — so a repaired stamp
    lands on the transport the backup run recorded when one is available. The
    catalog map is the once-per-app prefetch on ``ctx.extras`` when the batch
    preparer ran; stamps that already declare ``source_transport`` skip the
    lookup entirely.

    :param stored_form: A copy of the task's existing ``data['_form']``.
    :param task: The stamped task row (catalog key / meta for the lookup).
    :param ctx: Shared backfill context (inventory lookups plus optional catalog
        prefetch).
    :return: The repaired form, or ``None`` when the stamp already describes its
        source.
    """
    if stored_form.get("source_transport") is not None:
        return repair_source_declaration(stored_form)
    return repair_source_declaration(
        stored_form,
        catalogued_transport=_catalogued_transport_from_ctx(task, stored_form, ctx),
    )


FORM_BACKFILL_ENTRY = FormBackfillEntry(
    app_key="mysql_backups/restore",
    owner=OWNER,
    create_model=RestoreCreate,
    reconstructor=reconstruct_mysql_restores_form,
    stamp_repairer=repair_mysql_restores_stamp,
    batch_preparer=prepare_mysql_restores_catalog_transports,
)
