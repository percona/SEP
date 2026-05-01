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

from app.core.auth.exceptions import HTTPForbiddenException
from app.sep.plugins.snippets.deps import (
    build_snippet_execution_meta,
    get_executable_snippet_for_api,
    get_snippet_execution_request_meta,
)
from app.sep.snippets.config import SnippetSudoOption
from app.sep.snippets.models.snippet import (
    EXECUTOR_HOSTS_INPUT_NAME,
)


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
