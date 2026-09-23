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

"""Define dependencies for the Restores plugin."""

import asyncio
import logging
from collections.abc import Coroutine, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, TypeVar

import yaml
from fastapi import Body
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.exceptions import (
    HTTPNotFoundException,
    HTTPUnprocessableEntityException,
)
from app.inventory.models import ServiceTypeEnum
from app.sep.api.task_history_actors import task_actor_fields
from app.sep.apps.framework import build_default_task_response
from app.sep.apps.framework.spec import RESERVED_FORM_KEY, stamp_form_input
from app.sep.apps.meta_keys import SERVICE_NAME_META_KEY
from app.sep.apps.mysql_backups.crud import MysqlBackupRunManager
from app.sep.apps.mysql_backups.models import (
    BackupType,
    CatalogServiceKey,
    CataloguedSourceTransport,
    UNKNOWN_SERVICE_SENTINEL,
)
from app.sep.apps.mysql_backups.restore.models import (
    repair_source_declaration,
    RestoreCreate,
    RestoresResponse,
)
from app.sep.apps.mysql_backups.restore.spec import (
    build_restore_spec,
    RestoreResolved,
)
from app.sep.db import get_async_session_maker
from app.sep.db.engine import engine as sep_engine
from app.sep.deps import get_created_entity, get_username_mapping, InventoryAPI
from app.sep.models import SyncInventoryEntityTypeEnum
from app.tasks.models import Task, TaskHistoryStatusEnum, TaskWrite

_log = logging.getLogger(__name__)
_T = TypeVar("_T")

#: Prefetched catalog transports keyed by ``(service_id, service_name, backup_source)``.
CatalogTransportContext = Mapping[
    tuple[int | None, str, str], CataloguedSourceTransport | None
]


@dataclass(frozen=True, slots=True)
class RestoreResponseContext:
    """Bound once per list/detail/create build for the restore response builder.

    Carries the username map every task app resolves actors through, plus the
    catalog transport prefetch this app batches for undeclared stamps.
    """

    usernames: Mapping[str, str] = field(default_factory=dict)
    transports: CatalogTransportContext = field(default_factory=dict)


async def resolve_restore_entities(
    form: RestoreCreate, inventory_api: InventoryAPI
) -> RestoreResolved:
    """Resolve the inventory entities a restore form references.

    MyDumper always resolves its MySQL service (eager-raising when ``service_id``
    is unset or stale), splits the service address into ``dest_host`` / ``dest_port``,
    and resolves the optional schema into the restore ``database``. XtraBackup and
    Binlog have no destination service: a ``service_id`` of ``None`` or the
    ``UNKNOWN_SERVICE_SENTINEL`` placeholder skips the lookup, and a stale id whose
    service was deleted degrades to a node-only annotation on a 404.

    ``ServiceRef(allow_custom=True)`` also lets the form submit a typed service
    name instead of an inventory id. A name is never a valid detail-route segment,
    so it annotates XtraBackup and Binlog restores as-is and is rejected for
    MyDumper, which needs the service address to derive its destination.

    A resolved service whose address carries no port yields ``dest_host`` alone,
    and the payload applies its own ``3306`` default. One resolving to no address
    at all is rejected rather than tolerated: an unset ``dest_host`` drops
    ``DEST_HOST`` from the emitted config, which the payload reads as
    ``localhost`` and loads into whatever MySQL runs on the executor instead of
    the destination the operator chose.

    :param form: The validated restore create form.
    :param inventory_api: The Inventory API used to resolve the references.
    :return: The resolved facts fed into :func:`build_restore_spec`.
    :raises HTTPException: When a MyDumper service reference is a typed name or the
        unknown-service placeholder, its lookup fails, or it resolves to a service
        carrying no address; or when a non-MyDumper lookup fails with a status
        other than 404.
    """
    if form.backup_type == BackupType.MYDUMPER:
        if form.service_id is None or not form.service_id.isdecimal():
            raise HTTPUnprocessableEntityException(
                detail=(
                    "Destination Database Service must be an existing MySQL service "
                    "for a MyDumper restore"
                )
            )
        service = await get_created_entity(
            inventory_api,
            SyncInventoryEntityTypeEnum.SERVICE,
            int(form.service_id),
            type=ServiceTypeEnum.MYSQL,
        )
        host, _, port = (service.address or "").partition(":")
        dest_host = host.strip()
        if not dest_host:
            raise HTTPUnprocessableEntityException(
                detail=(
                    "Destination Database Service must resolve to a network address "
                    "for a MyDumper restore"
                )
            )
        port = port.strip()
        dest_port = int(port) if port else None
        database = None
        if (
            form.schema_id is not None
            and form.schema_id.isdigit()
            and int(form.schema_id) > 0
        ):
            schema = await get_created_entity(
                inventory_api,
                SyncInventoryEntityTypeEnum.SCHEMA,
                int(form.schema_id),
                service_id=service.id,
            )
            database = schema.name
        return RestoreResolved(
            service_name=service.name,
            dest_host=dest_host,
            dest_port=dest_port,
            database=database,
        )

    if form.service_id and form.service_id != UNKNOWN_SERVICE_SENTINEL:
        if not form.service_id.isdigit():
            return RestoreResolved(service_name=form.service_id)
        try:
            service = await get_created_entity(
                inventory_api,
                SyncInventoryEntityTypeEnum.SERVICE,
                int(form.service_id),
                type=ServiceTypeEnum.MYSQL,
            )
        except HTTPNotFoundException:
            return RestoreResolved()
        return RestoreResolved(service_name=service.name)

    return RestoreResolved()


async def build_restore_payload(
    form: Annotated[RestoreCreate, Body()],
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build the restore task payload for the derived JSON create route.

    The ``payload_builder`` the framework uses verbatim as the create dependency:
    resolve the form's references, then feed the shared pure
    :func:`build_restore_spec`, so a JSON-created task's payload stays
    byte-identical to a Jinja-form-created one.

    :param form: The JSON restore create body.
    :param inventory_api: The Inventory API used to resolve references.
    :return: The restore ``TaskWrite``.
    """
    resolved = await resolve_restore_entities(form, inventory_api)
    write = build_restore_spec(form, resolved)
    stamp_form_input(write, form)
    return write


def _extract_restore_config(task: Task) -> tuple[BackupType | None, Any, Any]:
    """Read backup type and destination host/port out of a restore task's config.

    :param task: The restore task to inspect.
    :return: The ``(backup_type, dest_host, dest_port)`` triple, each ``None`` when
        the config is absent or unparseable.
    """
    meta = task.data.get("meta") if task.data else None
    raw_config = meta.get("config") if meta else None
    if not raw_config:
        return None, None, None
    try:
        config = yaml.safe_load(raw_config)
    except yaml.YAMLError:
        config = None
    server_list = config.get("SERVER_LIST") if isinstance(config, dict) else None
    server = server_list[0] if isinstance(server_list, list) and server_list else None
    if not isinstance(server, dict):
        return None, None, None
    host = server.get("DEST_HOST")
    port = server.get("DEST_PORT")
    raw_type = server.get("BACKUP_TYPE")
    if raw_type is None:
        return None, host, port
    try:
        return BackupType(raw_type), host, port
    except ValueError:
        return None, host, port


def _catalog_service_key_for_stamp(
    task: Task, stored_form: dict[str, Any]
) -> CatalogServiceKey | None:
    """Build the catalog service key a stored restore stamp can query with.

    Prefers the inventory id from the stamp plus ``_service_name`` from task meta
    when both are present. A free-typed (non-decimal) ``service_id`` is treated as
    a name-only key. Returns ``None`` when neither a usable id nor a name is
    available — the caller then skips the catalog lookup.

    :param task: The restore task carrying optional ``meta._service_name``.
    :param stored_form: The undeclared ``_form`` stamp.
    :return: The catalog key, or ``None`` when the stamp cannot be scoped.
    """
    meta = task.data.get("meta") if task.data else None
    meta = meta if isinstance(meta, dict) else {}
    raw_name = meta.get(SERVICE_NAME_META_KEY)
    service_name = (
        raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else None
    )

    raw_id = stored_form.get("service_id")
    if raw_id is None:
        return (
            CatalogServiceKey(service_name=service_name, service_id=None)
            if service_name
            else None
        )

    sid = str(raw_id).strip()
    if not sid or sid == UNKNOWN_SERVICE_SENTINEL:
        return (
            CatalogServiceKey(service_name=service_name, service_id=None)
            if service_name
            else None
        )
    if not sid.isdecimal():
        return CatalogServiceKey(service_name=sid, service_id=None)
    try:
        parsed = int(sid)
    except ValueError:
        return None
    # Id alone still matches id-stamped rows; the name is only needed for the
    # ``service_id IS NULL`` fallback on pre-id catalog rows.
    return CatalogServiceKey(service_name=service_name or sid, service_id=parsed)


def _transport_cache_key(
    task: Task, stored_form: dict[str, Any]
) -> tuple[int | None, str, str] | None:
    """Return the prefetch map key for ``stored_form``, or ``None`` when unscoped.

    :param task: The restore task carrying optional service meta.
    :param stored_form: The undeclared ``_form`` stamp.
    :return: ``(service_id, service_name, backup_source)``, or ``None``.
    """
    backup_source = stored_form.get("backup_source")
    if not isinstance(backup_source, str) or not backup_source:
        return None
    key = _catalog_service_key_for_stamp(task, stored_form)
    if key is None:
        return None
    return (key.service_id, key.service_name, backup_source)


def pending_catalog_transport_lookups(
    items: Sequence[tuple[Task, dict[str, Any]]],
) -> dict[tuple[int | None, str, str], CatalogServiceKey]:
    """Build the batched catalog lookup map for undeclared restore forms.

    Shared by the list/detail response prefetch and the form-backfill batch
    preparer so both pay one ``catalogued_source_transports`` query. Forms that
    already declare ``source_transport`` are skipped — their repair/normalize
    path ignores a catalog hit anyway.

    :param items: ``(task, form)`` pairs to consider (stamps or reconstructed
        bodies).
    :return: Map from :func:`_transport_cache_key` to the scoping
        :class:`CatalogServiceKey`.
    """
    pending: dict[tuple[int | None, str, str], CatalogServiceKey] = {}
    for task, stored_form in items:
        if stored_form.get("source_transport") is not None:
            continue
        cache_key = _transport_cache_key(task, stored_form)
        if cache_key is None or cache_key in pending:
            continue
        service_key = _catalog_service_key_for_stamp(task, stored_form)
        if service_key is not None:
            pending[cache_key] = service_key
    return pending


def _run_coro_sync(coro: Coroutine[Any, Any, _T]) -> _T:
    """Run ``coro`` to completion from sync code, including under a running loop.

    Used by the sync form-backfill repairer (and as a fallback when no request
    context was bound). When no loop is running, ``asyncio.run`` is enough; when
    one is, the coroutine runs on a worker thread with its own loop. Callers must
    open any asyncpg work on a throwaway engine for that loop — see
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
    lookup_engine = create_async_engine(sep_engine.url, poolclass=NullPool)
    try:
        async with get_async_session_maker_from_engine(lookup_engine)() as session:
            return await MysqlBackupRunManager.catalogued_source_transport(
                session, key, backup_source
            )
    finally:
        await lookup_engine.dispose()


def _split_restore_context(
    context: RestoreResponseContext | Mapping[Any, Any] | None,
) -> tuple[Mapping[str, str], CatalogTransportContext | None]:
    """Split a bound context into the username map and optional transport prefetch.

    Accepts the composite :class:`RestoreResponseContext` the provider returns,
    a plain username map (actor-resolution unit tests), or a transport prefetch
    keyed by ``(service_id, service_name, backup_source)`` tuples (catalog unit
    tests). A plain username map yields ``transports=None`` so catalog lookups
    fall back to the sync bridge.

    :param context: The value bound as the builder's ``context`` keyword.
    :return: ``(usernames, transports)``; ``transports`` is ``None`` when the
        caller did not supply a prefetch map.
    """
    if context is None:
        return {}, None
    if isinstance(context, RestoreResponseContext):
        return context.usernames, context.transports
    if context and all(isinstance(key, tuple) for key in context):
        return {}, context  # type: ignore[return-value]
    return context, None


async def restore_response_context(
    *, tasks: Sequence[Task] = ()
) -> RestoreResponseContext:
    """Resolve usernames and prefetch catalogued transports for the request.

    Bound once per list/detail/create build as the builders' ``context``. The
    username map is the same resolution every task app applies to actor fields.
    Catalog transports run on the request event loop against the shared sep
    session maker — one session and one batched SELECT for the whole page — so
    the sync builder never pays a per-row thread+loop+NullPool spin-up. A
    session/query failure is recorded as ``None`` for every pending key so the
    builder falls through to inference without re-querying.

    :param tasks: The page (list) or singleton (detail/create) being rendered.
    :return: The username map plus a map from :func:`_transport_cache_key` to
        catalogued transport.
    """
    usernames = await get_username_mapping()
    stamp_items: list[tuple[Task, dict[str, Any]]] = []
    for task in tasks:
        data = task.data if isinstance(task.data, dict) else None
        stored_form = data.get(RESERVED_FORM_KEY) if data else None
        if isinstance(stored_form, dict):
            stamp_items.append((task, stored_form))
    pending = pending_catalog_transport_lookups(stamp_items)

    if not pending:
        return RestoreResponseContext(usernames=usernames, transports={})

    try:
        async with get_async_session_maker()() as session:
            transports = await MysqlBackupRunManager.catalogued_source_transports(
                session, pending
            )
    except Exception:  # noqa: BLE001 — session/query failure must not take out the page
        _log.warning(
            "Catalog source_transport session failed; falling back to inference",
            exc_info=True,
        )
        transports = dict.fromkeys(pending, None)
    return RestoreResponseContext(usernames=usernames, transports=transports)


def catalogued_transport_for_stamp(
    task: Task,
    stored_form: dict[str, Any],
    *,
    context: CatalogTransportContext | None = None,
) -> CataloguedSourceTransport | None:
    """Return the catalogued object-store transport for an undeclared stamp, if any.

    When ``context`` is provided (the once-per-request prefetch from
    :func:`restore_response_context`), look up there and never open a sync bridge
    — a miss means the catalog had nothing, not that the lookup was skipped.
    Without ``context`` (form backfill), fall back to the NullPool sync bridge.

    Failures without ``context`` yield ``None`` so the caller falls through to
    inference.

    :param task: The restore task being serialized.
    :param stored_form: The undeclared ``_form`` stamp.
    :param context: Optional prefetch map from :func:`restore_response_context`.
    :return: The catalogued transport, or ``None``.
    """
    cache_key = _transport_cache_key(task, stored_form)
    if cache_key is None:
        return None
    if context is not None:
        return context.get(cache_key)

    key = _catalog_service_key_for_stamp(task, stored_form)
    if key is None:
        return None
    backup_source = cache_key[2]
    try:
        return _run_coro_sync(_fetch_catalogued_transport(key, backup_source))
    except Exception:  # noqa: BLE001 — catalog being down must never fail the list
        _log.warning(
            "Catalog source_transport lookup failed for backup_source=%r; "
            "falling back to inference",
            backup_source,
            exc_info=True,
        )
        return None


def _declared_source_override(
    task: Task, *, context: CatalogTransportContext | None = None
) -> dict[str, Any]:
    """Return a ``data`` override declaring the source of a stamp that describes it poorly.

    The edit form seeds each field from the served stamp and falls back to the
    schema default where the stamp has no value, so a stamp written before the
    source controls existed would seed ``source_transport`` to ``local``. The
    gates then hide the SSH and object-store fields, and a hidden field is
    dropped from the submission entirely, so saving that form would discard
    credentials the restore still needs. The same holds for an AES-256 key file a
    stamp names without declaring the format that reveals it. Repairing the stamp
    here means the form opens on the source its stored values imply, keeping a key
    file the engine can read and dropping one it cannot.

    When a matching :class:`~app.sep.apps.mysql_backups.models.MysqlBackupRun`
    recorded an object-store ``source_transport``, that value is preferred over
    field inference — the same catalog-first path
    :func:`~app.sep.apps.mysql_backups.restore.models.repair_source_declaration`
    accepts via ``catalogued_transport``.

    Re-validating through :class:`RestoreCreate` rather than serving the repair
    directly keeps the served stamp exactly what a subsequent ``PUT`` would
    accept. It is tolerant of a stamp that cannot be validated at all, because
    this builder also serves the list route, where one unparseable task must not
    take out the whole page.

    :param task: The restore task being serialized.
    :param context: Optional prefetch map from :func:`restore_response_context`.
    :return: A single-key ``data`` override, or an empty mapping when the stamp
        already describes its source, is absent, or does not validate.
    """
    data = task.data
    if not data:
        return {}
    stored_form = data.get(RESERVED_FORM_KEY)
    if not isinstance(stored_form, dict):
        return {}
    repaired = repair_source_declaration(
        stored_form,
        catalogued_transport=catalogued_transport_for_stamp(
            task, stored_form, context=context
        ),
    )
    if repaired is None:
        return {}
    try:
        declared = RestoreCreate.model_validate(repaired).model_dump(mode="json")
    except ValidationError:
        return {}
    return {"data": {**data, RESERVED_FORM_KEY: declared}}


def build_restore_api_task_response(
    task: Task,
    status: TaskHistoryStatusEnum | None = None,
    *,
    last_executed_at: datetime | None = None,
    context: RestoreResponseContext | Mapping[Any, Any] | None = None,
) -> RestoresResponse:
    """Build a ``RestoresResponse`` for the JSON API list/detail routes.

    :param task: The restore task retrieved from the Tasks API.
    :param status: The latest known execution status for the task.
    :param last_executed_at: The task's most recent finish time (``max``
        ``finished_at``), or ``None`` until it has finished once.
    :param context: The :class:`RestoreResponseContext` bound by
        ``response_context_provider`` (usernames plus catalog transports), a
        plain username map, a catalog prefetch map, or ``None`` outside the
        JSON routes.
    :return: A validated restore task API response object.
    """
    usernames, transports = _split_restore_context(context)
    backup_type, host, port = _extract_restore_config(task)
    meta = task.data.get("meta") if task.data else None
    return build_default_task_response(
        RestoresResponse,
        task,
        status,
        last_executed_at=last_executed_at,
        extras={
            "backup_type": backup_type,
            "host": host,
            "port": port,
            "hostname": meta.get("target") if meta else None,
            **task_actor_fields(task, usernames),
            **_declared_source_override(task, context=transports),
        },
    )


def parse_restore_task_data(task: dict[str, Any]) -> dict[str, Any]:
    """Parse restore task data for editing.

    Extracts configuration from an existing restore task to populate the edit form.

    :param task: The task data retrieved from the Tasks API.
    :type task: dict[str, Any]
    :return: A dictionary containing parsed restore configuration.
    :rtype: dict[str, Any]
    """
    data = task["data"]
    meta = data["meta"]
    task_config = yaml.safe_load(meta["config"])
    server_config = task_config["SERVER_LIST"][0]
    all_servers_config = task_config.get("ALL_SERVERS", {})

    result = {
        "name": task["name"],
        "hostname": meta["target"],
        "backup_type": server_config["BACKUP_TYPE"],
        "service_id": None,
        "host": server_config.get("DEST_HOST"),
        "port": server_config.get("DEST_PORT") or 3306,
        "database": server_config.get("DATABASE"),
    }

    for config in [server_config, all_servers_config]:
        result.update(
            {k.lower(): v for k, v in config.items() if k.lower() not in result}
        )

    return result
