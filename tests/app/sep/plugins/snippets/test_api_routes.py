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

"""HTTP integration tests for the snippets plugin's JSON API routes."""

from datetime import datetime, UTC
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.sep.snippets.models import Snippet
from app.tasks.models import TaskHistoryStatusEnum

API_BASE = "/api/plugins/snippets"


@pytest.mark.asyncio
class TestSnippetsApiList:
    """Tests for ``GET /api/plugins/snippets/``."""

    async def test_returns_empty_list_when_no_snippets(
        self, test_client, session: AsyncSession, snippets_dir
    ):
        """Empty DB → empty list with a 200 ``application/json`` response."""
        response = test_client.get(f"{API_BASE}/")

        assert response.status_code == status.HTTP_200_OK
        assert "application/json" in response.headers["content-type"]
        assert response.json() == []

    async def test_returns_snippet_payload(self, test_client, create_snippet):
        """A persisted snippet is projected into its API response shape."""
        snippet = await create_snippet("hello.sh", approved=True)

        response = test_client.get(f"{API_BASE}/")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body) == 1
        row = body[0]
        assert row["filename"] == snippet.filename
        assert row["title"] == snippet.title
        assert row["is_approved"] is True
        assert row["md5_digest"] == "a" * 32
        assert row["sudo_optional"] is False


@pytest.mark.asyncio
class TestSnippetsPluginSchema:
    """Tests for ``GET /api/plugins/snippets/schema``."""

    async def test_returns_static_plugin_schema(self, test_client):
        """The static plugin schema declares no forms but a populated list view."""
        response = test_client.get(f"{API_BASE}/schema")

        assert response.status_code == status.HTTP_200_OK
        assert "application/json" in response.headers["content-type"]
        body = response.json()
        assert body["name"] == "snippets"
        assert body["forms"] == []
        column_keys = [column["key"] for column in body["listView"]["columns"]]
        assert "filename" in column_keys
        assert "isApproved" in column_keys


@pytest.mark.asyncio
class TestSnippetsApiPerSnippetSchema:
    """Tests for ``GET /api/plugins/snippets/{snippet_filename}/schema``."""

    async def test_returns_404_for_unknown_snippet(self, test_client):
        """A missing snippet filename surfaces as a 404."""
        response = test_client.get(f"{API_BASE}/missing.sh/schema")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_returns_per_snippet_schema_with_preview_field(
        self, test_client, create_snippet
    ):
        """The execution section embeds a ScriptPreviewField with a baked URL."""
        snippet = await create_snippet("hello.sh", approved=True)

        response = test_client.get(f"{API_BASE}/{snippet.filename}/schema")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["name"] == "snippets"
        execution_section = next(
            section for section in body["forms"] if section["title"] == "Execution"
        )
        field_types = {field["type"] for field in execution_section["fields"]}
        assert "host" in field_types
        assert "script_preview" in field_types
        preview_field = next(
            field
            for field in execution_section["fields"]
            if field["type"] == "script_preview"
        )
        assert preview_field["endpointUrl"] == (
            f"/plugins/snippets/{snippet.filename}/script-preview"
        )


@pytest.mark.asyncio
class TestSnippetsApiScriptPreview:
    """Tests for ``GET /api/plugins/snippets/{snippet_filename}/script-preview``."""

    async def test_returns_preview_with_language_hint(
        self, test_client, create_snippet
    ):
        """The preview response carries content, truncation flag, and a language hint."""
        snippet = await create_snippet("hello.sh", approved=True)

        response = test_client.get(f"{API_BASE}/{snippet.filename}/script-preview")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert "echo hi" in body["content"]
        assert body["is_truncated"] is False
        assert isinstance(body["language"], str)

    async def test_returns_422_for_undecodable_snippet(
        self, test_client, create_snippet
    ):
        """A snippet with non-UTF-8 bytes returns 422 instead of 500."""
        snippet = await create_snippet("binary.sh", approved=True, create_file=False)
        # Replace the seeded text file with binary garbage.

        (Snippet.BASE_DIR / snippet.filename).write_bytes(b"\xff\xfe\x00\x01")

        with patch.object(
            type(snippet),
            "get_preview",
            side_effect=UnicodeDecodeError("utf-8", b"\xff", 0, 1, "boom"),
        ):
            response = test_client.get(
                f"{API_BASE}/{snippet.filename}/script-preview",
            )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
class TestSnippetsApiHistory:
    """Tests for ``GET /api/plugins/snippets/{snippet_filename}/history``."""

    async def test_history_passes_filter_and_inlines_files(
        self, test_client, mock_task_api_dep, create_snippet
    ):
        """History endpoint filters by snippet filename and inlines available files."""
        snippet = await create_snippet("hello.sh", approved=True)
        history_id = 42
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                {
                    "items": [
                        {
                            "id": history_id,
                            "status": TaskHistoryStatusEnum.SUCCESS.value,
                            "created_at": datetime.now(UTC).isoformat(),
                            "created_by": "alice",
                        },
                    ],
                    "total": 1,
                    "offset": 0,
                    "limit": 50,
                },
                ["log.txt"],
            ],
        )

        response = test_client.get(f"{API_BASE}/{snippet.filename}/history")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body) == 1
        assert body[0]["task_id"] == history_id
        assert body[0]["available_files"] == ["log.txt"]
        first_call = mock_task_api_dep.get.call_args_list[0]
        assert first_call.kwargs["params"] == {"snippet_filename": snippet.filename}


@pytest.mark.asyncio
class TestSnippetsApiExecute:
    """Tests for ``POST /api/plugins/snippets/{snippet_filename}/execute``."""

    async def test_returns_403_when_snippet_not_approved(
        self, test_client, mock_task_api_dep, create_snippet
    ):
        """An unapproved snippet's execute endpoint returns 403, not a redirect."""
        snippet = await create_snippet("hello.sh", approved=False)

        response = test_client.post(
            f"{API_BASE}/{snippet.filename}/execute",
            json={"executor_host": "host1"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_task_api_dep.post.assert_not_called()

    async def test_returns_404_for_unknown_snippet(
        self, test_client, mock_task_api_dep
    ):
        """Executing an unknown snippet returns 404 without calling the tasks API."""
        response = test_client.post(
            f"{API_BASE}/missing.sh/execute",
            json={"executor_host": "host1"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_task_api_dep.post.assert_not_called()

    async def test_executes_snippet_and_returns_task_response(
        self, test_client, mock_task_api_dep, create_snippet
    ):
        """Successful execution returns 201 + task id and posts the meta payload."""
        snippet = await create_snippet("hello.sh", approved=True)
        mock_task_api_dep.post = AsyncMock(return_value={"id": 99})

        response = test_client.post(
            f"{API_BASE}/{snippet.filename}/execute",
            json={"executor_host": "host1", "args": {}},
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        expected_task_id = 99
        assert body["task_id"] == expected_task_id
        assert body["snippet_filename"] == snippet.filename
        assert mock_task_api_dep.post.called
        path_arg = mock_task_api_dep.post.call_args.args[0]
        assert path_arg.startswith("/execute/")
        meta = mock_task_api_dep.post.call_args.kwargs["json"]["meta"]
        assert meta["target"] == "host1"
        assert meta["_snippet_filename"] == snippet.filename
        assert meta["md5_checksum"] == snippet.md5_digest


# Override the module-level test_client fixture so it uses the same in-memory
# session as the other snippet plugin tests; otherwise the snippets table is
# absent on the default global session.


@pytest.fixture
def test_client(regular_user, session, snippets_dir):
    """Return a TestClient sharing the in-memory session and snippets dir."""
    from fastapi.testclient import TestClient

    from app.sep.deps import (
        get_api_authenticated_user,
        get_current_user,
        get_session,
        validate_csrf,
    )
    from app.sep.main import sep_app

    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user
    sep_app.dependency_overrides[get_api_authenticated_user] = lambda: regular_user
    sep_app.dependency_overrides[get_session] = lambda: session
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}
