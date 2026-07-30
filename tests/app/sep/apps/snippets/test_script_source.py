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

"""Cover the snippets ``ScriptSource`` hooks directly against a real session.

The hooks are exercised through the public :data:`snippet_source` surface
(``load_script`` / ``list_scripts`` / ``load_scripts`` / ``build_form_schema`` /
``build_execution_meta`` / ``list_response``) rather than the private module
functions, mirroring the framework's own ``test_script_source.py``. ``load_script``
/ ``list_scripts`` / ``load_scripts`` open their own request-less session, so the
suite points ``script_source.get_async_session_maker`` at the in-memory test
session (the same pattern ``tests/app/sep/apps/snippets/test_celery.py`` uses for
the Celery sync task) — the real session is exercised, never a mocked
``AsyncSession``.
"""

from collections.abc import Awaitable, Callable

import pytest
from pytest_mock import MockerFixture
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.datastructures import URL

from app.core.auth.exceptions import HTTPForbiddenException
from app.core.exceptions import (
    HTTPBadRequestException,
    HTTPNotFoundException,
    HTTPUnprocessableEntityException,
)
from app.sep.apps.framework.script_source import ScriptExecuteWrite
from app.sep.apps.snippets.deps import build_snippet_execution_meta
from app.sep.apps.snippets.script_source import (
    build_snippet_source,
    snippet_source,
    SnippetScript,
)
from app.sep.snippets.config import snippets_settings, SnippetSudoOption
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models.snippet import (
    EXECUTOR_HOSTS_INPUT_NAME,
    EXTRA_ARGS_INPUT_NAME,
    Snippet,
    SnippetExecutionMeta,
)

pytestmark = pytest.mark.asyncio


def _framework_processed_body(
    script: SnippetScript, body: ScriptExecuteWrite
) -> ScriptExecuteWrite:
    """Reproduce the framework execute route's pre-processing before the hook runs.

    ``derive_script_routes`` validates ``body.args`` against the script's args-only
    model and replaces them with the model's coerced ``model_dump()`` (keyed by
    Python attribute name), so the hook never sees the raw client args. Tests that
    call the hook directly must reproduce this or they exercise an unreachable path.
    """
    validated = script.get_execution_model().model_validate(body.args)
    return body.model_copy(update={"args": validated.model_dump()})


def _legacy_execution_meta(
    snippet: Snippet, body: ScriptExecuteWrite
) -> SnippetExecutionMeta:
    """Rebuild the meta the way the pre-migration JSON execute route did."""
    raw_args = {**body.args, EXECUTOR_HOSTS_INPUT_NAME: body.executor_host}
    if snippet.sudo.is_optional:
        raw_args.setdefault("sudo", body.sudo)
    legacy_args = snippet.get_execution_model().model_validate(raw_args)
    return build_snippet_execution_meta(
        snippet, legacy_args, build_snippet_source(snippet)
    )


class TestLoadAndListScripts:
    """Cover ``load_script`` / ``list_scripts`` (request-less, detached rows)."""

    async def test_load_script_returns_detached_usable_script(
        self,
        request_less_session: AsyncSession,
        create_snippet: Callable[..., Awaitable[Snippet]],
    ) -> None:
        """Resolve a snippet to a ``SnippetScript`` usable after the session closes."""
        await create_snippet("ok.sh", approved=True)
        script = await snippet_source.load_script("ok.sh")
        assert isinstance(script, SnippetScript)
        assert script.filename == "ok.sh"
        assert script.execution_task_name

    async def test_load_script_missing_db_row_raises_404(
        self, request_less_session: AsyncSession
    ) -> None:
        """Raise 404 when no snippet row matches the filename."""
        with pytest.raises(HTTPNotFoundException):
            await snippet_source.load_script("missing.sh")

    async def test_load_script_missing_on_disk_raises_404(
        self,
        request_less_session: AsyncSession,
        create_snippet: Callable[..., Awaitable[Snippet]],
    ) -> None:
        """Raise 404 when the DB row exists but the file is gone from disk."""
        await create_snippet("gone.sh", approved=True, create_file=False)
        with pytest.raises(HTTPNotFoundException):
            await snippet_source.load_script("gone.sh")

    async def test_list_scripts_returns_all_detached(
        self,
        request_less_session: AsyncSession,
        create_snippet: Callable[..., Awaitable[Snippet]],
    ) -> None:
        """Return one ``SnippetScript`` per discovered snippet row."""
        await create_snippet("a.sh")
        await create_snippet("b.sh")
        scripts = await snippet_source.list_scripts()
        assert sorted(script.filename for script in scripts) == ["a.sh", "b.sh"]


class TestLoadScriptsBatch:
    """Cover the batch ``load_scripts`` hook (one query, detached rows, filtering)."""

    async def test_resolves_selection_in_one_query(
        self,
        request_less_session: AsyncSession,
        create_snippet: Callable[..., Awaitable[Snippet]],
        mocker: MockerFixture,
    ) -> None:
        """Resolve several filenames with a single ``SnippetManager.list`` call."""
        await create_snippet("a.sh")
        await create_snippet("b.sh")
        spy = mocker.spy(SnippetManager, "list")

        resolved = await snippet_source.load_scripts(["a.sh", "b.sh"])

        assert set(resolved) == {"a.sh", "b.sh"}
        assert spy.call_count == 1

    async def test_returns_detached_usable_scripts(
        self,
        request_less_session: AsyncSession,
        create_snippet: Callable[..., Awaitable[Snippet]],
    ) -> None:
        """Return scripts usable after the request-less session closes."""
        await create_snippet("a.sh", approved=True)
        resolved = await snippet_source.load_scripts(["a.sh"])
        assert isinstance(resolved["a.sh"], SnippetScript)
        assert resolved["a.sh"].filename == "a.sh"
        assert resolved["a.sh"].execution_task_name

    async def test_missing_db_row_is_omitted(
        self,
        request_less_session: AsyncSession,
        create_snippet: Callable[..., Awaitable[Snippet]],
    ) -> None:
        """Leave a filename with no matching row out of the result."""
        await create_snippet("a.sh")
        resolved = await snippet_source.load_scripts(["a.sh", "missing.sh"])
        assert set(resolved) == {"a.sh"}

    async def test_missing_file_on_disk_is_omitted(
        self,
        request_less_session: AsyncSession,
        create_snippet: Callable[..., Awaitable[Snippet]],
    ) -> None:
        """Leave a filename whose row exists but file is gone out of the result."""
        await create_snippet("a.sh")
        await create_snippet("gone.sh", create_file=False)
        resolved = await snippet_source.load_scripts(["a.sh", "gone.sh"])
        assert set(resolved) == {"a.sh"}

    async def test_duplicate_filename_is_queried_once(
        self,
        request_less_session: AsyncSession,
        create_snippet: Callable[..., Awaitable[Snippet]],
        mocker: MockerFixture,
    ) -> None:
        """Resolve a repeated filename to one row with a single query."""
        await create_snippet("a.sh")
        spy = mocker.spy(SnippetManager, "list")

        resolved = await snippet_source.load_scripts(["a.sh", "a.sh"])

        assert set(resolved) == {"a.sh"}
        assert spy.call_count == 1

    async def test_unsafe_filename_is_rejected(
        self, request_less_session: AsyncSession
    ) -> None:
        """Reject an unsafe filename before any lookup runs."""
        with pytest.raises(HTTPBadRequestException):
            await snippet_source.load_scripts(["../secret.sh"])

    async def test_case_insensitive_match_keyed_by_requested_spelling(
        self,
        request_less_session: AsyncSession,
        create_snippet: Callable[..., Awaitable[Snippet]],
        mocker: MockerFixture,
    ) -> None:
        """Key a case-folded row match by the requested spelling, not the row's.

        A case-insensitive collation matches ``Check.sh`` to row ``check.sh``;
        callers look the result up by the string they sent, so the hook must key
        that row by ``Check.sh``. SQLite's ``IN`` is case-sensitive, so the
        collation match is simulated by returning the seeded lowercase row.
        """
        snippet = await create_snippet("check.sh")
        mocker.patch.object(
            SnippetManager, "list", mocker.AsyncMock(return_value=[snippet])
        )

        resolved = await snippet_source.load_scripts(["Check.sh"])

        assert set(resolved) == {"Check.sh"}
        assert resolved["Check.sh"].filename == "check.sh"

    async def test_two_case_variants_of_one_file_both_resolve(
        self,
        request_less_session: AsyncSession,
        create_snippet: Callable[..., Awaitable[Snippet]],
        mocker: MockerFixture,
    ) -> None:
        """Key one collation-matched row by every requested spelling of it.

        A selection carrying both ``Check.sh`` and ``check.sh`` folds to one
        row on a case-insensitive collation; the many-to-one map keeps both
        spellings as keys so neither caller lookup drops to ``None``.
        """
        snippet = await create_snippet("check.sh")
        mocker.patch.object(
            SnippetManager, "list", mocker.AsyncMock(return_value=[snippet])
        )

        resolved = await snippet_source.load_scripts(["Check.sh", "check.sh"])

        assert set(resolved) == {"Check.sh", "check.sh"}
        assert resolved["Check.sh"].snippet is resolved["check.sh"].snippet
        assert resolved["Check.sh"].filename == "check.sh"


class TestArgsOnlyModel:
    """Cover the args-only execution model the framework validates against."""

    async def test_validates_without_hostname(
        self,
        request_less_session: AsyncSession,
        create_snippet: Callable[..., Awaitable[Snippet]],
    ) -> None:
        """Validate an empty args body even though ``-hostname-`` is absent."""
        await create_snippet("ok.sh", approved=True)
        script = await snippet_source.load_script("ok.sh")
        validated = script.get_execution_model().model_validate({})
        assert validated.executor_host is None


class TestBuildSnippetSource:
    """Cover the request-less artifact-URL builder."""

    async def test_raises_400_when_no_base_url(
        self,
        request_less_session: AsyncSession,
        create_snippet: Callable[..., Awaitable[Snippet]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Raise 400 when neither SNIPPETS_BASE_URL nor BASE_URL is set."""
        monkeypatch.setattr(snippets_settings, "SNIPPETS_BASE_URL", None)
        monkeypatch.setattr(
            "app.sep.apps.framework.script_helpers.settings.BASE_URL", None
        )
        await create_snippet("ok.sh", approved=True)
        script = await snippet_source.load_script("ok.sh")
        with pytest.raises(HTTPBadRequestException):
            build_snippet_source(script.snippet)

    async def test_builds_token_url_when_configured(
        self,
        request_less_session: AsyncSession,
        create_snippet: Callable[..., Awaitable[Snippet]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Build the ``/artifacts/download/<token>`` URL from the configured base."""
        monkeypatch.setattr(
            snippets_settings, "SNIPPETS_BASE_URL", URL("https://sep.example")
        )
        await create_snippet("ok.sh", approved=True)
        script = await snippet_source.load_script("ok.sh")
        url = build_snippet_source(script.snippet)
        assert url.startswith("https://sep.example/artifacts/download/")


class TestBuildExecutionMeta:
    """Cover the execute-meta hook (executability guard + legacy parity)."""

    async def test_unapproved_snippet_raises_403(
        self,
        request_less_session: AsyncSession,
        create_snippet: Callable[..., Awaitable[Snippet]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Reject an unapproved snippet with 403 before any execution meta is built."""
        monkeypatch.setattr(
            snippets_settings, "SNIPPETS_BASE_URL", URL("https://sep.example")
        )
        await create_snippet("ok.sh", approved=False)
        script = await snippet_source.load_script("ok.sh")
        body = ScriptExecuteWrite(executor_host="host1", args={})
        with pytest.raises(HTTPForbiddenException):
            snippet_source.build_execution_meta(script, body)

    async def test_requires_gate_omitted_field_raises_422(
        self,
        request_less_session: AsyncSession,
        create_snippet: Callable[..., Awaitable[Snippet]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Reject a JSON execute omitting a requires-gated field with 422.

        Security backstop for the ``requires`` direction: the constraint must be
        enforced server-side on the JSON API path, not merely rendered client-side.
        """
        monkeypatch.setattr(
            snippets_settings, "SNIPPETS_BASE_URL", URL("https://sep.example")
        )
        snippet = await create_snippet("gated.sh", approved=True)
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
        snippet.__dict__.pop("validated_parameters", None)
        await SnippetManager.save(
            request_less_session, snippet, flag_modified_fields=["meta"]
        )
        script = await snippet_source.load_script("gated.sh")
        # ``mode == write`` but ``reason`` omitted -> requires gate fires.
        body = ScriptExecuteWrite(executor_host="host1", args={"mode": "write"})

        with pytest.raises(HTTPUnprocessableEntityException):
            snippet_source.build_execution_meta(
                script, _framework_processed_body(script, body)
            )

    async def test_meta_matches_legacy_path(
        self,
        request_less_session: AsyncSession,
        create_snippet: Callable[..., Awaitable[Snippet]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Produce the same execution meta as the legacy ``build_snippet_execution_meta``."""
        monkeypatch.setattr(
            snippets_settings, "SNIPPETS_BASE_URL", URL("https://sep.example")
        )
        await create_snippet("ok.sh", approved=True)
        script = await snippet_source.load_script("ok.sh")
        body = ScriptExecuteWrite(executor_host="host1", args={})

        hook_meta = snippet_source.build_execution_meta(
            script, _framework_processed_body(script, body)
        )
        legacy_meta = _legacy_execution_meta(script.snippet, body)

        assert hook_meta.model_dump() == legacy_meta.model_dump()

    async def test_extra_args_reach_command_via_new_schema_alias(
        self,
        request_less_session: AsyncSession,
        create_snippet: Callable[..., Awaitable[Snippet]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Deliver a schema-driven ``extra_args`` submission into the built command.

        End-to-end assertion for the new Extra Args field: a value keyed by the
        schema field name must survive the args-only twin's ``model_validate``,
        the hook's ``model_construct`` re-attachment, and land in the interpreter
        command string ``to_args_string()`` builds.
        """
        monkeypatch.setattr(
            snippets_settings, "SNIPPETS_BASE_URL", URL("https://sep.example")
        )
        snippet = await create_snippet("extra.sh", approved=True)
        snippet.meta = {**snippet.meta, "allow_extra_args": True}
        snippet.__dict__.pop("allow_extra_args", None)
        await SnippetManager.save(
            request_less_session, snippet, flag_modified_fields=["meta"]
        )
        script = await snippet_source.load_script("extra.sh")
        body = ScriptExecuteWrite(
            executor_host="host1", args={"extra_args": "--verbose"}
        )

        meta = snippet_source.build_execution_meta(
            script, _framework_processed_body(script, body)
        )

        assert "--verbose" in meta.args.split()

    async def test_extra_args_still_bind_via_legacy_alias(
        self,
        request_less_session: AsyncSession,
        create_snippet: Callable[..., Awaitable[Snippet]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Keep the legacy ``-extra_args-`` submission spelling working end-to-end.

        The new schema-driven alias must be additive, not a replacement, so
        both spellings resolve to the same execution args.
        """
        monkeypatch.setattr(
            snippets_settings, "SNIPPETS_BASE_URL", URL("https://sep.example")
        )
        snippet = await create_snippet("extra.sh", approved=True)
        snippet.meta = {**snippet.meta, "allow_extra_args": True}
        snippet.__dict__.pop("allow_extra_args", None)
        await SnippetManager.save(
            request_less_session, snippet, flag_modified_fields=["meta"]
        )
        script = await snippet_source.load_script("extra.sh")
        new_alias_body = ScriptExecuteWrite(
            executor_host="host1", args={"extra_args": "--verbose"}
        )
        legacy_body = ScriptExecuteWrite(
            executor_host="host1", args={EXTRA_ARGS_INPUT_NAME: "--verbose"}
        )

        new_alias_meta = snippet_source.build_execution_meta(
            script, _framework_processed_body(script, new_alias_body)
        )
        legacy_meta = _legacy_execution_meta(script.snippet, legacy_body)

        assert new_alias_meta.model_dump() == legacy_meta.model_dump()

    @pytest.mark.parametrize("requested_sudo", [True, False])
    async def test_optional_sudo_toggle_is_honored(
        self,
        request_less_session: AsyncSession,
        create_snippet: Callable[..., Awaitable[Snippet]],
        monkeypatch: pytest.MonkeyPatch,
        *,
        requested_sudo: bool,
    ) -> None:
        """Apply the user's sudo toggle on an optional-sudo snippet.

        The execution model keys sudo on its ``-sudo-`` alias (no
        ``populate_by_name``), so the plain ``ScriptExecuteWrite.sudo`` input is
        re-attached by attribute name; the interpreter gains its ``sudo`` prefix
        only when the caller opted in.
        """
        monkeypatch.setattr(
            snippets_settings, "SNIPPETS_BASE_URL", URL("https://sep.example")
        )
        snippet = await create_snippet("sudo.sh", approved=True)
        snippet.meta = {**snippet.meta, "sudo": SnippetSudoOption.OPTIONAL.value}
        snippet.__dict__.pop("validated_parameters", None)
        await SnippetManager.save(
            request_less_session, snippet, flag_modified_fields=["meta"]
        )
        script = await snippet_source.load_script("sudo.sh")
        assert script.snippet.sudo.is_optional
        body = ScriptExecuteWrite(executor_host="host1", sudo=requested_sudo, args={})

        meta = snippet_source.build_execution_meta(
            script, _framework_processed_body(script, body)
        )

        assert meta.interpreter.startswith("sudo ") == requested_sudo
