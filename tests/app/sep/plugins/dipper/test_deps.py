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
from app.sep.plugins.dipper.deps import build_dipper_meta_from_args
from app.sep.snippets.config import SnippetSudoOption


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
