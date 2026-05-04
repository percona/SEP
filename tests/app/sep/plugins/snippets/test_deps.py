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
    check_snippet_batch_existence,
    get_executable_snippet_for_api,
    get_snippet_execution_request_meta,
    SnippetBatchExistenceResult,
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
