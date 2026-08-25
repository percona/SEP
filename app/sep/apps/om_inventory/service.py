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

The dispatch machinery lives here: :mod:`~app.sep.apps.om_inventory.inventory`,
:mod:`~app.sep.apps.om_inventory.mapping`, :mod:`~app.sep.apps.om_inventory.dispatch`
and the :mod:`~app.sep.apps.om_inventory.payload` package. An upgrade app and a restart
app will want exactly the same four, so they will want a shared home; this is where they
live until there is a second caller to justify one.
"""

import logging
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.requests import RemoteAPI
from app.core.security import require_internal_token
from app.core.utils.date_time import utc_now
from app.inventory.config import inventory_settings
from app.sep.apps.om_inventory.config import om_inventory_settings
from app.sep.apps.om_inventory.crud import (
    conflict_detail,
    conflicting_run,
    ProbeRunManager,
    prune_runs,
    upsert_host,
    upsert_service,
)
from app.sep.apps.om_inventory.dispatch import HostProbeResult, probe_all
from app.sep.apps.om_inventory.enumeration import (
    build_hosts,
    InventoryHost,
    list_inventory_nodes,
)
from app.sep.apps.om_inventory.inventory import (
    InventoryService,
    list_mongodb_services,
)
from app.sep.apps.om_inventory.mapping import (
    get_executor_states,
    map_services,
    usable_executor_hosts,
)
from app.sep.apps.om_inventory.models import (
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
    # Mongods running here that PMM has no service for. They are host observations
    # rather than service rows because there is no service id to key a row on -- see
    # the payload's find_unregistered. An arbiter is the ordinary case: it holds no
    # data, therefore no user documents, therefore SCRAM cannot authenticate and
    # `pmm-admin add mongodb` fails for it.
    ("unregistered_mongods", ("unregistered_mongods",)),
    # Whether this host can reach Percona's repository. Kept whole rather than
    # flattened to a boolean: "unreachable" is not actionable on its own, and the
    # status code, the latency and the proxy in effect are what tell an operator
    # whether to fix DNS, a certificate, or a proxy allow-list.
    ("repo", ("repo",)),
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


async def _sweep(observed_at: str, node_ids: list[str] | None = None) -> SweepOutcome:
    """Map, probe and collect, without touching the run row.

    Split out so :func:`run_probe` reads as the lifecycle it is -- create, work,
    record -- rather than interleaving the two.

    A scope narrows *everything downstream of enumeration*, not the enumeration
    itself: hosts are still listed from inventory, because that is how a scoped id is
    recognised as a host at all, and then everything outside the scope is dropped
    before a single dispatch is made. Nothing outside it is written, which is what
    makes §5.4's rule real -- an entity this run did not attempt keeps every timestamp
    it had, so refreshing one host cannot make the rest of the estate look failed.

    :param observed_at: When the sweep began, ISO 8601, stamped on every fact.
    :param node_ids: The hosts to refresh, or ``None`` for the whole estate.
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
        # Every known executor, not only the usable ones: a host served by a
        # registered-but-broken client has to resolve, or its row reports "no
        # executor" and sends the reader after an onboarding problem that is not
        # there. Dispatch still works from the usable subset.
        executor_states = await get_executor_states(tasks_api)
        mapped = map_services(services, usable_executor_hosts(executor_states))
        # Hosts are enumerated from nodes rather than derived from the services just
        # mapped: a host with no database has no service to derive it from, and that
        # is the host worth having a row for.
        hosts = build_hosts(nodes, services, executor_states)
        if node_ids:
            hosts, services, mapped = _narrow_to_scope(
                hosts, services, mapped, node_ids
            )
        # Every host with an executor is dispatched to, service or no service:
        # a machine with a PMM client and no database is the one an install
        # decision is about, and it has no service to be reached through.
        host_results = await probe_all(
            tasks_api,
            mapped,
            executor_hosts=[host.executor_host for host in hosts if host.has_executor],
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

        _record_entity(outcome, entry, record, host_result, node_ids, observed_at)

    outcome.nodes = _build_receipt(outcome, mapped, host_results, node_ids)
    return outcome


def _build_receipt(
    outcome: SweepOutcome,
    mapped: list[Any],
    host_results: dict[str, Any],
    node_ids: dict[str | None, str],
) -> list[dict[str, Any]]:
    """Record what the sweep attempted, one entry per **host**.

    Host-oriented rather than service-oriented, because a sweep attempts hosts. The
    receipt used to be a flat list of services, which meant a machine carrying a PMM
    client and no database - the case OM most exists to describe - appeared nowhere
    in it at all, however many times it was probed. A reader looking for
    ``pmm-client-node00`` found the sweep counted it and could not see it.

    One dispatch covers every service on a host, so the host owns the timing and the
    failure; its services carry only what is theirs. That is also why the duration
    used to be repeated identically across a host's services, which read as several
    measurements when it was one.

    :param outcome: The sweep in progress.
    :param mapped: The services, each with the executor host it resolved to.
    :param host_results: What each dispatch returned, keyed by executor host.
    :param node_ids: Node ids keyed by the names and addresses a service knows.
    :return: One entry per host, each carrying its services.
    """
    by_node: dict[str, list[dict[str, Any]]] = {}
    for entry in mapped:
        node_id = node_ids.get(entry.service.node_name) or node_ids.get(
            entry.service.node_address
        )
        record = _record_for(entry, host_results)
        by_node.setdefault(node_id or "", []).append(
            {
                # PMM's service UUID, as everywhere else in this app. Null where
                # inventory holds none.
                "service_id": entry.service.external_id,
                "service_name": entry.service.name,
                "answered": bool(record),
                "error": outcome.service_errors.get(entry.service.external_id or ""),
            }
        )

    receipt = []
    for host in outcome.hosts:
        result = host_results.get(host.executor_host or "")
        receipt.append(
            {
                "node_id": host.node_id,
                "host_name": host.name,
                "executor_host": host.executor_host,
                # How the executor was matched, or that it was not. `orphaned` is why
                # nothing ran, and it is not an error.
                "resolution": str(host.resolution),
                # Whether the *host* answered, which is a different question from
                # whether its services did: a host with no database can answer
                # perfectly well and have no services at all.
                "answered": bool(result and result.host_record is not None),
                "duration_seconds": result.duration_seconds if result else None,
                "error": (result.error if result else None)
                or outcome.host_errors.get(host.node_id),
                "services": by_node.get(host.node_id, []),
            }
        )
    return receipt


def _narrow_to_scope(
    hosts: list[InventoryHost],
    services: list[InventoryService],
    mapped: list[Any],
    node_ids: list[str],
) -> tuple[list[InventoryHost], list[InventoryService], list[Any]]:
    """Drop everything the caller did not ask about.

    Services are matched to hosts by name and address, as everywhere else in this app:
    a service knows its node's name, not PMM's node id, and this is the same join
    :func:`_index_hosts` does in the other direction.

    An id that names no enumerated host silently contributes nothing here, because the
    endpoint has already rejected it with a 404. Reaching this function it can only
    mean the estate changed between the request and the sweep, and refreshing the rest
    of the scope is a better answer than failing the run.

    :param hosts: Every enumerated host.
    :param services: Every MongoDB service.
    :param mapped: Every service paired with its executor.
    :param node_ids: The hosts to keep.
    :return: The hosts, services and mappings inside the scope.
    """
    wanted = set(node_ids)
    scoped_hosts = [host for host in hosts if host.node_id in wanted]

    names = {host.name for host in scoped_hosts}
    names |= {host.address for host in scoped_hosts if host.address}

    def on_scope(service: InventoryService) -> bool:
        return service.node_name in names or service.node_address in names

    scoped_services = [service for service in services if on_scope(service)]
    scoped_mapped = [entry for entry in mapped if on_scope(entry.service)]

    logger.info(
        "OM inventory: scoped to %d host(s) of %d, %d service(s) of %d",
        len(scoped_hosts),
        len(hosts),
        len(scoped_services),
        len(services),
    )
    return scoped_hosts, scoped_services, scoped_mapped


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
            "OM inventory: not storing service %r -- its node (name=%r address=%r) "
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


async def _finalise(
    session: AsyncSession, run_id: UUID, outcome: SweepOutcome
) -> ProbeRun:
    """Write what the sweep did onto its run row, and close it.

    A function rather than a block inside the sweep so the counters can be asserted
    without dispatching anything. They are the run's whole receipt, and every one of
    them is derived - a mistake here is invisible until someone reads a history and
    draws the wrong conclusion from it.

    Both sets are taken from the same lists the estate was written from rather than
    counted independently, so the receipt and the rows cannot disagree about what
    happened.

    :param session: The database session.
    :param run_id: The run being closed.
    :param outcome: What the sweep produced.
    :return: The stored row.
    """
    finished = await ProbeRunManager.get(session, id=run_id)
    finished.status = _terminal_status(outcome)
    finished.finished_at = utc_now()
    finished.services_total = outcome.total
    finished.services_resolved = outcome.resolved
    finished.services_orphaned = outcome.orphaned
    finished.services_answered = outcome.answered
    # Hosts as well as services, because a sweep attempts both. A host-only refresh
    # would otherwise report "0 of 0 services", which reads exactly like a run that
    # did nothing -- on the one host OM most exists to describe.
    finished.hosts_total = len(outcome.hosts)
    finished.hosts_probeable = sum(1 for host in outcome.hosts if host.has_executor)
    finished.hosts_answered = len(outcome.host_documents)
    finished.facts = outcome.facts
    finished.nodes = outcome.nodes
    return await ProbeRunManager.save(session, finished)


async def _persist_estate(outcome: SweepOutcome, run_id: UUID) -> None:
    """Write what the sweep saw into ``om.host`` and ``om.service``.

    Hosts first, and in one transaction with the services: ``om.service.node_id`` is
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
                # Passed separately from ``observed`` because it is not a probe
                # fact: SEP knows it without running anything, so it is refreshed
                # on every sweep like the host's name and address, including for
                # the hosts no probe was ever dispatched to.
                executor=host.executor_document,
                error=(
                    None
                    if document
                    else "the host has an executor but returned no probe record"
                ),
                run_id=run_id,
                attempted=attempted,
            )
        # Before the services: ``om.service.node_id`` is a real foreign key, so the
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


def _terminal_status(outcome: SweepOutcome) -> ProbeRunStatus:
    """Conclude a sweep from what it reached.

    Judged on **dispatches and services together**, not services alone. Services alone
    was right while every dispatch existed to reach one, and it stopped being right
    the moment a host could be probed for its own sake: a refresh of a machine with a
    PMM client and no database resolves no services at all, and would have been
    reported ``FAILED`` for doing exactly what it was asked. Measured that way on a
    scoped refresh of ``standalone-node00``, which is what prompted this.

    Orphans still do not count against a run: a service whose node runs no healthy
    executor is a fact about the estate, not a failure of the sweep. Reaching *nothing*
    is different -- no host answered and no service resolved -- and that is OM's
    infrastructure being unavailable, which is the condition the probe exists to
    surface.

    :param outcome: What the sweep produced.
    :return: The status.
    """
    attempted = len(outcome.dispatched) + outcome.resolved
    answered = len(outcome.host_documents) + outcome.answered

    if not attempted:
        return ProbeRunStatus.FAILED
    if answered == attempted:
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


async def run_probe(
    execution_id: UUID | None = None, node_ids: list[str] | None = None
) -> UUID:
    """Run one probe sweep and store its facts.

    The run row is created before the work starts so a caller can be answered with an
    id immediately, and only this function ever writes its terminal status.

    :param execution_id: An already-created run's id, passed by the trigger endpoint.
        ``None`` mints a fresh run.
    :param node_ids: The hosts to refresh, or ``None`` for the whole estate. Taken
        from the caller rather than read back off the run row so a scheduled sweep,
        which has no row until this function makes one, takes the same path.
    :return: The run's id.
    """
    session_maker = get_async_session_maker()
    async with session_maker() as session:
        if execution_id is None:
            run = await ProbeRunManager.save(session, ProbeRun(scope=node_ids))
        else:
            run = await ProbeRunManager.get(session, id=execution_id)
        run_id = run.id

        # The same single-flight check the trigger endpoint makes, repeated here
        # because **the schedule does not go through the endpoint**. Beat calls this
        # task directly, so with the check only in the handler a scheduled sweep would
        # start on top of one already dispatching. Both then enqueue the same job for
        # the same host, the Tasks layer refuses the duplicate, and the loser records
        # a 409 against a host that is perfectly healthy -- moving its failure
        # timestamps for a race rather than a fault. Measured happening on this
        # workspace's sandbox: two full sweeps 31 seconds apart, four healthy hosts
        # marked unanswered.
        #
        # Excluding this run's own row matters: the trigger endpoint creates it before
        # dispatching, so without that the task would refuse itself every time.
        blocking = await conflicting_run(
            session,
            node_ids,
            exclude=run_id,
            stale_after=om_inventory_settings.STALE_RUN_AFTER,
        )
        if blocking is not None:
            run.status = ProbeRunStatus.SKIPPED
            run.finished_at = utc_now()
            run.error = conflict_detail(blocking, node_ids)
            await ProbeRunManager.save(session, run)
            logger.info("OM inventory: sweep %s skipped -- %s", run_id, run.error)
            return run_id

    observed_at = utc_now().isoformat()
    try:
        outcome = await _sweep(observed_at, node_ids)
    except Exception as exc:
        logger.exception("OM inventory: sweep %s failed", run_id)
        await _fail_run(run_id, str(exc))
        return run_id

    # The estate goes in before the run reaches a terminal status, so a reader that
    # sees a finished run always finds the rows that run produced.
    await _persist_estate(outcome, run_id)

    async with session_maker() as session:
        await _finalise(session, run_id, outcome)
        await prune_runs(session, om_inventory_settings.RUN_RETENTION)
    status = _terminal_status(outcome)

    logger.info(
        "OM inventory: sweep %s %s -- %d service(s), %d resolved, %d answered, %d fact(s)",
        run_id,
        status,
        outcome.total,
        outcome.resolved,
        outcome.answered,
        len(outcome.facts),
    )
    return run_id
