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

"""Cover the three-phase task-payload decomposition in ``framework/spec.py``.

The envelope golden tests assert byte-uniformity with the canonical hand-written
envelopes in ``checksums/deps.py`` (run-command) and ``backup_pg/deps.py``
(run-python); the resolve tests exercise ref-marker resolution against a fake
inventory backend; the assemble step is a pure function of form + resolved
entities, so none of these need a real database.
"""

from typing import Annotated, Any, Literal
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel, Field

from app.core.exceptions import HTTPBadRequestException
from app.core.requests.remote_api import RemoteAPI
from app.inventory.constants import DEFAULT_MYSQL_PORT, DEFAULT_POSTGRESQL_PORT
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework.form_dsl import (
    AppFormModel,
    ArgFormat,
    HostRef,
    SchemaRef,
    ServiceRef,
    Ui,
)
from app.sep.apps.framework.spec import (
    assemble_envelope,
    build_command_args,
    build_run_python_task,
    RESERVED_FORM_KEY,
    resolve_refs,
    ResolvedEntities,
    RunCommandSpec,
    RunPythonSpec,
    stamp_form_input,
    validate_arg_formats,
)
from app.sep.connectivity import (
    CONNECTIVITY_META_HOST_KEY,
    CONNECTIVITY_META_PORT_KEY,
    CONNECTIVITY_META_SERVICE_TYPE_KEY,
)
from app.tasks.models import TaskBackendEnum, TaskWrite
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
            owner="CHECKSUMS",
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
        assert write.owner == "CHECKSUMS"
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
            owner="CHECKSUMS",
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
            owner="CHECKSUMS",
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
            owner="BACKUP_PG",
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
            owner="BACKUP_PG",
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
                owner="CHECKSUMS",
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
                owner="CHECKSUMS",
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
            owner="CHECKSUMS",
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
            owner="CHECKSUMS",
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


class _MultiHostForm(AppFormModel):
    """Carry a multi-value ``HostRef`` to exercise the single-executor-host guard."""

    task_name: Annotated[str, Ui(label="Name", section="main")] = ""
    hosts: Annotated[
        list[str], HostRef(multiple=True), Ui(label="Hosts", section="main")
    ]


class _IntHostForm(AppFormModel):
    """Carry an ``int | str`` HostRef to exercise executor-host str coercion."""

    host: Annotated[
        int | str | None, HostRef(allow_custom=True), Ui(label="Host", section="main")
    ] = None


class _TwoServiceForm(AppFormModel):
    """Carry a marked source and an unmarked destination ``ServiceRef``.

    The destination is declared *after* the source so the old last-wins
    selection would pick it; the ``check_connectivity`` marker must instead keep
    the source as ``resolved.service``.
    """

    task_name: Annotated[str, Ui(label="Name", section="main")] = ""
    source_id: Annotated[
        int | None,
        ServiceRef(service_types=(ServiceTypeEnum.MYSQL,), check_connectivity=True),
        Ui(label="Source", section="main"),
    ] = None
    dest_id: Annotated[
        int | None,
        ServiceRef(service_types=(ServiceTypeEnum.MYSQL,)),
        Ui(label="Dest", section="main"),
    ] = None


class _SoleUnmarkedServiceForm(AppFormModel):
    """Carry a single unmarked ``ServiceRef`` to exercise the sole-ref fallback."""

    task_name: Annotated[str, Ui(label="Name", section="main")] = ""
    service_id: Annotated[
        int | None,
        ServiceRef(service_types=(ServiceTypeEnum.MYSQL,)),
        Ui(label="Service", section="main"),
    ] = None


class _SourceByTable(BaseModel):
    """Carry a discriminated-union branch nesting a free-solo ``SchemaRef``."""

    mode: Literal["table"] = "table"
    src_schema: Annotated[
        int | str | None,
        SchemaRef(allow_custom=True),
        Ui(label="Schema", section="main", depends_on="service_id"),
    ] = None


class _SourceByQuery(BaseModel):
    """Carry a ref-less discriminated-union branch (the inactive-branch case)."""

    mode: Literal["query"] = "query"
    query: Annotated[str, Ui(label="Query", section="main")] = ""


class _NestedRefForm(AppFormModel):
    """Carry a marked top-level service plus a one-of source nesting a ref."""

    task_name: Annotated[str, Ui(label="Name", section="main")] = ""
    service_id: Annotated[
        int | None,
        ServiceRef(service_types=(ServiceTypeEnum.MYSQL,), check_connectivity=True),
        Ui(label="Service", section="main"),
    ] = None
    source: Annotated[
        _SourceByTable | _SourceByQuery,
        Field(discriminator="mode"),
        Ui(label="Source", section="main"),
    ] = _SourceByTable()


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
    async def test_host_ref_value_coerced_to_str(self) -> None:
        """Coerce a non-``str`` ``HostRef`` value to ``str`` for ``executor_host``."""
        inventory = _fake_inventory({})

        resolved = await resolve_refs(_IntHostForm(host=8080), inventory)

        assert resolved.executor_host == "8080"
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
    async def test_multi_host_ref_raises(self) -> None:
        """Reject a multi-value ``HostRef`` selection that has no single executor host."""
        inventory = _fake_inventory({})

        with pytest.raises(ValueError, match="multi-value HostRef"):
            await resolve_refs(_MultiHostForm(hosts=["h1", "h2"]), inventory)

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

    @pytest.mark.asyncio
    async def test_check_connectivity_service_is_primary(self) -> None:
        """Select the ``check_connectivity`` service as primary, not the last ref."""
        source = _service(
            address="src-host",
            service_type=ServiceTypeEnum.MYSQL,
            name="source",
            port=3306,
        )
        dest = _service(
            address="dst-host",
            service_type=ServiceTypeEnum.MYSQL,
            name="dest",
            port=3306,
        )
        inventory = _fake_inventory(
            {
                "/services/1": source.model_dump(mode="json"),
                "/services/2": dest.model_dump(mode="json"),
            }
        )

        resolved = await resolve_refs(
            _TwoServiceForm(source_id=1, dest_id=2), inventory
        )

        assert resolved.service is not None
        assert resolved.service.name == "source"
        assert resolved.entities["source_id"].name == "source"
        assert resolved.entities["dest_id"].name == "dest"

    @pytest.mark.asyncio
    async def test_sole_service_ref_is_primary_when_none_marked(self) -> None:
        """Select the sole ``ServiceRef`` as primary when none is marked."""
        service = _service(
            address="h", service_type=ServiceTypeEnum.MYSQL, name="svc", port=3306
        )
        inventory = _fake_inventory({"/services/1": service.model_dump(mode="json")})

        resolved = await resolve_refs(_SoleUnmarkedServiceForm(service_id=1), inventory)

        assert resolved.service is not None
        assert resolved.service.name == "svc"

    @pytest.mark.asyncio
    async def test_resolves_active_branch_nested_ref(self) -> None:
        """Resolve a ref nested in the active one-of branch, keyed by dotted name."""
        service = _service(
            address="h", service_type=ServiceTypeEnum.MYSQL, name="svc", port=3306
        )
        schema = CreatedSchemaFactory.build(name="public")
        inventory = _fake_inventory(
            {
                "/services/1": service.model_dump(mode="json"),
                "/schemas/5": schema.model_dump(mode="json"),
            }
        )

        resolved = await resolve_refs(
            _NestedRefForm(service_id=1, source=_SourceByTable(src_schema=5)), inventory
        )

        assert resolved.entities["source.src_schema"].name == "public"
        assert resolved.service.name == "svc"

    @pytest.mark.asyncio
    async def test_nested_branch_custom_value_resolves_to_none(self) -> None:
        """Resolve a free-typed nested ref to ``None`` (manual fallback)."""
        service = _service(
            address="h", service_type=ServiceTypeEnum.MYSQL, name="svc", port=3306
        )
        inventory = _fake_inventory({"/services/1": service.model_dump(mode="json")})

        resolved = await resolve_refs(
            _NestedRefForm(service_id=1, source=_SourceByTable(src_schema="custom")),
            inventory,
        )

        assert resolved.entities["source.src_schema"] is None

    @pytest.mark.asyncio
    async def test_inactive_branch_refs_not_resolved(self) -> None:
        """Skip refs declared on a one-of branch that is not the active one."""
        service = _service(
            address="h", service_type=ServiceTypeEnum.MYSQL, name="svc", port=3306
        )
        inventory = _fake_inventory({"/services/1": service.model_dump(mode="json")})

        resolved = await resolve_refs(
            _NestedRefForm(service_id=1, source=_SourceByQuery(query="SELECT 1")),
            inventory,
        )

        assert "source.src_schema" not in resolved.entities


class TestAssembleEnvelopeAlertDetailBuilder:
    """Cover the optional ``alert_detail_builder`` stamping on the envelope."""

    def test_alert_detail_builder_stamped_when_set(self) -> None:
        """Assert the supplied ``alert_detail_builder`` is stamped onto the ``TaskWrite``."""
        service = _service(
            address="db-host",
            service_type=ServiceTypeEnum.MYSQL,
            name="svc-1",
            port=3306,
        )
        spec = RunPythonSpec(config="", requirements="", payload="file:///p")

        write = assemble_envelope(
            spec,
            ResolvedEntities(service=service, entities={}),
            name="task-1",
            owner="ARCHIVER",
            alert_detail_builder="pkg.mod:builder",
        )

        assert write.alert_detail_builder == "pkg.mod:builder"

    def test_alert_detail_builder_none_by_default(self) -> None:
        """Assert ``alert_detail_builder`` defaults to ``None`` when not supplied."""
        service = _service(
            address="db-host",
            service_type=ServiceTypeEnum.MYSQL,
            name="svc-1",
            port=3306,
        )
        spec = RunPythonSpec(config="", requirements="", payload="file:///p")

        write = assemble_envelope(
            spec,
            ResolvedEntities(service=service, entities={}),
            name="task-1",
            owner="ARCHIVER",
        )

        assert write.alert_detail_builder is None


class _ArgForm(AppFormModel):
    """Carry value-arg, flag-arg, and unmapped fields for build_command_args tests."""

    task_name: Annotated[str, Ui(label="Name", section="main")] = ""
    databases: Annotated[
        str, ArgFormat("--databases=${value}"), Ui(label="DB", section="main")
    ] = ""
    set_vars: Annotated[
        str, ArgFormat("--set-vars=${value}"), Ui(label="Vars", section="main")
    ] = ""
    binary_index: Annotated[
        bool, ArgFormat("--binary-index"), Ui(label="Binary", section="main")
    ] = False
    explain_arg: Annotated[
        bool, ArgFormat("--explain"), Ui(label="Explain", section="main")
    ] = False


class TestBuildCommandArgs:
    """Cover the declarative ``ArgFormat`` assembler in ``build_command_args``."""

    def test_value_args_precede_flag_args(self) -> None:
        """Emit all value args (field order) before all flag args (field order)."""
        args = build_command_args(
            _ArgForm(
                databases="db1",
                set_vars="v=1",
                binary_index=True,
                explain_arg=True,
            )
        )

        assert args == [
            "--databases=db1",
            "--set-vars=v=1",
            "--binary-index",
            "--explain",
        ]

    def test_empty_value_arg_is_skipped(self) -> None:
        """Skip a value arg whose field value is an empty string."""
        args = build_command_args(_ArgForm(databases="", set_vars="v=1"))

        assert args == ["--set-vars=v=1"]

    def test_flag_emitted_only_when_true(self) -> None:
        """Emit a flag arg only when its boolean field is ``True``."""
        args = build_command_args(_ArgForm(binary_index=False, explain_arg=True))

        assert args == ["--explain"]

    def test_spaced_value_is_a_single_quoted_round_trip_token(self) -> None:
        """Keep a whitespace-bearing value as one token through the quote round-trip."""
        args = build_command_args(_ArgForm(databases="reporting db"))

        assert args == ["--databases=reporting db"]

    def test_field_without_arg_format_is_ignored(self) -> None:
        """Ignore a field that declares no ``ArgFormat`` marker."""
        args = build_command_args(_ArgForm(task_name="my-task"))

        assert args == []


class _TypoPlaceholderForm(AppFormModel):
    """Carry a value-arg template whose placeholder is misspelled."""

    task_name: Annotated[str, Ui(label="Name", section="main")] = ""
    databases: Annotated[
        str, ArgFormat("--databases=${vale}"), Ui(label="DB", section="main")
    ] = ""


class _FlagOnNonBoolForm(AppFormModel):
    """Carry a no-placeholder (flag) template on a non-bool field."""

    task_name: Annotated[str, Ui(label="Name", section="main")] = ""
    explain_arg: Annotated[
        str, ArgFormat("--explain"), Ui(label="Explain", section="main")
    ] = ""


class _NonTerminalValueForm(AppFormModel):
    """Carry a value template whose ``${value}`` is not in the terminal position."""

    task_name: Annotated[str, Ui(label="Name", section="main")] = ""
    databases: Annotated[
        str, ArgFormat("--databases=${value}s"), Ui(label="DB", section="main")
    ] = ""


class TestValidateArgFormats:
    """Cover the construction-time ``ArgFormat`` validation in ``validate_arg_formats``."""

    def test_well_formed_markers_pass(self) -> None:
        """Accept exact ``${value}`` value templates and flag templates on bool fields."""
        validate_arg_formats(_ArgForm)

    def test_unsupported_placeholder_raises(self) -> None:
        """Reject a value template whose placeholder is not ``value`` (a typo footgun)."""
        with pytest.raises(ValueError, match="unsupported placeholder"):
            validate_arg_formats(_TypoPlaceholderForm)

    def test_flag_template_on_non_bool_field_raises(self) -> None:
        """Reject a no-placeholder template on a field that is not ``bool``."""
        with pytest.raises(ValueError, match="bool field"):
            validate_arg_formats(_FlagOnNonBoolForm)

    def test_non_terminal_value_placeholder_raises(self) -> None:
        """Reject a value template whose ``${value}`` is not terminal (reverse-parse footgun)."""
        with pytest.raises(ValueError, match="terminal"):
            validate_arg_formats(_NonTerminalValueForm)


class _DefaultArgForm(AppFormModel):
    """Carry templateless ``ArgFormat`` markers that derive from field name and type."""

    task_name: Annotated[str, Ui(label="Name", section="main")] = ""
    max_load: Annotated[str, ArgFormat(), Ui(label="Load", section="main")] = ""
    binary_index: Annotated[bool, ArgFormat(), Ui(label="Binary", section="main")] = (
        False
    )
    explain_arg: Annotated[
        bool, ArgFormat("--explain"), Ui(label="Explain", section="main")
    ] = False


class TestDerivedArgFormat:
    """Cover the templateless ``ArgFormat`` default derivation."""

    def test_value_arg_derives_kebab_name(self) -> None:
        """Derive ``--<kebab-name>=${value}`` for a non-bool field with no template."""
        args = build_command_args(_DefaultArgForm(max_load="Threads_running=50"))

        assert args == ["--max-load=Threads_running=50"]

    def test_flag_derives_kebab_name(self) -> None:
        """Derive ``--<kebab-name>`` for a bool field with no template."""
        args = build_command_args(_DefaultArgForm(binary_index=True))

        assert args == ["--binary-index"]

    def test_explicit_template_overrides_derived_default(self) -> None:
        """Keep an explicit template when the CLI spelling diverges from the name."""
        args = build_command_args(_DefaultArgForm(explain_arg=True))

        assert args == ["--explain"]

    def test_derived_value_arg_skipped_when_empty(self) -> None:
        """Skip a derived value arg whose field value is empty, like an explicit one."""
        args = build_command_args(_DefaultArgForm())

        assert args == []

    def test_validate_accepts_templateless_markers(self) -> None:
        """Accept templateless markers on both bool and non-bool fields."""
        validate_arg_formats(_DefaultArgForm)


class _StampForm(AppFormModel):
    """Declare the minimal create form the reserved-key stamp tests submit."""

    task_name: Annotated[str, Ui(label="Name", section="main")] = ""


class TestStampFormInput:
    """Cover the reserved-key stamp written onto the task envelope ``data``."""

    @staticmethod
    def _envelope() -> TaskWrite:
        """Build a run-command envelope to stamp the create form onto."""
        service = _service(
            address="db-host",
            service_type=ServiceTypeEnum.MYSQL,
            name="svc-1",
            port=3306,
        )
        return assemble_envelope(
            RunCommandSpec(command="cmd", args=""),
            ResolvedEntities(service=service, entities={}),
            name="task-1",
            owner="CHECKSUMS",
        )

    def test_stamps_dumped_form_under_reserved_key(self) -> None:
        """Write the JSON-mode form dump onto the reserved ``data`` key."""
        write = self._envelope()
        form = _StampForm(task_name="task-1")

        stamp_form_input(write, form)

        assert write.data[RESERVED_FORM_KEY] == form.model_dump(mode="json")

    def test_raises_when_reserved_key_already_present(self) -> None:
        """Fail fast rather than silently overwrite a key a spec builder set."""
        write = self._envelope()
        write.data[RESERVED_FORM_KEY] = {"prior": True}

        with pytest.raises(ValueError, match="reserved key"):
            stamp_form_input(write, _StampForm(task_name="task-1"))


class TestBuildRunPythonTask:
    """Cover the connectivity-optional ``build_run_python_task`` builder."""

    @staticmethod
    def _write(
        *,
        service_name: str | None = None,
        extra_data: dict[str, Any] | None = None,
        alert_on_fail: bool = False,
    ) -> TaskWrite:
        """Build a run-python ``TaskWrite`` with fixed defaults for the required args."""
        return build_run_python_task(
            name="task-1",
            owner="BACKUP_MONGO",
            target="mongo-host",
            config="alias: stanza\n",
            requirements="packaging\nPyYAML",
            payload="file:///plugin/payload",
            service_name=service_name,
            extra_data=extra_data,
            alert_on_fail=alert_on_fail,
        )

    def test_data_dict_shape(self) -> None:
        """Emit the canonical run-python data shape with no connectivity meta."""
        write = self._write()

        assert write.data == {
            "task": "run-python",
            "meta": {
                "config": "alias: stanza\n",
                "target": "mongo-host",
                "requirements": "packaging\nPyYAML",
            },
            "payload": "file:///plugin/payload",
        }

    def test_meta_key_order(self) -> None:
        """Pin the canonical meta key order with ``_service_name`` last."""
        write = self._write(service_name="mongo-svc")

        assert list(write.data["meta"].keys()) == [
            "config",
            "target",
            "requirements",
            "_service_name",
        ]

    def test_service_name_omitted_when_none(self) -> None:
        """Omit ``_service_name`` from the meta when ``service_name`` is ``None``."""
        write = self._write(service_name=None)

        assert "_service_name" not in write.data["meta"]

    def test_extra_data_merged_at_top_level(self) -> None:
        """Merge ``extra_data`` at the ``data`` top level after ``payload``."""
        write = self._write(extra_data={"backup_type": "pbm-config"})

        assert write.data["backup_type"] == "pbm-config"
        assert list(write.data.keys()) == ["task", "meta", "payload", "backup_type"]

    def test_defaults(self) -> None:
        """Emit the PROXY backend with no failure alert or detail builder by default."""
        write = self._write()

        assert write.backend == TaskBackendEnum.PROXY
        assert write.alert_on_fail is False
        assert write.alert_detail_builder is None

    def test_alert_on_fail_propagates(self) -> None:
        """Propagate ``alert_on_fail=True`` onto the ``TaskWrite``."""
        write = self._write(alert_on_fail=True)

        assert write.alert_on_fail is True

    @pytest.mark.parametrize(
        "reserved_key", ["task", "meta", "payload", RESERVED_FORM_KEY]
    )
    def test_extra_data_reserved_key_collision_raises(self, reserved_key: str) -> None:
        """Reject an ``extra_data`` key that collides with a reserved envelope key."""
        with pytest.raises(ValueError, match="reserved"):
            self._write(extra_data={reserved_key: "x"})
