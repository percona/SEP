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

"""Cover the keying-agnostic script-app helpers directly.

Each helper takes the already-resolved script / meta, so the tests build a plain
in-memory ``Snippet`` (no DB row needed) and assert byte-identical output against
a hand-constructed expected value — the same guarantee the unchanged OpenAPI
snapshots prove end-to-end.
"""

from unittest.mock import AsyncMock

import pytest
from starlette.datastructures import URL
from starlette.requests import Request

from app.core.exceptions import HTTPBadRequestException
from app.core.requests import RemoteAPI
from app.core.security import crypto_timestamp_serializer
from app.sep.apps.framework.script_helpers import (
    build_artifact_download_url,
    build_execution_meta,
    build_script_preview,
    post_task_execution,
)
from app.sep.artifact_constants import (
    ARTIFACT_DOWNLOAD_SALT,
    ARTIFACT_TYPE_DIPPER,
    ARTIFACT_TYPE_SNIPPET,
)
from app.sep.snippets.config import snippets_settings
from app.sep.snippets.models.snippet import (
    EXECUTOR_HOSTS_INPUT_NAME,
    FilePreview,
    Snippet,
    SnippetExecutionMeta,
    SUDO_INPUT_NAME,
)
from app.sep.snippets.utils import guess_mime_type, mime_type_to_highlighter_language

_MD5 = "a" * 32


def _snippet(*, filename: str = "script.sh", sudo: str | None = None) -> Snippet:
    """Return an unpersisted snippet, optionally carrying a ``sudo`` meta value."""
    snippet = Snippet(filename=filename, size=20, md5_digest=_MD5)
    if sudo is not None:
        snippet.meta = {**snippet.meta, "sudo": sudo}
    return snippet


def _execution_args(snippet: Snippet, extra: dict[str, object] | None = None):
    """Validate execution args for ``snippet`` with an executor host set."""
    return snippet.get_execution_model().model_validate(
        {EXECUTOR_HOSTS_INPUT_NAME: "host1", **(extra or {})}
    )


def _make_request(host: str = "sep.example") -> Request:
    """Return a minimal HTTPS request whose host derives the base URL."""
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "https",
            "server": (host, 443),
            "path": "/api/apps/snippets/snippet/download",
            "query_string": b"",
            "headers": [(b"host", host.encode())],
        }
    )


class TestBuildScriptPreview:
    """Cover the preview-response builder and its decode-error propagation."""

    @pytest.mark.asyncio
    async def test_maps_get_preview_to_response(self, mocker) -> None:
        """Map ``get_preview`` output to a response with a MIME-derived language."""
        snippet = _snippet()
        preview = FilePreview(
            preamble="#!/bin/sh\n",
            frontmatter="",
            content="echo hi\n",
            is_truncated=True,
        )
        mocker.patch.object(Snippet, "get_preview", AsyncMock(return_value=preview))

        result = await build_script_preview(snippet)

        assert result.content == preview.full_content
        assert result.is_truncated is True
        assert result.language == mime_type_to_highlighter_language(
            guess_mime_type(snippet.path)
        )

    @pytest.mark.asyncio
    async def test_propagates_unicode_decode_error(self, mocker) -> None:
        """Propagate ``UnicodeDecodeError`` rather than building a 422 itself."""
        snippet = _snippet()
        mocker.patch.object(
            Snippet,
            "get_preview",
            AsyncMock(
                side_effect=UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid byte")
            ),
        )

        with pytest.raises(UnicodeDecodeError):
            await build_script_preview(snippet)


class TestBuildExecutionMeta:
    """Cover the sudo-resolving execution-meta assembly."""

    def test_no_sudo_keeps_interpreter(self) -> None:
        """Keep the interpreter untouched when neither script nor args opt into sudo."""
        snippet = _snippet()
        meta = build_execution_meta(
            snippet,
            _execution_args(snippet),
            interpreter="bash",
            snippet_source="https://x/y",
            snippet_filename="script.sh",
        )

        assert meta.interpreter == "bash"
        assert meta.target == "host1"
        assert meta.md5_checksum == _MD5

    def test_sudo_when_script_sudo_always(self) -> None:
        """Prepend ``sudo`` when the script's sudo option is ``ALWAYS``."""
        snippet = _snippet(sudo="always")
        meta = build_execution_meta(
            snippet,
            _execution_args(snippet),
            interpreter="bash",
            snippet_source="https://x/y",
            snippet_filename="script.sh",
        )

        assert meta.interpreter == "sudo bash"

    def test_sudo_when_args_field_truthy(self) -> None:
        """Prepend ``sudo`` when the validated args carry a truthy sudo field."""
        snippet = _snippet(sudo="optional")
        args = _execution_args(snippet, {SUDO_INPUT_NAME: True})
        meta = build_execution_meta(
            snippet,
            args,
            interpreter="bash",
            snippet_source="https://x/y",
            snippet_filename="script.sh",
        )

        assert meta.interpreter == "sudo bash"

    def test_sudo_default_applies_when_args_lack_field(self) -> None:
        """Use ``sudo_default`` when the args model has no sudo field."""
        snippet = _snippet()
        meta = build_execution_meta(
            snippet,
            _execution_args(snippet),
            interpreter="bash",
            snippet_source="https://x/y",
            snippet_filename="script.sh",
            sudo_default=True,
        )

        assert meta.interpreter == "sudo bash"

    def test_snippet_filename_is_caller_keyed(self) -> None:
        """Record the caller-supplied ``snippet_filename`` under its serialized alias."""
        snippet = _snippet()
        meta = build_execution_meta(
            snippet,
            _execution_args(snippet),
            interpreter="bash",
            snippet_source="https://x/y",
            snippet_filename="dipper/7/x.sh",
        )

        dumped = meta.model_dump(by_alias=True, exclude_none=True)
        assert dumped["_snippet_filename"] == "dipper/7/x.sh"


class TestBuildArtifactDownloadUrl:
    """Cover the signed artifact-URL builder across request-backed and request-less paths."""

    @staticmethod
    def _decode(url: str) -> dict:
        token = url.rsplit("/artifacts/download/", 1)[1]
        return crypto_timestamp_serializer.loads(token, salt=ARTIFACT_DOWNLOAD_SALT)

    def test_request_backed_snippet_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Build a snippet-type token URL against the configured base URL."""
        monkeypatch.setattr(
            snippets_settings, "SNIPPETS_BASE_URL", URL("https://sep.example")
        )
        url = build_artifact_download_url(
            _make_request(),
            artifact_type=ARTIFACT_TYPE_SNIPPET,
            filename="x.sh",
            md5_digest=_MD5,
        )

        assert url.startswith("https://sep.example/artifacts/download/")
        assert self._decode(url) == {"type": "snippet", "filename": "x.sh", "md5": _MD5}

    def test_request_backed_dipper_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Build a dipper-type token URL, differing from the snippet URL only by type."""
        monkeypatch.setattr(
            snippets_settings, "SNIPPETS_BASE_URL", URL("https://sep.example")
        )
        url = build_artifact_download_url(
            _make_request(),
            artifact_type=ARTIFACT_TYPE_DIPPER,
            filename="x.sh",
            md5_digest=_MD5,
        )

        assert self._decode(url)["type"] == "dipper"

    def test_request_backed_falls_back_to_request_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Derive the base URL from the request host when no base URL is configured."""
        monkeypatch.setattr(snippets_settings, "SNIPPETS_BASE_URL", None)
        monkeypatch.setattr("app.core.config.settings.BASE_URL", None)
        url = build_artifact_download_url(
            _make_request(host="host.internal"),
            artifact_type=ARTIFACT_TYPE_SNIPPET,
            filename="x.sh",
            md5_digest=_MD5,
        )

        assert url.startswith("https://host.internal/artifacts/download/")

    def test_request_less_uses_configured_base(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Use the configured base URL on the request-less path."""
        monkeypatch.setattr(
            snippets_settings, "SNIPPETS_BASE_URL", URL("https://sep.example")
        )
        url = build_artifact_download_url(
            None,
            artifact_type=ARTIFACT_TYPE_SNIPPET,
            filename="x.sh",
            md5_digest=_MD5,
        )

        assert url.startswith("https://sep.example/artifacts/download/")

    def test_request_less_without_base_url_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Raise 400 with the exact message when no base URL is set request-less."""
        monkeypatch.setattr(snippets_settings, "SNIPPETS_BASE_URL", None)
        monkeypatch.setattr("app.core.config.settings.BASE_URL", None)

        with pytest.raises(HTTPBadRequestException) as exc_info:
            build_artifact_download_url(
                None,
                artifact_type=ARTIFACT_TYPE_SNIPPET,
                filename="x.sh",
                md5_digest=_MD5,
            )

        assert exc_info.value.detail == (
            "Snippet execution requires SNIPPETS_BASE_URL or BASE_URL to be set."
        )


class TestPostTaskExecution:
    """Cover the execute-POST tail and its soft id extraction."""

    @staticmethod
    def _meta() -> SnippetExecutionMeta:
        return SnippetExecutionMeta(
            target="host1",
            interpreter="bash",
            snippet_source="https://x/y",
            snippet_filename="x.sh",
            md5_checksum=_MD5,
        )

    @pytest.mark.asyncio
    async def test_returns_id_and_posts_meta_envelope(self) -> None:
        """Send the meta envelope and return the created task id."""
        expected_id = 42
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.post.return_value = {"id": expected_id, "status": "queued"}
        meta = self._meta()

        task_id = await post_task_execution(tasks_api, "run_snippet", meta)

        assert task_id == expected_id
        tasks_api.post.assert_awaited_once_with(
            "/execute/run_snippet",
            json={"meta": meta.model_dump(by_alias=True, exclude_none=True)},
        )

    @pytest.mark.asyncio
    async def test_returns_none_when_id_absent(self) -> None:
        """Return ``None`` when the upstream dict carries no id."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.post.return_value = {}

        assert await post_task_execution(tasks_api, "run_snippet", self._meta()) is None

    @pytest.mark.asyncio
    async def test_returns_none_when_response_not_dict(self) -> None:
        """Return ``None`` when the upstream response is not a dict."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.post.return_value = []

        assert await post_task_execution(tasks_api, "run_snippet", self._meta()) is None
