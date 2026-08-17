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

"""Run one probe sweep: inventory, executor mapping, dispatch, facts.

This is the half of discovery that cannot be done from PMM. Everything PMM can
derive for itself -- identity, versions, replica-set state, reachability, load -- it
reads from its own inventory and VictoriaMetrics. What is left needs a process on the
database host to answer: the command line a mongod was started with, the config file
it read, and above all the *installed* binary version as against the *running* server
the metrics report. Their divergence is the upgraded-but-not-restarted case, and no
metric anywhere carries it.

The dispatch machinery lives here: :mod:`~app.sep.apps.pom_discovery.inventory`,
:mod:`~app.sep.apps.pom_discovery.mapping`, :mod:`~app.sep.apps.pom_discovery.dispatch`
and the :mod:`~app.sep.apps.pom_discovery.payload` package, inherited from ``pom_worker``
when that app was retired. An upgrade app and a restart app will want exactly the same
four, so they will want a shared home; this is where they live until there is a second
caller to justify one.
"""

import logging
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.requests import RemoteAPI
from app.core.security import require_internal_token
from app.core.utils.date_time import utc_now
from app.inventory.config import inventory_settings
from app.sep.apps.pom_discovery.config import pom_discovery_settings
from app.sep.apps.pom_discovery.crud import (
    ProbeRunManager,
    prune_runs,
    upsert_host,
    upsert_service,
)
from app.sep.apps.pom_discovery.dispatch import HostProbeResult, probe_all
from app.sep.apps.pom_discovery.enumeration import (
    build_hosts,
    InventoryHost,
    list_inventory_nodes,
)
from app.sep.apps.pom_discovery.inventory import (
    InventoryService,
    list_mongodb_services,
)
from app.sep.apps.pom_discovery.mapping import get_executor_hosts, map_services
from app.sep.apps.pom_discovery.models import (
    NodeResolution,
    ProbeRun,
    ProbeRunStatus,
)
from app.sep.config import sep_settings
from app.sep.db import get_async_session_maker

logger = logging.getLogger(__name__)

#: The fields the probe contributes, mapped out of one probe record.
#:
#: ``installed_version`` is the one this app exists for. The rest divide in two: facts
#: nothing else has either (``config_path``, ``argv``, the OS pair) and fallbacks the
#: consumer's precedence table puts *behind* metrics (``version``, ``state``), which
#: therefore surface only where the exporter had nothing to say about a service.
PROBE_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("installed_version", ("binary_version",)),
    ("version", ("database", "db_version")),
    ("git_version", ("database", "git_version")),
    ("storage_engine", ("database", "storage_engine")),
    ("replication_set", ("database", "set_name")),
    ("config_path", ("process", "config_path")),
    ("argv", ("process", "argv")),
    ("server_process", ("process", "program")),
    ("server_running", ("process", "running")),
    ("uptime_seconds", ("process", "uptime_sec")),
    ("os", ("system", "os_name")),
    ("kernel", ("system", "kernel")),
)


async def _build_clients() -> tuple[RemoteAPI, RemoteAPI]:
    """Construct the inventory and tasks API clients outside request context.

    :return: The inventory and tasks API clients.
    """
    inventory_api = await settings.get_remote_api(
        endpoint=sep_settings.INVENTORY_ENDPOINT,
        ssl_cafile=settings.SSL_CAFILE,
        ssl_keyfile=inventory_settings.SSL_KEYFILE,
        ssl_certfile=inventory_settings.SSL_CERTFILE,
        logger_name="inventory_api",
    )
    tasks_api = await settings.get_remote_api(
        endpoint=sep_settings.TASKS_ENDPOINT,
        ssl_cafile=settings.SSL_CAFILE,
        logger_name="tasks_api",
    )
    return inventory_api, tasks_api


def _dig(record: dict[str, Any], path: tuple[str, ...]) -> Any:
    """Read a nested value out of a probe record.

    :param record: The probe record.
    :param path: The key path.
    :return: The value, or ``None`` when any step is missing.
    """
    node: Any = record
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def build_facts(
    service: InventoryService, record: dict[str, Any], observed_at: str
) -> list[dict[str, Any]]:
    """Turn one probe record into facts the consumer can merge.

    Keyed by **PMM's** service UUID, not SEP's inventory id. That translation is the
    whole reason this function exists rather than the caller storing records: the
    consumer joins facts against its own services table, where SEP's integer key means
    nothing. A service inventory holds no ``external_id`` for contributes no facts --
    they would be unjoinable, and storing unjoinable facts only makes the run look
    more productive than it was.

    :param service: The inventory service the record is about.
    :param record: One probe record.
    :param observed_at: When the probe ran, ISO 8601.
    :return: The facts, possibly empty.
    """
    if not service.external_id:
        return []

    facts = []
    for field, path in PROBE_FIELDS:
        value = _dig(record, path)
        if value is None or value in ("", []):
            continue
        facts.append(
            {
                "service_id": service.external_id,
                "field": field,
                "value": value,
                "observed_at": observed_at,
            }
        )
    return facts


def _record_for(entry: Any, host_results: dict[str, HostProbeResult]) -> dict | None:
    """Return the probe record for one mapped service, if it answered.

    :param entry: The mapped service.
    :param host_results: Probe results keyed by executor host.
    :return: The record, or ``None``.
    """
    if entry.resolution == NodeResolution.ORPHANED:
        return None
    result = host_results.get(entry.executor_host or "")
    if result is None:
        return None
    # Keyed by service *name*: that is what the payload echoes back in each NDJSON
    # record, because build_config sends the name as the target's identity. The
    # service id never reaches the node.
    return result.records.get(entry.service.name)


#: Probe-record fields that describe the **host** rather than any service on it.
#:
#: Lifted from the payload's own host record, which it prints once per dispatch
#: whether or not the host runs a database. Keeping these on the host row is what
#: stops ``repo.reachable`` being stored three times on a host running three mongods,
#: and those three copies being free to disagree once a partial sweep updates some and
#: not others.
HOST_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("os", ("system", "os_name")),
    ("kernel", ("system", "kernel")),
)

#: Probe-record fields that belong to one **service**.
SERVICE_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("probe_status", ("status",)),
    ("installed_version", ("binary_version",)),
    ("version", ("database", "db_version")),
    ("git_version", ("database", "git_version")),
    ("storage_engine", ("database", "storage_engine")),
    ("replication_set", ("database", "set_name")),
    ("config_path", ("process", "config_path")),
    ("argv", ("process", "argv")),
    ("server_process", ("process", "program")),
    ("server_running", ("process", "running")),
    ("uptime_seconds", ("process", "uptime_sec")),
)


def build_document(
    record: dict[str, Any],
    fields: tuple[tuple[str, tuple[str, ...]], ...],
    collected_at: str,
) -> dict[str, Any]:
    """Build one ``observed`` document out of a probe record.

    ``collected_at`` sits on the document rather than on each field: everything in one
    probe is collected at the same instant, and the granularity that can genuinely
    differ is the row -- a host can be reachable while a mongod on it is not, and those
    are already two rows.

    :param record: One probe record.
    :param fields: The ``(key, path)`` pairs to lift out of it.
    :param collected_at: When the probe ran, ISO 8601.
    :return: The document, always carrying at least ``collected_at``.
    """
    document: dict[str, Any] = {"collected_at": collected_at}
    for key, path in fields:
        value = _dig(record, path)
        if value is None or value in ("", []):
            continue
        document[key] = value
    return document


@dataclass
class SweepOutcome:
    """Carry everything one sweep produced.

    A dataclass rather than the tuple this used to return: the counters, the facts
    and now the per-service records are three different things, and positional
    unpacking of six values at the call site said which was which only by convention.

    :param total: Services inventory reported.
    :param resolved: ...of which mapped to a live executor host.
    :param orphaned: ...of which did not.
    :param answered: Services whose host returned a usable record.
    :param facts: The collected facts.
    :param nodes: One record per mapped service; see :class:`ProbeRun`.
    :param hosts: The hosts in scope this sweep, whether or not they carry a service.
    :param host_documents: The ``observed`` document per host that answered, keyed by
        executor host -- the level those attributes belong to.
    :param service_documents: The ``observed`` document per service that answered,
        keyed by PMM's service id.
    :param service_errors: Why a service did not answer, keyed by PMM's service id.
        Only for services a run actually attempted: an entity nobody targeted must
        not have its timestamps touched at all.
    :param seen: ``(service, node_id)`` for every service PMM knows that resolved to
        a host in scope, orphans included -- all of them get a row.
    :param attempted: PMM's service ids for the subset this run actually probed. The
        rest keep the freshness columns they already had.
    :param dispatched: Executor hosts a payload was actually sent to. A host with an
        executor and no MongoDB service is *not* in here: dispatch is driven by
        targets, so nothing ran there. Recording it as a failed attempt would have it
        accumulate a failure every sweep for a condition that is not a failure --
        probing a host that has no database is §11 work and does not exist yet.
    :param host_errors: Why a host did not answer, keyed by PMM's node id.
    """

    total: int = 0
    resolved: int = 0
    orphaned: int = 0
    answered: int = 0
    facts: list[dict[str, Any]] = dc_field(default_factory=list)
    nodes: list[dict[str, Any]] = dc_field(default_factory=list)
    hosts: list[InventoryHost] = dc_field(default_factory=list)
    host_documents: dict[str, dict[str, Any]] = dc_field(default_factory=dict)
    service_documents: dict[str, dict[str, Any]] = dc_field(default_factory=dict)
    service_errors: dict[str, str] = dc_field(default_factory=dict)
    seen: list[tuple[InventoryService, str]] = dc_field(default_factory=list)
    attempted: set[str] = dc_field(default_factory=set)
    dispatched: set[str] = dc_field(default_factory=set)
    host_errors: dict[str, str] = dc_field(default_factory=dict)


async def _sweep(observed_at: str) -> SweepOutcome:
    """Map, probe and collect, without touching the run row.

    Split out so :func:`run_probe` reads as the lifecycle it is -- create, work,
    record -- rather than interleaving the two.

    :param observed_at: When the sweep began, ISO 8601, stamped on every fact.
    :return: What the sweep reached, collected and saw per service.
    """
    inventory_api, tasks_api = await _build_clients()

    # Both services authenticate; outside request context there is no user session to
    # borrow, so the sweep rides the internal service token the same way the scheduled
    # inventory sync does. ``auth`` is a sync context manager setting a header for its
    # block, so every call that needs it has to be made inside.
    token = require_internal_token()
    with inventory_api.auth(token), tasks_api.auth(token):
        services = await list_mongodb_services(inventory_api)
        nodes = await list_inventory_nodes(inventory_api)
        executor_hosts = await get_executor_hosts(tasks_api)
        mapped = map_services(services, executor_hosts)
        # Hosts are enumerated from nodes rather than derived from the services just
        # mapped: a host with no database has no service to derive it from, and that
        # is the host worth having a row for.
        hosts = build_hosts(nodes, services, executor_hosts)
        # Every host with an executor is dispatched to, service or no service:
        # a machine with a PMM client and no database is the one an install
        # decision is about, and it has no service to be reached through.
        host_results = await probe_all(
            tasks_api,
            mapped,
            executor_hosts=[host.executor_host for host in hosts if host.executor_host],
        )

    outcome = SweepOutcome(total=len(mapped), hosts=hosts, dispatched=set(host_results))
    # One document per host that answered, from the host's own record rather than
    # from whichever of its services happened to report.
    for executor_host, result in host_results.items():
        if result.host_record is not None:
            outcome.host_documents[executor_host] = build_document(
                result.host_record, HOST_FIELDS, observed_at
            )

    node_ids = _index_hosts(outcome)

    for entry in mapped:
        host_result = host_results.get(entry.executor_host or "")
        record = _record_for(entry, host_results)
        service_facts = (
            build_facts(entry.service, record, observed_at) if record else []
        )

        if entry.resolution == NodeResolution.ORPHANED:
            outcome.orphaned += 1
        else:
            outcome.resolved += 1
            if record:
                outcome.answered += 1
                outcome.facts.extend(service_facts)

        outcome.nodes.append(
            {
                # PMM's service UUID, as everywhere else in this app. Null where
                # inventory holds none, which is also why such a service can
                # contribute no facts.
                "service_id": entry.service.external_id,
                # Carried so a reader is not left joining UUIDs by hand. It is what
                # the payload echoes back per record, so it is the app's own key too.
                "service_name": entry.service.name,
                "executor_host": entry.executor_host,
                "resolution": str(entry.resolution),
                "answered": bool(record),
                # The host's number, repeated on each service it served: one dispatch
                # covers every target on a host, so there is no per-service time to
                # report and inventing one would be a lie about what was measured.
                "duration_seconds": host_result.duration_seconds
                if host_result
                else None,
                "facts_collected": len(service_facts),
                "error": host_result.error if host_result else None,
            }
        )

        _record_entity(outcome, entry, record, host_result, node_ids, observed_at)

    return outcome


def _index_hosts(outcome: SweepOutcome) -> dict[str | None, str]:
    """Index the enumerated hosts by every name a service might know them by.

    A service carries its node's *name and address*; the host rows carry PMM's node
    id. This is the one place the two are joined, and it is why enumeration keeps
    both.

    :param outcome: The sweep in progress.
    :return: Node ids keyed by host name and address.
    """
    node_ids: dict[str | None, str] = {}
    for host in outcome.hosts:
        node_ids[host.name] = host.node_id
        if host.address:
            node_ids.setdefault(host.address, host.node_id)
    return node_ids


def _record_entity(
    outcome: SweepOutcome,
    entry: Any,
    record: dict[str, Any] | None,
    host_result: HostProbeResult | None,
    node_ids: dict[str | None, str],
    observed_at: str,
) -> None:
    """Fold one mapped service into the entity writes the sweep will make.

    An orphan still gets a row -- it is a service PMM knows about, and a listing that
    hid it would report a healthier estate than exists. What it does not get is an
    *attempt*: nothing was run against it, so marking it failed would make a host
    whose executor is simply absent look like a host that refused to answer.

    :param outcome: The sweep in progress.
    :param entry: The mapped service.
    :param record: Its probe record, or ``None`` when it did not answer.
    :param host_result: The dispatch result for its executor host.
    :param node_ids: Node ids keyed by host name and address.
    :param observed_at: When the sweep began, ISO 8601.
    """
    if entry.service.external_id is None:
        # No PMM service id, no row: the key is what the consumer joins on, and an
        # unkeyable row could never be read back.
        return

    node_id = node_ids.get(entry.service.node_name) or node_ids.get(
        entry.service.node_address
    )
    if node_id is None:
        logger.warning(
            "POM discovery: not storing service %r -- its node (name=%r address=%r) "
            "is not in the enumerated estate",
            entry.service.name,
            entry.service.node_name,
            entry.service.node_address,
        )
        return

    outcome.seen.append((entry.service, node_id))
    if entry.resolution == NodeResolution.ORPHANED:
        return
    outcome.attempted.add(entry.service.external_id)

    if record is None:
        outcome.service_errors[entry.service.external_id] = (
            host_result.error
            if host_result and host_result.error
            else "the host answered, but returned no record for this service"
        )
        return

    outcome.service_documents[entry.service.external_id] = build_document(
        record, SERVICE_FIELDS, observed_at
    )


async def _persist_estate(outcome: SweepOutcome, run_id: UUID) -> None:
    """Write what the sweep saw into ``pom.host`` and ``pom.service``.

    Hosts first, and in one transaction with the services: ``pom.service.node_id`` is
    a real foreign key, so a service whose host row does not exist yet cannot be
    inserted.

    Every enumerated entity is written; only the ones this run actually probed have
    their freshness columns moved. A host with no executor is *seen* every sweep and
    *probed* by none of them, so its row and its ``executor_host`` stay current while
    its failure history stays where it was -- which is what keeps "unreachable for
    three days" from resetting to "unreachable since the last sweep".

    :param outcome: What the sweep produced.
    :param run_id: The run being recorded.
    """
    session_maker = get_async_session_maker()
    async with session_maker() as session:
        for host in outcome.hosts:
            document = outcome.host_documents.get(host.executor_host or "")
            attempted = host.executor_host in outcome.dispatched
            await upsert_host(
                session,
                node_id=host.node_id,
                name=host.name,
                address=host.address,
                executor_host=host.executor_host,
                observed=document,
                error=(
                    None
                    if document
                    else "the host has an executor but returned no probe record"
                ),
                run_id=run_id,
                attempted=attempted,
            )
        # Before the services: ``pom.service.node_id`` is a real foreign key, so the
        # host rows have to be in the transaction first.
        await session.flush()

        for service, node_id in outcome.seen:
            service_id = service.external_id or ""
            await upsert_service(
                session,
                service_id=service_id,
                node_id=node_id,
                name=service.name,
                port=service.port,
                role=None,
                observed=outcome.service_documents.get(service_id),
                error=outcome.service_errors.get(service_id),
                run_id=run_id,
                attempted=service_id in outcome.attempted,
            )
        await session.commit()


def _terminal_status(resolved: int, answered: int) -> ProbeRunStatus:
    """Conclude a sweep from what it reached.

    Orphans do not count against it: a service whose node runs no healthy executor is
    a fact about the estate, not a failure of the sweep. Resolving nothing at all is
    different -- that is POM's infrastructure being unavailable, which is exactly the
    condition the probe exists to surface.

    :param resolved: Services that mapped to a live executor host.
    :param answered: ...of which returned a record.
    :return: The status.
    """
    if not resolved:
        return ProbeRunStatus.FAILED
    if answered == resolved:
        return ProbeRunStatus.SUCCESS
    return ProbeRunStatus.PARTIAL


async def _fail_run(run_id: UUID, error: str) -> None:
    """Drive a run to ``FAILED`` after the sweep raised.

    :param run_id: The run's id.
    :param error: The failure detail.
    """
    session_maker = get_async_session_maker()
    async with session_maker() as session:
        failed = await ProbeRunManager.get(session, id=run_id)
        failed.status = ProbeRunStatus.FAILED
        failed.finished_at = utc_now()
        failed.error = error
        await ProbeRunManager.save(session, failed)


async def run_probe(execution_id: UUID | None = None) -> UUID:
    """Run one probe sweep and store its facts.

    The run row is created before the work starts so a caller can be answered with an
    id immediately, and only this function ever writes its terminal status.

    :param execution_id: An already-created run's id, passed by the trigger endpoint.
        ``None`` mints a fresh run.
    :return: The run's id.
    """
    session_maker = get_async_session_maker()
    async with session_maker() as session:
        if execution_id is None:
            run = await ProbeRunManager.save(session, ProbeRun())
        else:
            run = await ProbeRunManager.get(session, id=execution_id)
        run_id = run.id

    observed_at = utc_now().isoformat()
    try:
        outcome = await _sweep(observed_at)
    except Exception as exc:
        logger.exception("POM discovery: sweep %s failed", run_id)
        await _fail_run(run_id, str(exc))
        return run_id

    # The estate goes in before the run reaches a terminal status, so a reader that
    # sees a finished run always finds the rows that run produced.
    await _persist_estate(outcome, run_id)

    status = _terminal_status(outcome.resolved, outcome.answered)
    async with session_maker() as session:
        finished = await ProbeRunManager.get(session, id=run_id)
        finished.status = status
        finished.finished_at = utc_now()
        finished.services_total = outcome.total
        finished.services_resolved = outcome.resolved
        finished.services_orphaned = outcome.orphaned
        finished.services_answered = outcome.answered
        finished.facts = outcome.facts
        finished.nodes = outcome.nodes
        await ProbeRunManager.save(session, finished)
        await prune_runs(session, pom_discovery_settings.RUN_RETENTION)

    logger.info(
        "POM discovery: sweep %s %s -- %d service(s), %d resolved, %d answered, %d fact(s)",
        run_id,
        status,
        outcome.total,
        outcome.resolved,
        outcome.answered,
        len(outcome.facts),
    )
    return run_id
