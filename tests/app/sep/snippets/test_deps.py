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

"""Tests for snippet plugin deps helpers."""

from unittest.mock import MagicMock

import pytest
from fastapi import status

import app.sep.snippets.deps as snippets_deps
from app.core.auth.exceptions import HTTPForbiddenException
from app.core.exceptions import HTTPBadRequestException
from app.sep.snippets.config import SnippetSudoOption
from app.sep.snippets.deps import (
    build_snippet_execution_meta,
    check_snippet_batch_existence,
    get_executable_snippet_for_api,
    get_snippet_execution_request_meta,
    SnippetBatchExistenceResult,
    validate_snippet_filename,
    validate_snippet_parameters,
)
from app.sep.snippets.models.snippet import (
    EXECUTOR_HOSTS_INPUT_NAME,
    Snippet,
)


class _AsyncForm:
    """Mimic the async context manager returned by ``Request.form()``."""

    def __init__(self, data: dict):
        self._data = data

    async def __aenter__(self) -> dict:
        return self._data

    async def __aexit__(self, *exc) -> bool:
        return False


def _gated_snippet() -> Snippet:
    """Return an unpersisted snippet with a ``start`` field hidden when ``list``."""
    snippet = Snippet(filename="gated.sh", size=20, md5_digest="a" * 32)
    snippet.meta = {
        **snippet.meta,
        "parameters": [
            {"name": "list", "type": "bool", "label": "List"},
            {
                "name": "start",
                "type": "str",
                "label": "Start",
                "visible_when_not": "list",
            },
        ],
    }
    return snippet


@pytest.mark.asyncio
async def test_get_validated_execution_args_rejects_gated_hidden_value(mocker):
    """The legacy form path flashes + redirects when a gated gate fires."""
    snippet = _gated_snippet()
    request = MagicMock()
    request.form.return_value = _AsyncForm(
        {EXECUTOR_HOSTS_INPUT_NAME: "host1", "list": "1", "start": "2020"}
    )
    mock_messages = mocker.patch.object(snippets_deps, "messages")
    mocker.patch.object(
        snippets_deps,
        "_get_snippet_redirect_exc",
        return_value=RuntimeError("redirect"),
    )

    with pytest.raises(RuntimeError, match="redirect"):
        await snippets_deps.get_validated_execution_args(request, snippet, referer=None)

    mock_messages.error.assert_called_once()


@pytest.mark.asyncio
async def test_get_validated_execution_args_rejects_missing_required_field(mocker):
    """The legacy form path flashes + redirects when a requires gate fires."""
    snippet = Snippet(filename="req.sh", size=20, md5_digest="a" * 32)
    snippet.meta = {
        **snippet.meta,
        "parameters": [
            {"name": "mode", "type": "str", "label": "Mode"},
            {
                "name": "reason",
                "type": "str",
                "label": "Reason",
                "requires_when": {"parameter": "mode", "equals": "write"},
            },
        ],
    }
    request = MagicMock()
    # ``mode == write`` but ``reason`` omitted -> requires gate fires.
    request.form.return_value = _AsyncForm(
        {EXECUTOR_HOSTS_INPUT_NAME: "host1", "mode": "write"}
    )
    mock_messages = mocker.patch.object(snippets_deps, "messages")
    mocker.patch.object(
        snippets_deps,
        "_get_snippet_redirect_exc",
        return_value=RuntimeError("redirect"),
    )

    with pytest.raises(RuntimeError, match="redirect"):
        await snippets_deps.get_validated_execution_args(request, snippet, referer=None)

    mock_messages.error.assert_called_once()


@pytest.mark.asyncio
async def test_get_validated_execution_args_allows_when_gate_not_fired(mocker):
    """When the gate does not fire, the legacy path returns the validated args."""
    snippet = _gated_snippet()
    request = MagicMock()
    # ``list`` omitted -> defaults falsy -> gate does not fire; ``start`` allowed.
    request.form.return_value = _AsyncForm(
        {EXECUTOR_HOSTS_INPUT_NAME: "host1", "start": "2020"}
    )
    mock_messages = mocker.patch.object(snippets_deps, "messages")

    result = await snippets_deps.get_validated_execution_args(
        request, snippet, referer=None
    )

    assert result.executor_host == "host1"
    mock_messages.error.assert_not_called()


@pytest.mark.asyncio
async def test_get_validated_execution_args_gateless_unchanged(mocker):
    """A gateless snippet validates and returns without gate evaluation effects."""
    snippet = Snippet(filename="plain.sh", size=20, md5_digest="a" * 32)
    snippet.meta = {
        **snippet.meta,
        "parameters": [{"name": "name", "type": "str", "label": "Name"}],
    }
    request = MagicMock()
    request.form.return_value = _AsyncForm(
        {EXECUTOR_HOSTS_INPUT_NAME: "host1", "name": "x"}
    )
    mock_messages = mocker.patch.object(snippets_deps, "messages")

    result = await snippets_deps.get_validated_execution_args(
        request, snippet, referer=None
    )

    assert result.executor_host == "host1"
    mock_messages.error.assert_not_called()


@pytest.mark.asyncio
async def test_build_snippet_execution_meta_matches_legacy_dep(create_snippet):
    """``build_snippet_execution_meta`` produces byte-identical meta as the dep."""
    snippet = await create_snippet("hello.sh", approved=True)
    execution_args = snippet.get_execution_model().model_validate(
        {EXECUTOR_HOSTS_INPUT_NAME: "host1"},
    )
    snippet_source = "https://signed.example/artifact?token=abc"

    helper_meta = build_snippet_execution_meta(snippet, execution_args, snippet_source)
    dep_meta = get_snippet_execution_request_meta(
        snippet=snippet,
        snippet_source=snippet_source,
        execution_args=execution_args,
    )

    assert helper_meta.model_dump(
        by_alias=True, exclude_none=True
    ) == dep_meta.model_dump(
        by_alias=True,
        exclude_none=True,
    )


@pytest.mark.asyncio
async def test_build_snippet_execution_meta_prepends_sudo_when_always(create_snippet):
    """A snippet whose sudo == ALWAYS prepends ``sudo`` to the interpreter."""
    snippet = await create_snippet("hello.sh", approved=True)
    snippet.__dict__.pop("sudo", None)
    snippet.meta = {**snippet.meta, "sudo": "always"}
    snippet.__dict__.pop("sudo", None)
    assert snippet.sudo == SnippetSudoOption.ALWAYS

    execution_args = snippet.get_execution_model().model_validate(
        {EXECUTOR_HOSTS_INPUT_NAME: "host1"},
    )

    meta = build_snippet_execution_meta(snippet, execution_args, "https://x/y")

    assert meta.interpreter.startswith("sudo ")


@pytest.mark.asyncio
async def test_build_snippet_execution_meta_raises_when_no_interpreter(
    create_snippet, mocker
):
    """Raise ``HTTPBadRequestException`` when the snippet has no configured interpreter."""
    snippet = await create_snippet("hello.sh", approved=True)
    execution_args = snippet.get_execution_model().model_validate(
        {EXECUTOR_HOSTS_INPUT_NAME: "host1"},
    )
    mocker.patch.object(
        Snippet,
        "execution_interpreter",
        new_callable=mocker.PropertyMock,
        return_value=None,
    )

    with pytest.raises(HTTPBadRequestException):
        build_snippet_execution_meta(snippet, execution_args, "https://x/y")


@pytest.mark.asyncio
async def test_get_executable_snippet_for_api_raises_403_for_unapproved(
    create_snippet,
):
    """The API-friendly executable dep raises 403, not a redirect."""
    snippet = await create_snippet("hello.sh", approved=False)

    with pytest.raises(HTTPForbiddenException) as exc_info:
        get_executable_snippet_for_api(snippet=snippet)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert "not approved" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_get_executable_snippet_for_api_raises_403_for_uninterpretable(
    create_snippet,
):
    """An approved snippet that cannot execute raises 403 with the right detail."""
    snippet = await create_snippet("hello.sh", approved=True)
    fake_snippet = MagicMock()
    fake_snippet.is_approved = True
    fake_snippet.can_execute = False
    fake_snippet.filename = snippet.filename

    with pytest.raises(HTTPForbiddenException) as exc_info:
        get_executable_snippet_for_api(snippet=fake_snippet)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert "cannot be executed" in str(exc_info.value.detail)


def test_validate_snippet_parameters_adds_non_sticky_messages():
    """Validation messages are non-sticky flash messages with no path scoping."""
    request = MagicMock()
    snippet = MagicMock()
    snippet.is_approved = True
    snippet.filename = "hello.sh"
    snippet.validated_parameters.errors = ["Bad parameter"]

    with pytest.MonkeyPatch.context() as monkeypatch:
        warning_mock = MagicMock()
        error_mock = MagicMock()
        monkeypatch.setattr(snippets_deps.messages, "warning", warning_mock)
        monkeypatch.setattr(snippets_deps.messages, "error", error_mock)
        validate_snippet_parameters(request=request, snippet=snippet)

    assert warning_mock.call_count + error_mock.call_count == 1
    called_mock = warning_mock if warning_mock.call_count else error_mock
    called_mock.assert_called_once_with(request, "Bad parameter")


class TestCheckSnippetBatchExistence:
    """Tests for ``check_snippet_batch_existence`` precheck helper."""

    @pytest.mark.asyncio
    async def test_all_present_returns_empty_result(self, session, create_snippet):
        """All filenames in DB and on disk → empty error arrays."""
        await create_snippet("a.sh")
        await create_snippet("b.sh")

        result = await check_snippet_batch_existence(session, ["a.sh", "b.sh"])

        assert isinstance(result, SnippetBatchExistenceResult)
        assert result.missing_in_db == []
        assert result.missing_on_disk == []
        assert result.has_errors is False
        assert {s.filename for s in result.snippets} == {"a.sh", "b.sh"}

    @pytest.mark.asyncio
    async def test_missing_in_db_listed(self, session, create_snippet):
        """A filename absent from the DB is listed in ``missing_in_db``."""
        await create_snippet("a.sh")

        result = await check_snippet_batch_existence(session, ["a.sh", "ghost.sh"])

        assert result.missing_in_db == ["ghost.sh"]
        assert result.missing_on_disk == []
        assert result.has_errors is True

    @pytest.mark.asyncio
    async def test_missing_on_disk_listed(self, session, create_snippet):
        """A row whose file is absent from disk is listed in ``missing_on_disk``."""
        await create_snippet("a.sh", create_file=True)
        await create_snippet("b.sh", create_file=False)

        result = await check_snippet_batch_existence(session, ["a.sh", "b.sh"])

        assert result.missing_in_db == []
        assert result.missing_on_disk == ["b.sh"]
        assert result.has_errors is True

    @pytest.mark.asyncio
    async def test_both_categories_populated(self, session, create_snippet):
        """Both error arrays populate when the input mixes the two failures."""
        await create_snippet("on-disk.sh", create_file=True)
        await create_snippet("missing-file.sh", create_file=False)

        result = await check_snippet_batch_existence(
            session, ["on-disk.sh", "missing-file.sh", "ghost.sh"]
        )

        assert result.missing_in_db == ["ghost.sh"]
        assert result.missing_on_disk == ["missing-file.sh"]
        assert result.has_errors is True

    @pytest.mark.asyncio
    async def test_results_are_sorted(self, session, create_snippet):
        """Both arrays are sorted alphabetically for stable error rendering."""
        result = await check_snippet_batch_existence(session, ["z.sh", "a.sh"])

        assert result.missing_in_db == ["a.sh", "z.sh"]


class TestValidateSnippetFilename:
    """Unit tests for the ``_validate_snippet_filename`` guard."""

    def test_uses_built_in_filename_checks_without_regex_sentinel(self):
        """Filename validation is implemented with built-ins, not a regex sentinel."""
        assert not hasattr(snippets_deps, "_SAFE_FILENAME_RE")

    @pytest.mark.parametrize(
        "safe",
        [
            "hello.sh",
            "my-script.sh",
            "my_script.sh",
            "script_v2.sh",
            "check.py",
            "run.rb",
            "audit.sql",
            # safe subdirectory paths
            "sub/dir.sh",
            "team/check.sh",
            "v2/scripts/run.py",
        ],
    )
    def test_accepts_valid_filenames(self, safe):
        """Safe filenames pass without raising."""
        validate_snippet_filename(safe)  # must not raise

    @pytest.mark.parametrize(
        "bad",
        [
            "/tmp/evil.sh",
            "C:\\tmp\\evil.sh",
            "\\server\\share\\evil.sh",
            "C:evil.sh",
            "../evil.sh",
            "../../etc/passwd",
            "./relative.sh",
            ".hidden.sh",
            "back\\slash.sh",
            "no-extension",
            "bad name.sh",
            "semi;colon.sh",
            "ümlaut.sh",
            "",
            "sub//double.sh",
            "sub/no-ext",
            "sub/.hidden.sh",
            "sub/../escape.sh",
        ],
    )
    def test_rejects_unsafe_filenames(self, bad):
        """Traversal, hidden-file, separator, and extension-less names all raise 400."""
        with pytest.raises(HTTPBadRequestException) as exc_info:
            validate_snippet_filename(bad)
        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
