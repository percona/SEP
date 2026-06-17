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

"""Cover the three-phase task-payload decomposition in ``framework/payload.py``.

The envelope golden tests assert byte-uniformity with the canonical hand-written
envelopes in ``checksums/deps.py`` (run-command) and ``backup_pg/deps.py``
(run-python); the resolve tests exercise ref-marker resolution against a fake
inventory backend; the assemble step is a pure function of form + resolved
entities, so none of these need a real database.
"""

from typing import Annotated
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import HTTPBadRequestException
from app.core.requests.remote_api import RemoteAPI
from app.inventory.constants import DEFAULT_MYSQL_PORT, DEFAULT_POSTGRESQL_PORT
from app.inventory.models import ServiceTypeEnum
from app.sep.connectivity import (
    CONNECTIVITY_META_HOST_KEY,
    CONNECTIVITY_META_PORT_KEY,
    CONNECTIVITY_META_SERVICE_TYPE_KEY,
)
from app.sep.plugins.framework.form_dsl import (
    AppFormModel,
    HostRef,
    SchemaRef,
    ServiceRef,
    Ui,
)
from app.sep.plugins.framework.payload import (
    assemble_envelope,
    resolve_refs,
    ResolvedEntities,
    RunCommandSpec,
    RunPythonSpec,
)
from app.tasks.models import TaskBackendEnum, TaskOwner
from tests.app.factories import (
    CreatedNodeFactory,
    CreatedSchemaFactory,
    CreatedServiceFactory,
)


def _service(*, address: str, service_type: ServiceTypeEnum, name: str, port):
    """Build a ``CreatedService`` on a node whose address is ``address``."""
    return CreatedServiceFactory.build(
        node=CreatedNodeFactory.build(address=address),
        type=service_type,
        name=name,
        port=port,
    )


def _fake_inventory(routes: dict[str, dict]) -> AsyncMock:
    """Return an ``AsyncMock(spec=RemoteAPI)`` whose ``get`` routes by path."""
    api = AsyncMock(spec=RemoteAPI)

    async def _get(path: str, params: dict | None = None) -> dict:
        return routes[path]

    api.get.side_effect = _get
    return api


class TestAssembleEnvelopeRunCommand:
    """Assert the run-command envelope is byte-uniform with ``checksums/deps.py``."""

    def test_data_dict_matches_canonical_envelope(self) -> None:
        """Build the run-command ``data`` dict expected by the Tasks API."""
        service = _service(
            address="db-host",
            service_type=ServiceTypeEnum.MYSQL,
            name="svc-1",
            port=3306,
        )
        spec = RunCommandSpec(
            command="pt-table-checksum",
            args="--recursion-method=hosts",
            extra_meta={"_service_host": "db-host", "_service_port": 3306},
        )

        write = assemble_envelope(
            spec,
            ResolvedEntities(service=service, entities={}),
            name="task-1",
            owner=TaskOwner.CHECKSUMS,
            alert_on_fail=True,
        )

        assert write.data == {
            "task": "run-command",
            "meta": {
                "command": "pt-table-checksum",
                "args": "--recursion-method=hosts",
                "target": "db-host",
                "_service_name": "svc-1",
                "_service_host": "db-host",
                "_service_port": 3306,
                CONNECTIVITY_META_HOST_KEY: "db-host",
                CONNECTIVITY_META_PORT_KEY: 3306,
                CONNECTIVITY_META_SERVICE_TYPE_KEY: "mysql",
            },
        }
        assert write.name == "task-1"
        assert write.owner == TaskOwner.CHECKSUMS
        assert write.backend == TaskBackendEnum.PROXY
        assert write.alert_on_fail is True

    def test_meta_key_order_matches_canonical_envelope(self) -> None:
        """Pin the meta key order to the canonical run-command sequence."""
        service = _service(
            address="db-host",
            service_type=ServiceTypeEnum.MYSQL,
            name="svc-1",
            port=3306,
        )
        spec = RunCommandSpec(
            command="pt-table-checksum",
            args="",
            extra_meta={"_service_host": "db-host", "_service_port": 3306},
        )

        write = assemble_envelope(
            spec,
            ResolvedEntities(service=service, entities={}),
            name="task-1",
            owner=TaskOwner.CHECKSUMS,
        )

        assert list(write.data["meta"].keys()) == [
            "command",
            "args",
            "target",
            "_service_name",
            "_service_host",
            "_service_port",
            CONNECTIVITY_META_HOST_KEY,
            CONNECTIVITY_META_PORT_KEY,
            CONNECTIVITY_META_SERVICE_TYPE_KEY,
        ]

    def test_port_default_fallback_when_service_port_none(self) -> None:
        """Fall back to ``DEFAULT_MYSQL_PORT`` when the service has no port."""
        service = _service(
            address="db-host",
            service_type=ServiceTypeEnum.MYSQL,
            name="svc-1",
            port=None,
        )
        spec = RunCommandSpec(command="cmd", args="")

        write = assemble_envelope(
            spec,
            ResolvedEntities(service=service, entities={}),
            name="task-1",
            owner=TaskOwner.CHECKSUMS,
        )

        assert write.data["meta"][CONNECTIVITY_META_PORT_KEY] == DEFAULT_MYSQL_PORT


class TestAssembleEnvelopeRunPython:
    """Assert the run-python envelope is byte-uniform with ``backup_pg/deps.py``."""

    def test_data_dict_matches_canonical_envelope(self) -> None:
        """Build the run-python ``data`` dict expected by the Tasks API."""
        service = _service(
            address="pg-host",
            service_type=ServiceTypeEnum.POSTGRESQL,
            name="pg-1",
            port=5432,
        )
        spec = RunPythonSpec(
            config="alias: stanza\n",
            requirements="packaging\nPyYAML",
            payload="file:///plugin/payload",
        )

        write = assemble_envelope(
            spec,
            ResolvedEntities(service=service, entities={}),
            name="backup-1",
            owner=TaskOwner.BACKUP_PG,
        )

        assert write.data == {
            "task": "run-python",
            "meta": {
                "config": "alias: stanza\n",
                "target": "pg-host",
                "requirements": "packaging\nPyYAML",
                "_service_name": "pg-1",
                CONNECTIVITY_META_HOST_KEY: "pg-host",
                CONNECTIVITY_META_PORT_KEY: 5432,
                CONNECTIVITY_META_SERVICE_TYPE_KEY: "postgresql",
            },
            "payload": "file:///plugin/payload",
        }

    def test_port_default_fallback_uses_postgresql_default(self) -> None:
        """Fall back to ``DEFAULT_POSTGRESQL_PORT`` when the service has no port."""
        service = _service(
            address="pg-host",
            service_type=ServiceTypeEnum.POSTGRESQL,
            name="pg-1",
            port=None,
        )
        spec = RunPythonSpec(config="", requirements="", payload="file:///p")

        write = assemble_envelope(
            spec,
            ResolvedEntities(service=service, entities={}),
            name="backup-1",
            owner=TaskOwner.BACKUP_PG,
        )

        assert write.data["meta"][CONNECTIVITY_META_PORT_KEY] == DEFAULT_POSTGRESQL_PORT


class TestAssembleEnvelopeGuards:
    """Cover the fail-fast guards on ``assemble_envelope``."""

    def test_missing_service_raises(self) -> None:
        """Raise when no service is resolved for the connectivity meta."""
        spec = RunCommandSpec(command="cmd", args="")

        with pytest.raises(ValueError, match="service"):
            assemble_envelope(
                spec,
                ResolvedEntities(service=None, entities={}),
                name="task-1",
                owner=TaskOwner.CHECKSUMS,
            )

    def test_unresolvable_port_raises(self) -> None:
        """Raise when the service has no port and no default for its type."""
        service = _service(
            address="mongo-host",
            service_type=ServiceTypeEnum.MONGODB,
            name="mongo-1",
            port=None,
        )
        spec = RunCommandSpec(command="cmd", args="")

        with pytest.raises(ValueError, match="connectivity port"):
            assemble_envelope(
                spec,
                ResolvedEntities(service=service, entities={}),
                name="task-1",
                owner=TaskOwner.CHECKSUMS,
            )


class TestAssembleEnvelopeExecutorHost:
    """Cover the executor-host / service-host split on the assembled envelope."""

    def test_executor_host_drives_meta_target(self) -> None:
        """Set ``meta.target`` to the executor host, keeping connectivity on the service."""
        service = _service(
            address="db-host",
            service_type=ServiceTypeEnum.MYSQL,
            name="svc-1",
            port=3306,
        )
        spec = RunCommandSpec(command="cmd", args="")

        write = assemble_envelope(
            spec,
            ResolvedEntities(service=service, entities={}, executor_host="exec-node"),
            name="task-1",
            owner=TaskOwner.CHECKSUMS,
        )

        assert write.data["meta"]["target"] == "exec-node"
        assert write.data["meta"][CONNECTIVITY_META_HOST_KEY] == "db-host"

    def test_no_executor_host_falls_back_to_service_address(self) -> None:
        """Fall back to the service address for ``meta.target`` when no host resolved."""
        service = _service(
            address="db-host",
            service_type=ServiceTypeEnum.MYSQL,
            name="svc-1",
            port=3306,
        )
        spec = RunCommandSpec(command="cmd", args="")

        write = assemble_envelope(
            spec,
            ResolvedEntities(service=service, entities={}),
            name="task-1",
            owner=TaskOwner.CHECKSUMS,
        )

        assert write.data["meta"]["target"] == "db-host"
        assert write.data["meta"][CONNECTIVITY_META_HOST_KEY] == "db-host"


class _ResolveForm(AppFormModel):
    """Carry one of each resolvable ref plus a manual host for resolve tests."""

    task_name: Annotated[str, Ui(label="Name", section="main")] = ""
    service_id: Annotated[
        int | None,
        ServiceRef(service_types=(ServiceTypeEnum.MYSQL,)),
        Ui(label="Service", section="main"),
    ] = None
    schema_id: Annotated[
        int | None,
        SchemaRef(),
        Ui(label="Schema", section="main", depends_on="service_id"),
    ] = None
    custom_service: Annotated[
        int | str | None,
        ServiceRef(service_types=(ServiceTypeEnum.MYSQL,), allow_custom=True),
        Ui(label="Custom", section="main"),
    ] = None
    host: Annotated[
        str | None, HostRef(allow_custom=True), Ui(label="Host", section="main")
    ] = None


class _MultiTypeForm(AppFormModel):
    """Carry a multi-type ``ServiceRef`` for the type-enforcement tests."""

    task_name: Annotated[str, Ui(label="Name", section="main")] = ""
    service_id: Annotated[
        int | None,
        ServiceRef(service_types=(ServiceTypeEnum.MYSQL, ServiceTypeEnum.MONGODB)),
        Ui(label="Service", section="main"),
    ] = None


class _TwoHostForm(AppFormModel):
    """Carry two ``HostRef`` fields to exercise the single-executor-host guard."""

    task_name: Annotated[str, Ui(label="Name", section="main")] = ""
    host_a: Annotated[str | None, HostRef(), Ui(label="A", section="main")] = None
    host_b: Annotated[str | None, HostRef(), Ui(label="B", section="main")] = None


class TestResolveRefs:
    """Cover ref-marker resolution against a fake inventory backend."""

    @pytest.mark.asyncio
    async def test_resolves_each_inventory_ref(self) -> None:
        """Resolve the ``ServiceRef`` and ``SchemaRef`` fields by id."""
        service = _service(
            address="h", service_type=ServiceTypeEnum.MYSQL, name="svc", port=3306
        )
        schema = CreatedSchemaFactory.build(name="public")
        inventory = _fake_inventory(
            {
                "/services/1": service.model_dump(mode="json"),
                "/schemas/2": schema.model_dump(mode="json"),
            }
        )

        resolved = await resolve_refs(
            _ResolveForm(service_id=1, schema_id=2), inventory
        )

        assert resolved.service is not None
        assert resolved.service.name == "svc"
        assert resolved.entities["service_id"].name == "svc"
        assert resolved.entities["schema_id"].name == "public"

    @pytest.mark.asyncio
    async def test_empty_and_custom_refs_resolve_to_none(self) -> None:
        """Resolve empty and free-typed ref fields to ``None`` (manual fallback)."""
        inventory = _fake_inventory({})

        resolved = await resolve_refs(
            _ResolveForm(service_id=None, schema_id=None, custom_service="manual-name"),
            inventory,
        )

        assert resolved.service is None
        assert resolved.entities["service_id"] is None
        assert resolved.entities["custom_service"] is None
        inventory.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_host_ref_is_not_resolved(self) -> None:
        """Skip ``HostRef`` fields — the executor host is read from the form."""
        inventory = _fake_inventory({})

        resolved = await resolve_refs(_ResolveForm(host="some-host"), inventory)

        assert "host" not in resolved.entities

    @pytest.mark.asyncio
    async def test_host_ref_captured_as_executor_host(self) -> None:
        """Capture a ``HostRef`` field's free-typed value as the executor host."""
        inventory = _fake_inventory({})

        resolved = await resolve_refs(_ResolveForm(host="exec-node"), inventory)

        assert resolved.executor_host == "exec-node"
        inventory.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_host_ref_leaves_executor_host_none(self) -> None:
        """Leave ``executor_host`` as ``None`` when the model declares no ``HostRef``."""
        inventory = _fake_inventory({})

        resolved = await resolve_refs(_MultiTypeForm(service_id=None), inventory)

        assert resolved.executor_host is None

    @pytest.mark.asyncio
    async def test_multiple_host_refs_raise(self) -> None:
        """Reject a model declaring more than one ``HostRef`` field."""
        inventory = _fake_inventory({})

        with pytest.raises(ValueError, match="HostRef"):
            await resolve_refs(_TwoHostForm(host_a="a", host_b="b"), inventory)

    @pytest.mark.asyncio
    async def test_multi_type_service_in_tuple_resolves(self) -> None:
        """Accept a service whose type is within a multi-type ``ServiceRef``."""
        service = _service(
            address="h", service_type=ServiceTypeEnum.MONGODB, name="mongo", port=27017
        )
        inventory = _fake_inventory({"/services/1": service.model_dump(mode="json")})

        resolved = await resolve_refs(_MultiTypeForm(service_id=1), inventory)

        assert resolved.service is not None
        assert resolved.service.type is ServiceTypeEnum.MONGODB

    @pytest.mark.asyncio
    async def test_multi_type_service_out_of_tuple_raises(self) -> None:
        """Reject a service whose type is outside a multi-type ``ServiceRef``."""
        service = _service(
            address="h",
            service_type=ServiceTypeEnum.POSTGRESQL,
            name="pg",
            port=5432,
        )
        inventory = _fake_inventory({"/services/1": service.model_dump(mode="json")})

        with pytest.raises(HTTPBadRequestException):
            await resolve_refs(_MultiTypeForm(service_id=1), inventory)
