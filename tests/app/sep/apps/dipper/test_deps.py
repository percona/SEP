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

"""Tests for ``build_dipper_meta_from_args`` and related helpers in dipper deps."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.sep.deps as sep_deps
from app.core.exceptions import HTTPBadRequestException
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.dipper import deps as dipper_deps
from app.sep.apps.dipper.constants import CollectorTypeEnum
from app.sep.apps.dipper.deps import (
    build_dipper_meta_from_args,
    fetch_pmm_node_service_names,
    get_dipper_execution_meta,
    get_dipper_script_filename,
    has_pmm_script,
    resolve_executor_host_for_service,
)
from app.sep.apps.dipper.models import DipperScript
from app.sep.apps.field_names import RESERVED_EXECUTION_FIELD_NAMES
from app.sep.clients.pmm import PMMRemoteAPI
from app.sep.inventory import CreatedService
from app.sep.snippets.config import snippets_settings, SnippetSudoOption
from tests.app.factories import CreatedNodeFactory, CreatedServiceFactory


class TestValkeyScriptMapping:
    """Valkey resolves to both collector scripts and reports a PMM script."""

    def test_environment_script_resolves(self):
        """Valkey + environment resolves to the Valkey env collector."""
        assert (
            get_dipper_script_filename(
                ServiceTypeEnum.VALKEY, CollectorTypeEnum.ENVIRONMENT
            )
            == "pcs-collect-environment-valkey.sh"
        )

    def test_pmm_script_resolves(self):
        """Valkey + PMM resolves to the Valkey PMM collector."""
        assert (
            get_dipper_script_filename(ServiceTypeEnum.VALKEY, CollectorTypeEnum.PMM)
            == "pcs-collect-pmm-valkey.py"
        )

    def test_has_pmm_script_is_true(self):
        """Valkey is the second service type to carry a PMM collector."""
        assert has_pmm_script(ServiceTypeEnum.VALKEY) is True


def _make_script(
    *, execution_interpreter: str | None, sudo: SnippetSudoOption
) -> MagicMock:
    script = MagicMock()
    script.execution_interpreter = execution_interpreter
    script.sudo = sudo
    script.filename = "pcs-collect-environment-mysql.sh"
    script.md5_digest = "deadbeef"
    script.requirements = []
    return script


def _make_service(service_id: int = 1) -> MagicMock:
    service = MagicMock()
    service.id = service_id
    return service


def _make_args(*, executor_host: str = "host1", sudo: bool | None = None) -> MagicMock:
    args = MagicMock()
    args.sudo_field = "sudo"
    args.executor_host = executor_host
    # sudo attribute used by getattr(execution_args, execution_args.sudo_field, ...)
    if sudo is not None:
        args.sudo = sudo
    else:
        del args.sudo  # so getattr falls back to the default
    args.to_args_string.return_value = ""
    return args


class TestBuildDipperMetaFromArgs:
    """Tests for ``build_dipper_meta_from_args``."""

    def test_raises_bad_request_when_interpreter_is_none_and_sudo_always(self):
        """HTTPBadRequestException fires before sudo prefix is applied to None."""
        script = _make_script(execution_interpreter=None, sudo=SnippetSudoOption.ALWAYS)
        service = _make_service()
        args = _make_args(executor_host="host1")

        with pytest.raises(HTTPBadRequestException):
            build_dipper_meta_from_args(service, script, "src://test", args)

    def test_raises_bad_request_when_interpreter_is_none_and_sudo_explicit(self):
        """HTTPBadRequestException fires when interpreter is None and sudo=True in args."""
        script = _make_script(
            execution_interpreter=None, sudo=SnippetSudoOption.OPTIONAL
        )
        service = _make_service()
        args = _make_args(executor_host="host1", sudo=True)

        with pytest.raises(HTTPBadRequestException):
            build_dipper_meta_from_args(service, script, "src://test", args)

    def test_raises_bad_request_when_interpreter_is_none_and_no_sudo(self):
        """HTTPBadRequestException fires even when sudo is not requested."""
        script = _make_script(execution_interpreter=None, sudo=SnippetSudoOption.NEVER)
        service = _make_service()
        args = _make_args(executor_host="host1")

        with pytest.raises(HTTPBadRequestException):
            build_dipper_meta_from_args(service, script, "src://test", args)

    def test_interpreter_does_not_become_sudo_none_string(self):
        """Returned interpreter is never the literal string 'sudo None'."""
        script = _make_script(execution_interpreter=None, sudo=SnippetSudoOption.ALWAYS)
        service = _make_service()
        args = _make_args(executor_host="host1")

        try:
            meta = build_dipper_meta_from_args(service, script, "src://test", args)
            assert meta.interpreter != "sudo None"
        except HTTPBadRequestException:
            pass  # correct — guard fired before producing the bad string


def _script_with_parameter(name: str) -> DipperScript:
    """Return a DB-free Dipper script declaring a single parameter called ``name``.

    ``sudo: never`` keeps the script's own configuration out of the way, so a
    failure here can only come from the parameter name.
    """
    return DipperScript(
        filename="collect.sh",
        size=1,
        md5_digest="a" * 32,
        meta={
            "title": "Collect",
            "sudo": SnippetSudoOption.NEVER.value,
            "parameters": [{"name": name, "type": "str"}],
        },
    )


class TestInvalidFrontmatterBlocksExecution:
    """Cover the execution block for a script carrying invalid frontmatter."""

    @pytest.mark.parametrize("reserved_name", sorted(RESERVED_EXECUTION_FIELD_NAMES))
    def test_reserved_parameter_name_blocks_the_shared_meta_builder(
        self, reserved_name
    ):
        """Refuse to build execution meta for a script with a reserved parameter name.

        Dropping the parameter keeps the form renderable, but the script is still
        misconfigured -- the operator would silently run it without the argument
        its author declared. Both Dipper execution flows assemble their meta here,
        so guarding this one seam blocks both.
        """
        script = _script_with_parameter(reserved_name)
        assert script.execution_interpreter is not None
        assert script.can_execute is False

        with pytest.raises(HTTPBadRequestException):
            build_dipper_meta_from_args(
                _make_service(), script, "src://test", _make_args()
            )

    def test_reserved_parameter_name_blocks_the_legacy_form_flow(self):
        """Refuse the legacy form dependency for a script with a reserved name."""
        with pytest.raises(HTTPBadRequestException):
            get_dipper_execution_meta(
                _make_service(),
                _script_with_parameter("sudo"),
                "src://test",
                _make_args(),
            )

    def test_execution_proceeds_when_invalid_parameters_are_ignored(self, monkeypatch):
        """Honour the operator's opt-out rather than blocking unconditionally."""
        monkeypatch.setattr(
            snippets_settings.META, "IGNORE_INVALID_PARAMETERS", True, raising=False
        )

        meta = build_dipper_meta_from_args(
            _make_service(), _script_with_parameter("sudo"), "src://test", _make_args()
        )

        assert meta.target == "host1"


def _make_service_with_node(
    *,
    service_name: str = "svc",
    node_name: str | None = "node",
    node_address: str | None = "10.0.0.1",
) -> CreatedService:
    if node_name is None and node_address is None:
        node = None
    else:
        node = CreatedNodeFactory.build(name=node_name, address=node_address)
    return CreatedServiceFactory.build(name=service_name, node=node)


class TestResolveExecutorHostForService:
    """Tests for ``resolve_executor_host_for_service``."""

    def test_returns_node_name_when_it_matches_executor_hosts(self) -> None:
        """Return ``service.node.name`` when it matches a Nomad node name."""
        service = _make_service_with_node(
            node_name="mvc-lab-db3", node_address="10.0.0.7"
        )
        executor_hosts = {"mvc-lab-db3": "10.0.0.7"}
        assert (
            resolve_executor_host_for_service(executor_hosts, service) == "mvc-lab-db3"
        )

    def test_returns_executor_name_when_node_address_matches(self) -> None:
        """Resolve via address when inventory name differs from Nomad node name.

        Inventory records ``mvc-lab-maria1`` while the Nomad agent registers
        ``mvc-lab-db3`` for the same host; the helper must return the
        Nomad-keyed name expected by Dipper.
        """
        service = _make_service_with_node(
            node_name="mvc-lab-maria1", node_address="10.0.0.7"
        )
        executor_hosts = {"mvc-lab-db3": "10.0.0.7"}
        assert (
            resolve_executor_host_for_service(executor_hosts, service) == "mvc-lab-db3"
        )

    def test_prefers_node_name_over_address_lookup(self) -> None:
        """Take ``service.node.name`` over an address lookup that would resolve elsewhere."""
        service = _make_service_with_node(
            node_name="mvc-lab-db3", node_address="10.0.0.7"
        )
        executor_hosts = {"mvc-lab-db3": "10.0.0.9", "mvc-lab-db5": "10.0.0.7"}
        assert (
            resolve_executor_host_for_service(executor_hosts, service) == "mvc-lab-db3"
        )

    def test_returns_service_name_when_node_is_none(self) -> None:
        """Fall back to ``service.name`` when ``service.node`` is ``None``."""
        service = _make_service_with_node(
            service_name="mvc-lab-db3", node_name=None, node_address=None
        )
        executor_hosts = {"mvc-lab-db3": "10.0.0.7"}
        assert (
            resolve_executor_host_for_service(executor_hosts, service) == "mvc-lab-db3"
        )

    def test_returns_none_when_nothing_matches(self) -> None:
        """Return ``None`` when neither name nor address resolves."""
        service = _make_service_with_node(
            service_name="mvc-lab-other",
            node_name="mvc-lab-maria1",
            node_address="10.0.0.99",
        )
        executor_hosts = {"mvc-lab-db3": "10.0.0.7"}
        assert resolve_executor_host_for_service(executor_hosts, service) is None


def _named(*names: str) -> list[SimpleNamespace]:
    """Build a list of objects exposing a ``name`` attribute."""
    return [SimpleNamespace(name=name) for name in names]


class TestFetchPmmNodeServiceNames:
    """Tests for ``fetch_pmm_node_service_names``."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_client_is_none(self):
        """Return empty lists when PMM is not configured (client is ``None``)."""
        assert await fetch_pmm_node_service_names(None) == ([], [])

    @pytest.mark.asyncio
    async def test_swallows_client_errors_into_empty_lists(self):
        """Return empty lists when the PMM client raises (unreachable PMM)."""
        client = AsyncMock(spec=PMMRemoteAPI)
        client.get_nodes.side_effect = RuntimeError("connection refused")
        assert await fetch_pmm_node_service_names(client) == ([], [])

    @pytest.mark.asyncio
    async def test_extracts_node_and_service_names(self):
        """Return node and service names on the happy path."""
        client = AsyncMock(spec=PMMRemoteAPI)
        client.get_nodes.return_value = _named("node-a", "node-b")
        client.get_services.return_value = _named("svc-1", "svc-2")
        nodes, services = await fetch_pmm_node_service_names(client)
        assert nodes == ["node-a", "node-b"]
        assert services == ["svc-1", "svc-2"]

    @pytest.mark.asyncio
    async def test_filters_blank_and_dedupes_preserving_order(self):
        """Drop empty/whitespace names and dedupe while preserving first-seen order."""
        client = AsyncMock(spec=PMMRemoteAPI)
        client.get_nodes.return_value = _named("node-a", "", "  ", "node-a", "node-b")
        client.get_services.return_value = _named("svc-1", "svc-1", "")
        nodes, services = await fetch_pmm_node_service_names(client)
        assert nodes == ["node-a", "node-b"]
        assert services == ["svc-1"]


class TestPmmDepReExports:
    """Assert the dipper PMM deps are re-exports of the ``app.sep.deps`` originals."""

    @pytest.mark.parametrize("name", ["get_pmm_api", "PMMAPIDep"])
    def test_symbol_is_same_object_as_sep_deps(self, name):
        """Assert each re-exported symbol is identical to its ``app.sep.deps`` original.

        Identity is load-bearing: ``dependency_overrides`` and ``mocker.patch`` bind by
        object identity, so a local re-definition would silently break production overrides
        while leaving the suite green.

        :param name: The re-exported symbol name to compare.
        """
        assert getattr(dipper_deps, name) is getattr(sep_deps, name)
