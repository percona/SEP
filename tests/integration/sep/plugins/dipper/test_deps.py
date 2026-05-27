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

from unittest.mock import MagicMock

import pytest

from app.core.exceptions import HTTPBadRequestException
from app.sep.inventory import CreatedService
from app.sep.plugins.dipper.deps import (
    build_dipper_meta_from_args,
    resolve_executor_host_for_service,
)
from app.sep.snippets.config import SnippetSudoOption
from tests.factories import CreatedNodeFactory, CreatedServiceFactory


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
