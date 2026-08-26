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

"""Tests for legacy form backfill inventory service resolution."""

import logging
from types import SimpleNamespace

import pytest

from app.core.utils.date_time import utc_now
from app.inventory.crud import (
    NodeManager,
    RetiredInclusiveServiceManager,
    ServiceManager,
)
from app.inventory.models import Node, ServiceTypeEnum
from app.sep.apps.framework.form_backfill_inventory import (
    default_port_for_service_type,
    load_service_id_lookup,
    meta_service_hints,
    resolve_service_from_meta,
    SchemaIdLookup,
    ServiceIdLookup,
)
from app.sep.apps.framework.form_backfill_registry import FormBackfillContext
from app.sep.connectivity import CONNECTIVITY_META_HOST_KEY, CONNECTIVITY_META_PORT_KEY
from tests.app.factories import ServiceWriteFactory


def _service(
    service_id: int,
    *,
    service_type: ServiceTypeEnum,
    name: str,
    address: str,
    port: int | None,
) -> SimpleNamespace:
    """Build a minimal inventory service record for lookup tests."""
    return SimpleNamespace(
        id=service_id,
        type=service_type,
        name=name,
        port=port,
        node=SimpleNamespace(address=address),
    )


@pytest.mark.parametrize(
    ("service_type", "expected_port"),
    [
        (ServiceTypeEnum.MYSQL, 3306),
        (ServiceTypeEnum.POSTGRESQL, 5432),
    ],
)
def test_default_port_for_service_type(service_type, expected_port):
    """Return the conventional default port for supported service types."""
    assert default_port_for_service_type(service_type) == expected_port


def test_resolve_service_id_by_address():
    """Resolve a unique host/port pair to the inventory service id."""
    expected_service_id = 42
    lookup = ServiceIdLookup.from_services(
        [
            _service(
                expected_service_id,
                service_type=ServiceTypeEnum.MYSQL,
                name="db1",
                address="10.0.0.5",
                port=3306,
            )
        ]
    )

    assert (
        lookup.resolve(
            service_type=ServiceTypeEnum.MYSQL,
            host="10.0.0.5",
            port=3306,
        )
        == expected_service_id
    )


def test_resolve_service_id_uses_default_port_when_service_port_is_none():
    """Index services whose inventory row omits an explicit port."""
    expected_service_id = 7
    lookup = ServiceIdLookup.from_services(
        [
            _service(
                expected_service_id,
                service_type=ServiceTypeEnum.POSTGRESQL,
                name="pg-main",
                address="db.internal",
                port=None,
            )
        ]
    )

    assert (
        lookup.resolve(
            service_type=ServiceTypeEnum.POSTGRESQL,
            host="db.internal",
        )
        == expected_service_id
    )


def test_resolve_service_id_falls_back_to_service_name():
    """Use ``_service_name`` when the stored host does not match inventory."""
    expected_service_id = 99
    lookup = ServiceIdLookup.from_services(
        [
            _service(
                expected_service_id,
                service_type=ServiceTypeEnum.MYSQL,
                name="prod-mysql-1",
                address="10.0.0.5",
                port=3306,
            )
        ]
    )

    assert (
        lookup.resolve(
            service_type=ServiceTypeEnum.MYSQL,
            host="127.0.0.1",
            service_name="prod-mysql-1",
        )
        == expected_service_id
    )


def test_resolve_service_id_returns_none_for_ambiguous_address():
    """Skip tasks when multiple inventory services share the same host/port."""
    lookup = ServiceIdLookup.from_services(
        [
            _service(
                1,
                service_type=ServiceTypeEnum.MYSQL,
                name="db-a",
                address="10.0.0.5",
                port=3306,
            ),
            _service(
                2,
                service_type=ServiceTypeEnum.MYSQL,
                name="db-b",
                address="10.0.0.5",
                port=3306,
            ),
        ]
    )

    assert (
        lookup.resolve(
            service_type=ServiceTypeEnum.MYSQL,
            host="10.0.0.5",
            port=3306,
        )
        is None
    )


def test_meta_service_hints_prefers_connectivity_keys():
    """Read host/port from framework connectivity metadata before legacy stamps."""
    expected_port = 3307
    host, port, service_name = meta_service_hints(
        {
            CONNECTIVITY_META_HOST_KEY: "10.0.0.8",
            CONNECTIVITY_META_PORT_KEY: expected_port,
            "_service_host": "ignored",
            "_service_port": 3306,
            "_service_name": "mysql-prod",
        },
    )

    assert host == "10.0.0.8"
    assert port == expected_port
    assert service_name == "mysql-prod"


def test_meta_service_hints_honors_explicit_host_and_port_overrides():
    """Let YAML-derived host/port win over task meta when supplied."""
    expected_port = 5432
    host, port, service_name = meta_service_hints(
        {
            CONNECTIVITY_META_HOST_KEY: "10.0.0.8",
            CONNECTIVITY_META_PORT_KEY: 3307,
        },
        host="db.internal",
        port=expected_port,
    )

    assert host == "db.internal"
    assert port == expected_port
    assert service_name is None


def _mysql_lookup(*services: SimpleNamespace) -> ServiceIdLookup:
    """Build a MySQL service lookup, defaulting to one 10.0.0.9:3306 service."""
    if not services:
        services = (
            _service(
                21,
                service_type=ServiceTypeEnum.MYSQL,
                name="db1",
                address="10.0.0.9",
                port=3306,
            ),
        )
    return ServiceIdLookup.from_services(services)


def test_resolve_service_from_meta_resolves_by_address():
    """Resolve a service id from the meta connectivity host/port keys."""
    expected_service_id = 21
    ctx = FormBackfillContext(
        log=logging.getLogger("test"), service_lookup=_mysql_lookup()
    )
    meta = {CONNECTIVITY_META_HOST_KEY: "10.0.0.9", CONNECTIVITY_META_PORT_KEY: 3306}

    assert (
        resolve_service_from_meta(ctx, meta, ServiceTypeEnum.MYSQL)
        == expected_service_id
    )


def test_resolve_service_from_meta_honors_explicit_host_and_port():
    """Prefer explicit host/port overrides over meta connectivity keys."""
    expected_service_id = 22
    lookup = ServiceIdLookup.from_services(
        [
            _service(
                expected_service_id,
                service_type=ServiceTypeEnum.POSTGRESQL,
                name="pg1",
                address="db.internal",
                port=5432,
            )
        ]
    )
    ctx = FormBackfillContext(log=logging.getLogger("test"), service_lookup=lookup)
    meta = {CONNECTIVITY_META_HOST_KEY: "10.0.0.9", CONNECTIVITY_META_PORT_KEY: 3306}

    assert (
        resolve_service_from_meta(
            ctx,
            meta,
            ServiceTypeEnum.POSTGRESQL,
            host="db.internal",
            port=5432,
        )
        == expected_service_id
    )


def test_resolve_service_from_meta_falls_back_to_service_name():
    """Use ``_service_name`` when the stored host does not match."""
    expected_service_id = 23
    lookup = ServiceIdLookup.from_services(
        [
            _service(
                expected_service_id,
                service_type=ServiceTypeEnum.MYSQL,
                name="prod-mysql",
                address="10.0.0.9",
                port=3306,
            )
        ]
    )
    ctx = FormBackfillContext(log=logging.getLogger("test"), service_lookup=lookup)
    meta = {"_service_host": "127.0.0.1", "_service_name": "prod-mysql"}

    assert (
        resolve_service_from_meta(ctx, meta, ServiceTypeEnum.MYSQL)
        == expected_service_id
    )


def test_resolve_service_from_meta_returns_none_without_service_lookup():
    """Return ``None`` when the run has no inventory service lookup."""
    ctx = FormBackfillContext(log=logging.getLogger("test"), service_lookup=None)
    meta = {CONNECTIVITY_META_HOST_KEY: "10.0.0.9", CONNECTIVITY_META_PORT_KEY: 3306}

    assert resolve_service_from_meta(ctx, meta, ServiceTypeEnum.MYSQL) is None


def test_resolve_service_from_meta_returns_none_for_ambiguous_match():
    """Return ``None`` when the meta hints match more than one service."""
    ctx = FormBackfillContext(
        log=logging.getLogger("test"),
        service_lookup=_mysql_lookup(
            _service(
                1,
                service_type=ServiceTypeEnum.MYSQL,
                name="db-a",
                address="10.0.0.9",
                port=3306,
            ),
            _service(
                2,
                service_type=ServiceTypeEnum.MYSQL,
                name="db-b",
                address="10.0.0.9",
                port=3306,
            ),
        ),
    )
    meta = {CONNECTIVITY_META_HOST_KEY: "10.0.0.9", CONNECTIVITY_META_PORT_KEY: 3306}

    assert resolve_service_from_meta(ctx, meta, ServiceTypeEnum.MYSQL) is None


def _schema(schema_id: int, *, service_id: int, name: str) -> SimpleNamespace:
    """Build a minimal inventory schema record for lookup tests."""
    return SimpleNamespace(id=schema_id, service_id=service_id, name=name)


def test_resolve_schema_id_by_service_and_name():
    """Resolve a unique schema name on a parent service."""
    expected_schema_id = 15
    lookup = SchemaIdLookup.from_schemas(
        [_schema(expected_schema_id, service_id=4, name="appdb")]
    )

    assert lookup.resolve(service_id=4, schema_name="appdb") == expected_schema_id


def test_resolve_schema_id_returns_none_for_ambiguous_name():
    """Skip restores when multiple schemas share a name on one service."""
    lookup = SchemaIdLookup.from_schemas(
        [
            _schema(1, service_id=4, name="appdb"),
            _schema(2, service_id=4, name="appdb"),
        ]
    )

    assert lookup.resolve(service_id=4, schema_name="appdb") is None


@pytest.mark.asyncio
async def test_collecting_a_service_leaves_the_legacy_backfill_unchanged(session):
    """Name the legacy form backfill's behaviour for a collected service id.

    ``load_service_id_lookup`` reads through the default ``ServiceManager``,
    whose ``retired_at IS NULL`` guard already hides a tombstone. The legacy
    form field is therefore unmatched from the moment the service is retired —
    the operator re-picks, which was already the outcome for any id the lookup
    missed — and hard-deleting the row later changes nothing. Collection
    introduces no new degradation here, which is why
    ``resolve_mysql_service``'s contract needed no amendment either.
    """
    node = await NodeManager.create(session, Node(address="10.0.0.7", name="db-node"))
    service = await ServiceManager.create(
        session,
        ServiceWriteFactory.build(type=ServiceTypeEnum.MYSQL, port=3306),
        node_id=node.id,
    )
    hints = {"service_type": ServiceTypeEnum.MYSQL, "host": "10.0.0.7", "port": 3306}

    active = await load_service_id_lookup(session)
    assert active.resolve(**hints, service_name=None) == service.id

    service.retired_at = utc_now()
    service.retirement_key = service.id
    session.add(service)
    await session.commit()
    retired = await load_service_id_lookup(session)

    assert await RetiredInclusiveServiceManager.collect(session, [service.id]) == 1
    collected = await load_service_id_lookup(session)

    assert retired.resolve(**hints, service_name=None) is None
    assert collected.resolve(**hints, service_name=None) is None
