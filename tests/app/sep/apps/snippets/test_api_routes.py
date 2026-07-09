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
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.sep.apps.snippets.extra_routes as snippets_extra_routes
from app.sep.apps.snippets.models import (
    BatchApprovalErrorResponse,
    RefreshResponse,
    SnippetResponse,
    SnippetsCapabilitiesResponse,
)
from app.sep.deps import (
    BEARER_REQUIRED_DETAIL,
    get_api_authenticated_user,
    get_current_user,
    get_session,
    require_bearer_for_unsafe_methods,
    validate_csrf,
)
from app.sep.main import sep_app
from app.sep.snippets.config import snippets_settings
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models import Snippet
from app.tasks.models import TaskHistoryStatusEnum

API_BASE = "/api/apps/snippets"


async def _seed_gated_snippet(
    create_snippet, session, parameters, *, filename="gated.sh"
):
    """Seed an approved snippet whose meta declares ``parameters`` (persisted).

    The execute route reloads the snippet from the DB by filename, so the gated
    parameter metadata must be persisted (not just mutated in memory). The
    ``validated_parameters`` cache is dropped so the new meta is re-validated.
    """
    snippet = await create_snippet(filename, approved=True)
    snippet.meta = {**snippet.meta, "parameters": parameters}
    snippet.__dict__.pop("validated_parameters", None)
    await SnippetManager.save(session, snippet, flag_modified_fields=["meta"])
    return snippet


@pytest.fixture
def enable_manual_sync(mocker):
    """Fixture to patch ``ENABLE_MANUAL_SYNC`` setting."""

    def _patch_enable(*, value: bool) -> None:
        mocker.patch.object(
            snippets_settings,
            "ENABLE_MANUAL_SYNC",
            new=value,
        )

    return _patch_enable


class TestSnippetsApprovalApiReviewContracts:
    """Review-comment contracts for the snippets approval API surface."""

    def test_approval_response_collapses_into_snippet_response(self):
        """Single approval returns the snippet entity plus admin attribution."""
        from app.sep.apps.snippets import models as snippets_models

        assert "SnippetApprovalResponse" not in snippets_models.__all__
        assert not hasattr(snippets_models, "SnippetApprovalResponse")
        assert "updated_by" in SnippetResponse.model_fields

    def test_batch_approve_base_is_not_exported(self):
        """``SnippetBatchApproveBase`` is gone; callers use ``SnippetBatchApproveRequest``."""
        from app.sep.apps.snippets import models as snippets_models

        assert "SnippetBatchApproveBase" not in snippets_models.__all__
        assert not hasattr(snippets_models, "SnippetBatchApproveBase")

    def test_batch_approve_request_has_filenames_directly(self):
        """``SnippetBatchApproveRequest`` owns ``filenames`` — no delegation to a base."""
        from app.sep.apps.snippets.models import SnippetBatchApproveRequest

        assert "filenames" in SnippetBatchApproveRequest.model_fields

    def test_batch_approval_error_defaults_use_independent_factories(self):
        """Batch error array defaults are conventional and per-instance."""
        fields = BatchApprovalErrorResponse.model_fields

        assert fields["missing_in_db"].default_factory is list
        assert fields["missing_on_disk"].default_factory is list

        first = BatchApprovalErrorResponse()
        second = BatchApprovalErrorResponse()
        first.missing_in_db.append("ghost.sh")
        first.missing_on_disk.append("missing.sh")

        assert second.missing_in_db == []
        assert second.missing_on_disk == []


@pytest.mark.asyncio
class TestSnippetsApiList:
    """Tests for ``GET /api/apps/snippets/``."""

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
        assert row["service_type"] == snippet.service_type


@pytest.mark.asyncio
class TestSnippetsAppSchema:
    """Tests for ``GET /api/apps/snippets/schema``."""

    async def test_returns_static_plugin_schema(self, test_client):
        """The static plugin schema declares no forms but a populated list view."""
        response = test_client.get(f"{API_BASE}/schema")

        assert response.status_code == status.HTTP_200_OK
        assert "application/json" in response.headers["content-type"]
        body = response.json()
        assert body["name"] == "snippets"
        assert body["forms"] == []
        column_keys = [column["key"] for column in body["list_view"]["columns"]]
        assert "filename" in column_keys
        assert "isApproved" in column_keys


@pytest.mark.asyncio
class TestSnippetsApiSnippetFilenameQueryParam:
    """Contract tests for the required ``snippet_filename`` query parameter."""

    @pytest.mark.parametrize(
        "path",
        [
            "/snippet/schema",
            "/snippet/preview",
        ],
    )
    async def test_returns_422_when_snippet_filename_missing(self, test_client, path):
        """Requests without ``snippet_filename`` are rejected before snippet lookup."""
        response = test_client.get(f"{API_BASE}{path}")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        detail = response.json()["detail"]
        assert any(
            err.get("loc") == ["query", "snippet_filename"]
            for err in detail
            if isinstance(err, dict)
        )

    @pytest.mark.parametrize(
        "bad_filename",
        [
            "..evil.sh",
            ".hidden.sh",
            "no-extension",
        ],
    )
    async def test_traversal_or_unsafe_filename_returns_400(
        self, test_client, bad_filename
    ):
        """Filenames with traversal sequences or invalid forms return 400."""
        response = test_client.get(
            f"{API_BASE}/snippet/schema",
            params={"snippet_filename": bad_filename},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
class TestSnippetsApiPerSnippetSchema:
    """Tests for ``GET /api/apps/snippets/snippet/schema``."""

    async def test_returns_404_for_unknown_snippet(self, test_client):
        """A missing snippet filename surfaces as a 404."""
        response = test_client.get(
            f"{API_BASE}/snippet/schema",
            params={"snippet_filename": "missing.sh"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_returns_per_snippet_schema_with_preview_field(
        self, test_client, create_snippet
    ):
        """The schema exposes a dedicated post-submit ScriptPreview section."""
        snippet = await create_snippet("hello.sh", approved=True)

        response = test_client.get(
            f"{API_BASE}/snippet/schema",
            params={"snippet_filename": snippet.filename},
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["name"] == "snippets"
        execution_section = next(
            section for section in body["forms"] if section["title"] == "Execution"
        )
        field_types = {field["type"] for field in execution_section["fields"]}
        assert "host" in field_types
        assert "script_preview" not in field_types
        preview_section = next(
            section for section in body["forms"] if section["title"] == "Script preview"
        )
        assert preview_section["collapsible"] is True
        assert preview_section["collapsed_by_default"] is True
        assert preview_section["render_after_submit"] is True
        preview_field = next(
            field
            for field in preview_section["fields"]
            if field["type"] == "script_preview"
        )
        assert preview_field["label"] == "Snippet file"
        assert preview_field["endpoint_url"] == (
            f"/apps/snippets/snippet/preview?snippet_filename={snippet.filename}"
        )


@pytest.mark.asyncio
class TestSnippetsApiScriptPreview:
    """Tests for ``GET /api/apps/snippets/{snippet_filename}/preview``."""

    async def test_returns_preview_with_language_hint(
        self, test_client, create_snippet
    ):
        """The preview response carries content, truncation flag, and a language hint."""
        snippet = await create_snippet("hello.sh", approved=True)

        response = test_client.get(
            f"{API_BASE}/snippet/preview",
            params={"snippet_filename": snippet.filename},
        )

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
                f"{API_BASE}/snippet/preview",
                params={"snippet_filename": snippet.filename},
            )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_old_script_preview_route_returns_404(
        self, test_client, create_snippet
    ):
        """The removed script-preview path is not kept as a compatibility alias."""
        snippet = await create_snippet("hello.sh", approved=True)

        response = test_client.get(f"{API_BASE}/{snippet.filename}/script-preview")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_legacy_path_segment_route_returns_404(
        self, test_client, create_snippet
    ):
        """The old ``/{filename}/preview`` path returns 404; preview lives under ``/snippet/preview``."""
        snippet = await create_snippet("hello.sh", approved=True)

        response = test_client.get(f"{API_BASE}/{snippet.filename}/preview")

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
class TestSnippetsApiDownload:
    """Tests for ``GET /api/apps/snippets/{snippet_filename}/download``."""

    async def test_returns_raw_file_with_attachment_headers(
        self, test_client, create_snippet, snippets_dir
    ):
        """The endpoint streams the on-disk bytes verbatim with attachment headers."""
        snippet = await create_snippet("hello.sh", approved=True)
        on_disk = (snippets_dir / snippet.filename).read_bytes()

        response = test_client.get(
            f"{API_BASE}/snippet/download",
            params={"snippet_filename": snippet.filename},
        )

        assert response.status_code == status.HTTP_200_OK
        # ``FileResponse`` sets the disposition with a quoted filename.
        disposition = response.headers["content-disposition"]
        assert "attachment" in disposition
        assert f'filename="{snippet.filename}"' in disposition
        assert response.content == on_disk

    async def test_returns_401_for_unauthenticated_caller(
        self, api_unauthenticated_client, create_snippet
    ):
        """Anonymous callers are rejected with a structured 401, not a redirect."""
        snippet = await create_snippet("hello.sh", approved=True)

        response = api_unauthenticated_client.get(
            f"{API_BASE}/snippet/download",
            params={"snippet_filename": snippet.filename},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_returns_404_for_unknown_snippet(self, test_client):
        """A missing DB row surfaces as a 404."""
        response = test_client.get(
            f"{API_BASE}/snippet/download",
            params={"snippet_filename": "missing.sh"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_returns_404_when_file_missing_on_disk(
        self, test_client, create_snippet, snippets_dir
    ):
        """A persisted row whose file was deleted on disk surfaces as 404."""
        snippet = await create_snippet("hello.sh", approved=True)
        (snippets_dir / snippet.filename).unlink()

        response = test_client.get(
            f"{API_BASE}/snippet/download",
            params={"snippet_filename": snippet.filename},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
class TestSnippetsApiHistory:
    """Tests for ``GET /api/apps/snippets/{snippet_filename}/history``."""

    async def test_history_passes_filter_through(
        self, test_client, mock_task_api_dep, create_snippet
    ):
        """History endpoint filters by snippet filename and returns the upstream payload verbatim."""
        snippet = await create_snippet("hello.sh", approved=True)
        history_id = 42
        upstream_payload = {
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
        }
        mock_task_api_dep.get = AsyncMock(return_value=upstream_payload)

        response = test_client.get(
            f"{API_BASE}/snippet/history",
            params={"snippet_filename": snippet.filename},
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body == upstream_payload
        first_call = mock_task_api_dep.get.call_args_list[0]
        assert first_call.kwargs["params"] == {"snippet_filename": snippet.filename}
        # The endpoint must not fan out a per-row files lookup anymore.
        assert mock_task_api_dep.get.call_count == 1


@pytest.mark.asyncio
class TestSnippetsApiExecute:
    """Tests for ``POST /api/apps/snippets/{snippet_filename}/execute``."""

    async def test_returns_403_when_snippet_not_approved(
        self, test_client, mock_task_api_dep, create_snippet
    ):
        """An unapproved snippet's execute endpoint returns 403, not a redirect."""
        snippet = await create_snippet("hello.sh", approved=False)

        response = test_client.post(
            f"{API_BASE}/snippet/execute",
            params={"snippet_filename": snippet.filename},
            json={"executor_host": "host1"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_task_api_dep.post.assert_not_called()

    async def test_returns_404_for_unknown_snippet(
        self, test_client, mock_task_api_dep
    ):
        """Executing an unknown snippet returns 404 without calling the tasks API."""
        response = test_client.post(
            f"{API_BASE}/snippet/execute",
            params={"snippet_filename": "missing.sh"},
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
            f"{API_BASE}/snippet/execute",
            params={"snippet_filename": snippet.filename},
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

    async def test_rejects_submitted_value_for_gated_hidden_param(
        self, test_client, mock_task_api_dep, create_snippet, session
    ):
        """A value for a gated-hidden param is rejected (422); no task dispatched.

        ``start`` is hidden when ``list`` is truthy (``visible_when_not``), so a
        direct POST that supplies ``start`` while ``list`` is on must be
        server-rejected — the client would have dropped it.
        """
        snippet = await _seed_gated_snippet(
            create_snippet,
            session,
            [
                {"name": "list", "type": "bool", "label": "List"},
                {
                    "name": "start",
                    "type": "str",
                    "label": "Start",
                    "visible_when_not": "list",
                },
            ],
        )

        response = test_client.post(
            f"{API_BASE}/snippet/execute",
            params={"snippet_filename": snippet.filename},
            json={"executor_host": "host1", "args": {"list": True, "start": "2020"}},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()

    async def test_allows_value_when_gate_not_fired(
        self, test_client, mock_task_api_dep, create_snippet, session
    ):
        """When the gate does not fire, the submitted value executes normally."""
        snippet = await _seed_gated_snippet(
            create_snippet,
            session,
            [
                {"name": "list", "type": "bool", "label": "List"},
                {
                    "name": "start",
                    "type": "str",
                    "label": "Start",
                    "visible_when_not": "list",
                },
            ],
        )
        mock_task_api_dep.post = AsyncMock(return_value={"id": 7})

        response = test_client.post(
            f"{API_BASE}/snippet/execute",
            params={"snippet_filename": snippet.filename},
            json={"executor_host": "host1", "args": {"list": False, "start": "2020"}},
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert mock_task_api_dep.post.called

    async def test_allows_gated_param_omitted(
        self, test_client, mock_task_api_dep, create_snippet, session
    ):
        """A hidden param the client dropped (absent) executes without rejection."""
        snippet = await _seed_gated_snippet(
            create_snippet,
            session,
            [
                {"name": "list", "type": "bool", "label": "List"},
                {
                    "name": "start",
                    "type": "str",
                    "label": "Start",
                    "visible_when_not": "list",
                },
            ],
        )
        mock_task_api_dep.post = AsyncMock(return_value={"id": 8})

        response = test_client.post(
            f"{API_BASE}/snippet/execute",
            params={"snippet_filename": snippet.filename},
            json={"executor_host": "host1", "args": {"list": True}},
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert mock_task_api_dep.post.called

    async def test_rejects_on_equals_gate(
        self, test_client, mock_task_api_dep, create_snippet, session
    ):
        """An equality-based forbidden gate rejects a submitted hidden value."""
        snippet = await _seed_gated_snippet(
            create_snippet,
            session,
            [
                {
                    "name": "mode",
                    "type": "str",
                    "label": "Mode",
                    "choices": ["basic", "advanced"],
                },
                {
                    "name": "region",
                    "type": "str",
                    "label": "Region",
                    "visible_when_not": {"parameter": "mode", "equals": "advanced"},
                },
            ],
        )

        response = test_client.post(
            f"{API_BASE}/snippet/execute",
            params={"snippet_filename": snippet.filename},
            json={
                "executor_host": "host1",
                "args": {"mode": "advanced", "region": "us"},
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()

    async def test_gateless_snippet_executes_unchanged(
        self, test_client, mock_task_api_dep, create_snippet, session
    ):
        """A snippet with params but no visibility rule executes as before."""
        snippet = await _seed_gated_snippet(
            create_snippet,
            session,
            [{"name": "name", "type": "str", "label": "Name"}],
            filename="plain.sh",
        )
        mock_task_api_dep.post = AsyncMock(return_value={"id": 9})

        response = test_client.post(
            f"{API_BASE}/snippet/execute",
            params={"snippet_filename": snippet.filename},
            json={"executor_host": "host1", "args": {"name": "x"}},
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert mock_task_api_dep.post.called

    async def test_multiple_gated_fields_report_all_failures(
        self, test_client, mock_task_api_dep, create_snippet, session
    ):
        """All fired gates surface in the 422 detail; nothing is dispatched."""
        snippet = await _seed_gated_snippet(
            create_snippet,
            session,
            [
                {"name": "list", "type": "bool", "label": "List"},
                {
                    "name": "start",
                    "type": "str",
                    "label": "Start",
                    "visible_when_not": "list",
                },
                {
                    "name": "end",
                    "type": "str",
                    "label": "End",
                    "visible_when_not": "list",
                },
            ],
        )

        response = test_client.post(
            f"{API_BASE}/snippet/execute",
            params={"snippet_filename": snippet.filename},
            json={
                "executor_host": "host1",
                "args": {"list": True, "start": "a", "end": "b"},
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        detail = response.json()["detail"]
        expected_failures = 2
        assert isinstance(detail, list)
        assert len(detail) == expected_failures
        mock_task_api_dep.post.assert_not_called()

    async def test_gated_bool_false_executes(
        self, test_client, mock_task_api_dep, create_snippet, session
    ):
        """A gated bool submitted ``false`` is absent, so execution proceeds.

        Guards against a false-positive rejection: the forbidden gate must treat
        an explicit ``False`` toggle as unset, matching the client renderer.
        """
        snippet = await _seed_gated_snippet(
            create_snippet,
            session,
            [
                {"name": "list", "type": "bool", "label": "List"},
                {
                    "name": "flag",
                    "type": "bool",
                    "label": "Flag",
                    "visible_when_not": "list",
                },
            ],
        )
        mock_task_api_dep.post = AsyncMock(return_value={"id": 11})

        response = test_client.post(
            f"{API_BASE}/snippet/execute",
            params={"snippet_filename": snippet.filename},
            json={"executor_host": "host1", "args": {"list": True, "flag": False}},
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert mock_task_api_dep.post.called


@pytest.mark.asyncio
class TestSnippetsApiPutApproval:
    """Tests for ``PUT /api/apps/snippets/{filename}/approval``."""

    async def test_approves_unapproved_snippet(
        self, api_admin_client, create_snippet, admin_user, session: AsyncSession
    ):
        """An unapproved snippet flips to approved with admin attribution."""
        snippet = await create_snippet("hello.sh", approved=False)

        response = api_admin_client.put(
            f"{API_BASE}/snippet/approval",
            params={"snippet_filename": snippet.filename},
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["filename"] == snippet.filename
        assert body["is_approved"] is True
        assert body["approved_at"] is not None
        assert body["updated_by"] == str(admin_user.id)
        assert f"Approved by {admin_user.username}" in body["reason"]

        await session.refresh(snippet)
        assert snippet.is_approved is True

    async def test_idempotent_re_approval_does_not_overwrite_approved_at(
        self, api_admin_client, create_snippet, session: AsyncSession
    ):
        """Re-approving an already-approved snippet returns 200 and is a no-op."""
        snippet = await create_snippet("hello.sh", approved=True)
        original_approved_at = snippet.approved_at
        original_updated_by = snippet.updated_by
        original_reason = snippet.reason

        response = api_admin_client.put(
            f"{API_BASE}/snippet/approval",
            params={"snippet_filename": snippet.filename},
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["is_approved"] is True

        await session.refresh(snippet)
        assert snippet.approved_at == original_approved_at
        assert snippet.updated_by == original_updated_by
        assert snippet.reason == original_reason

    async def test_non_admin_forbidden(self, api_non_admin_client, create_snippet):
        """A non-admin caller cannot approve."""
        snippet = await create_snippet("hello.sh", approved=False)

        response = api_non_admin_client.put(
            f"{API_BASE}/snippet/approval",
            params={"snippet_filename": snippet.filename},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_unauthenticated_unauthorized(
        self, api_unauthenticated_client, create_snippet
    ):
        """No auth → 401, not a 303 redirect."""
        snippet = await create_snippet("hello.sh", approved=False)

        response = api_unauthenticated_client.put(
            f"{API_BASE}/snippet/approval",
            params={"snippet_filename": snippet.filename},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_missing_snippet_returns_404(self, api_admin_client):
        """An unknown filename surfaces as 404."""
        response = api_admin_client.put(
            f"{API_BASE}/snippet/approval",
            params={"snippet_filename": "missing.sh"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.parametrize(
        "bad_filename",
        [
            "..evil.sh",
            ".hidden.sh",
            "no-extension",
        ],
    )
    async def test_traversal_or_unsafe_filename_returns_400(
        self, api_admin_client, bad_filename
    ):
        """Filenames with traversal sequences or invalid forms return 400."""
        response = api_admin_client.put(
            f"{API_BASE}/snippet/approval",
            params={"snippet_filename": bad_filename},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
class TestSnippetsApiDeleteApproval:
    """Tests for ``DELETE /api/apps/snippets/{filename}/approval``."""

    async def test_removes_approval(
        self, api_admin_client, create_snippet, admin_user, session: AsyncSession
    ):
        """An approved snippet flips back to unapproved with admin attribution."""
        snippet = await create_snippet("hello.sh", approved=True)

        response = api_admin_client.delete(
            f"{API_BASE}/snippet/approval",
            params={"snippet_filename": snippet.filename},
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert response.content == b""

        await session.refresh(snippet)
        assert snippet.is_approved is False
        assert snippet.updated_by == str(admin_user.id)
        assert f"Approval removed by {admin_user.username}" in snippet.reason

    async def test_idempotent_when_never_approved(
        self, api_admin_client, create_snippet, session: AsyncSession
    ):
        """Removing an approval that doesn't exist is a no-op 204."""
        snippet = await create_snippet("hello.sh", approved=False)
        original_updated_by = snippet.updated_by
        original_reason = snippet.reason

        response = api_admin_client.delete(
            f"{API_BASE}/snippet/approval",
            params={"snippet_filename": snippet.filename},
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        await session.refresh(snippet)
        assert snippet.updated_by == original_updated_by
        assert snippet.reason == original_reason

    async def test_non_admin_forbidden(self, api_non_admin_client, create_snippet):
        """A non-admin caller cannot remove approval."""
        snippet = await create_snippet("hello.sh", approved=True)

        response = api_non_admin_client.delete(
            f"{API_BASE}/snippet/approval",
            params={"snippet_filename": snippet.filename},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_missing_snippet_returns_404(self, api_admin_client):
        """An unknown filename surfaces as 404 (distinct from the 204 idempotent path)."""
        response = api_admin_client.delete(
            f"{API_BASE}/snippet/approval",
            params={"snippet_filename": "missing.sh"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.parametrize(
        "bad_filename",
        [
            "..evil.sh",
            ".hidden.sh",
            "no-extension",
        ],
    )
    async def test_traversal_or_unsafe_filename_returns_400(
        self, api_admin_client, bad_filename
    ):
        """Filenames with traversal sequences or invalid forms return 400."""
        response = api_admin_client.delete(
            f"{API_BASE}/snippet/approval",
            params={"snippet_filename": bad_filename},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_unauthenticated_unauthorized(
        self, api_unauthenticated_client, create_snippet
    ):
        """No auth → 401."""
        snippet = await create_snippet("hello.sh", approved=True)

        response = api_unauthenticated_client.delete(
            f"{API_BASE}/snippet/approval",
            params={"snippet_filename": snippet.filename},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
class TestSnippetsApiPatchApprovals:
    """Tests for ``PATCH /api/apps/snippets/approvals``."""

    URL = f"{API_BASE}/approvals"

    async def test_happy_path(self, api_admin_client, create_snippet):
        """All-unapproved input flips both rows and reports counts."""
        await create_snippet("a.sh", approved=False)
        await create_snippet("b.sh", approved=False)

        response = api_admin_client.patch(
            self.URL, json={"filenames": ["a.sh", "b.sh"]}
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert sorted(body["approved"]) == ["a.sh", "b.sh"]
        assert body["skipped_already_approved"] == []
        expected_count = 2
        assert body["count"] == expected_count

    async def test_soft_skip_already_approved(self, api_admin_client, create_snippet):
        """Already-approved filenames are reported as skipped, not as errors."""
        await create_snippet("a.sh", approved=False)
        await create_snippet("b.sh", approved=True)

        response = api_admin_client.patch(
            self.URL, json={"filenames": ["a.sh", "b.sh"]}
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["approved"] == ["a.sh"]
        assert body["skipped_already_approved"] == ["b.sh"]
        assert body["count"] == 1

    async def test_all_already_approved(self, api_admin_client, create_snippet):
        """All-approved input is a 200 with empty ``approved`` and full skip list."""
        await create_snippet("a.sh", approved=True)
        await create_snippet("b.sh", approved=True)

        response = api_admin_client.patch(
            self.URL, json={"filenames": ["a.sh", "b.sh"]}
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["approved"] == []
        assert sorted(body["skipped_already_approved"]) == ["a.sh", "b.sh"]
        assert body["count"] == 0

    async def test_missing_in_db_aborts_with_400(
        self, api_admin_client, create_snippet, session: AsyncSession
    ):
        """A missing-in-db filename rejects the whole batch and writes nothing."""
        snippet = await create_snippet("a.sh", approved=False)

        response = api_admin_client.patch(
            self.URL, json={"filenames": ["a.sh", "ghost.sh"]}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()["detail"]
        assert body["missing_in_db"] == ["ghost.sh"]
        assert body["missing_on_disk"] == []

        await session.refresh(snippet)
        assert snippet.is_approved is False

    async def test_missing_on_disk_aborts_with_400(
        self, api_admin_client, create_snippet, session: AsyncSession
    ):
        """A missing-on-disk filename rejects the whole batch."""
        good = await create_snippet("good.sh", approved=False)
        await create_snippet("bad.sh", approved=False, create_file=False)

        response = api_admin_client.patch(
            self.URL, json={"filenames": ["good.sh", "bad.sh"]}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()["detail"]
        assert body["missing_in_db"] == []
        assert body["missing_on_disk"] == ["bad.sh"]

        await session.refresh(good)
        assert good.is_approved is False

    async def test_both_error_categories_reported_together(
        self, api_admin_client, create_snippet
    ):
        """Both error arrays populate when both conditions apply in one request."""
        await create_snippet("good.sh", approved=False)
        await create_snippet("bad.sh", approved=False, create_file=False)

        response = api_admin_client.patch(
            self.URL, json={"filenames": ["good.sh", "bad.sh", "ghost.sh"]}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()["detail"]
        assert body["missing_in_db"] == ["ghost.sh"]
        assert body["missing_on_disk"] == ["bad.sh"]

    async def test_non_admin_forbidden(self, api_non_admin_client, create_snippet):
        """A non-admin caller cannot batch-approve."""
        await create_snippet("a.sh", approved=False)

        response = api_non_admin_client.patch(self.URL, json={"filenames": ["a.sh"]})

        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_unauthenticated_unauthorized(
        self, api_unauthenticated_client, create_snippet
    ):
        """No auth → 401."""
        await create_snippet("a.sh", approved=False)

        response = api_unauthenticated_client.patch(
            self.URL, json={"filenames": ["a.sh"]}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_empty_filenames_returns_422(self, api_admin_client):
        """Empty ``filenames`` is a 422 validation error from Pydantic."""
        response = api_admin_client.patch(self.URL, json={"filenames": []})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_missing_filenames_returns_422(self, api_admin_client):
        """Missing ``filenames`` field is a 422 (regression for the body-parsing quirk)."""
        response = api_admin_client.patch(self.URL, json={})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        # Confirm the error is about the field, not a Form-parsing 400.
        body = response.json()
        assert any(
            "filenames" in str(err.get("loc", "")) for err in body.get("detail", [])
        )

    async def test_non_list_filenames_returns_422(self, api_admin_client):
        """A non-list ``filenames`` value is a 422."""
        response = api_admin_client.patch(self.URL, json={"filenames": "a.sh"})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @pytest.mark.parametrize(
        "bad_filename",
        [
            "../evil.sh",
            "../../etc/passwd",
            ".hidden.sh",
            "sub//double.sh",
            "no-extension",
        ],
    )
    async def test_traversal_or_unsafe_filename_in_batch_returns_400(
        self, api_admin_client, bad_filename
    ):
        """Traversal and invalid filenames in the batch body are rejected with 400.

        Unsafe filenames have no DB row, so the existence precheck returns them
        in ``missing_in_db`` and raises 400.
        """
        response = api_admin_client.patch(self.URL, json={"filenames": [bad_filename]})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        detail = response.json().get("detail", {})
        assert bad_filename in detail.get("missing_in_db", [])

    async def test_duplicate_filenames_silently_deduped(
        self, api_admin_client, create_snippet
    ):
        """Duplicates in ``filenames`` are silently deduped by ``UniqueList``."""
        await create_snippet("a.sh", approved=False)

        response = api_admin_client.patch(
            self.URL, json={"filenames": ["a.sh", "a.sh"]}
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["approved"] == ["a.sh"]
        assert body["count"] == 1

    async def test_atomic_concurrency_uses_db_filter(
        self, api_admin_client, create_snippet, mocker
    ):
        """The endpoint relies on the DB-level ``approved_at IS NULL`` filter.

        Mirrors the Jinja2 calibration test (``test_routes.py``) by
        mocking ``update_where`` to return only one filename for a 2-row
        request — simulating a concurrent admin who approved the second
        row between our SELECT and our UPDATE — and asserting the
        response derives ``skipped_already_approved`` from the real
        UPDATE result.
        """
        await create_snippet("a.sh", approved=False)
        await create_snippet("b.sh", approved=False)

        # With ``returning=["filename"]``, ``update_where`` returns a list of
        # the actually-updated filenames (one column → scalars()).
        mocker.patch.object(
            SnippetManager,
            "update_where",
            new=AsyncMock(return_value=["a.sh"]),
        )

        response = api_admin_client.patch(
            self.URL, json={"filenames": ["a.sh", "b.sh"]}
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["approved"] == ["a.sh"]
        assert body["skipped_already_approved"] == ["b.sh"]
        assert body["count"] == 1


@pytest.mark.asyncio
class TestSnippetsApiCapabilities:
    """Tests for ``GET /api/apps/snippets/capabilities``."""

    URL = f"{API_BASE}/capabilities"

    @pytest.mark.parametrize("enable_value", [True, False])
    async def test_returns_capability_flag(
        self, api_admin_client, enable_manual_sync, enable_value
    ):
        """Capabilities surface the ENABLE_MANUAL_SYNC setting."""
        enable_manual_sync(value=enable_value)

        response = api_admin_client.get(self.URL)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"manual_sync_enabled": enable_value}
        # Validate the response body fits the declared model contract.
        SnippetsCapabilitiesResponse.model_validate(response.json())

    async def test_non_admin_can_read(self, api_non_admin_client, enable_manual_sync):
        """Any authenticated user reads capabilities; no admin gate."""
        enable_manual_sync(value=True)

        response = api_non_admin_client.get(self.URL)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"manual_sync_enabled": True}

    async def test_unauthenticated_returns_401(
        self, api_unauthenticated_client, enable_manual_sync
    ):
        """No auth → 401, regardless of the underlying flag."""
        enable_manual_sync(value=True)

        response = api_unauthenticated_client.get(self.URL)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
class TestSnippetsApiRefresh:
    """Tests for ``POST /api/apps/snippets/refresh``."""

    URL = f"{API_BASE}/refresh"

    async def test_admin_with_manual_sync_enabled_returns_200(
        self, api_admin_client, enable_manual_sync, mocker
    ):
        """Admin happy path: 200 with ISO ``refreshed_at`` and one call."""
        enable_manual_sync(value=True)
        update_mock = mocker.patch.object(
            snippets_extra_routes,
            "update_snippets",
            new=AsyncMock(return_value=None),
        )

        response = api_admin_client.post(self.URL)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert "refreshed_at" in body
        # ISO 8601 round-trip: parsing must succeed.
        parsed = datetime.fromisoformat(body["refreshed_at"])
        assert parsed.tzinfo is not None
        # Validate body fits the declared model contract.
        RefreshResponse.model_validate(body)
        update_mock.assert_awaited_once()

    async def test_refresh_registers_drain_counter(
        self, api_admin_client, enable_manual_sync, mocker
    ):
        """The refresh wraps the sync in ``track_app_task`` for the snippets app."""
        enable_manual_sync(value=True)
        mocker.patch.object(
            snippets_extra_routes, "update_snippets", new=AsyncMock(return_value=None)
        )
        spy = mocker.spy(snippets_extra_routes, "track_app_task")

        response = api_admin_client.post(self.URL)

        assert response.status_code == status.HTTP_200_OK
        spy.assert_called_once()
        assert spy.call_args.args[1] == "snippets"

    async def test_admin_with_manual_sync_disabled_returns_403(
        self, api_admin_client, enable_manual_sync, mocker
    ):
        """Disabled deployment: 403 with structured detail; no work done."""
        enable_manual_sync(value=False)
        update_mock = mocker.patch.object(
            snippets_extra_routes,
            "update_snippets",
            new=AsyncMock(return_value=None),
        )

        response = api_admin_client.post(self.URL)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json() == {
            "detail": "Manual snippet sync is disabled in this deployment."
        }
        update_mock.assert_not_called()

    async def test_non_admin_returns_403_even_when_enabled(
        self, api_non_admin_client, enable_manual_sync, mocker
    ):
        """Non-admin caller: 403; no refresh work done."""
        enable_manual_sync(value=True)
        update_mock = mocker.patch.object(
            snippets_extra_routes,
            "update_snippets",
            new=AsyncMock(return_value=None),
        )

        response = api_non_admin_client.post(self.URL)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        update_mock.assert_not_called()

    async def test_unauthenticated_returns_401(
        self, api_unauthenticated_client, enable_manual_sync, mocker
    ):
        """No auth: 401; no refresh work done."""
        enable_manual_sync(value=True)
        update_mock = mocker.patch.object(
            snippets_extra_routes,
            "update_snippets",
            new=AsyncMock(return_value=None),
        )

        response = api_unauthenticated_client.post(self.URL)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        update_mock.assert_not_called()

    async def test_cookie_only_admin_mutation_rejected_by_bearer_gate(
        self, api_admin_client_no_bearer, enable_manual_sync, mocker
    ):
        """Cookie-auth admin POST without Bearer header is rejected with 401.

        The framework Bearer gate on ``/api/apps/*`` must fire before the
        route's business logic, so the refresh helper is never invoked.
        """
        enable_manual_sync(value=True)
        update_mock = mocker.patch.object(
            snippets_extra_routes,
            "update_snippets",
            new=AsyncMock(return_value=None),
        )

        response = api_admin_client_no_bearer.post(self.URL)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["detail"] == BEARER_REQUIRED_DETAIL
        update_mock.assert_not_called()

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("PUT", "/api/apps/snippets/snippet/approval"),
            ("DELETE", "/api/apps/snippets/snippet/approval"),
            ("PATCH", "/api/apps/snippets/approvals"),
        ],
    )
    async def test_cookie_only_approval_mutations_are_gate_rejected(
        self,
        api_admin_client_no_bearer,
        method: str,
        path: str,
    ) -> None:
        """The full snippets approval mutation matrix 401s under cookie-only auth.

        ``PUT/DELETE/PATCH`` on the approval surface share the framework gate;
        each must return the exact ``BEARER_REQUIRED_DETAIL`` body, with the
        gate firing before any DB write.
        """
        kwargs = {
            "params": {"snippet_filename": "hello.sh"},
            "json": {"filenames": ["hello.sh"]},
        }
        response = api_admin_client_no_bearer.request(method, path, **kwargs)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["detail"] == BEARER_REQUIRED_DETAIL

    async def test_dependency_order_auth_runs_before_config_gate(
        self, api_unauthenticated_client, enable_manual_sync
    ):
        """Unauth probe with flag True → 401, never the disabled-detail 403.

        Prevents leaking deployment-flag state to anonymous callers via the
        403-vs-401 differential.
        """
        enable_manual_sync(value=False)

        response = api_unauthenticated_client.post(self.URL)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        # Detail must NOT echo the gate-state message.
        body = response.json()
        assert body.get("detail") != (
            "Manual snippet sync is disabled in this deployment."
        )

    async def test_update_snippets_failure_propagates(
        self, api_admin_client, enable_manual_sync, mocker
    ):
        """Backend errors are not silently swallowed (500 to caller)."""
        enable_manual_sync(value=True)
        mocker.patch.object(
            snippets_extra_routes,
            "update_snippets",
            new=AsyncMock(side_effect=RuntimeError("disk walk failed")),
        )

        response = api_admin_client.post(self.URL)

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


@pytest.mark.asyncio
class TestSnippetsApiNestedFilenameContract:
    """Tests for per-snippet routes when ``snippet_filename`` contains ``/`` (query-param contract)."""

    NESTED_FILENAME = "diag/slow-query.sh"

    async def test_get_per_snippet_schema(self, test_client, create_snippet):
        """The per-snippet schema embeds a preview URL with ``/`` encoded in the query string."""
        snippet = await create_snippet(self.NESTED_FILENAME, approved=True)

        response = test_client.get(
            f"{API_BASE}/snippet/schema",
            params={"snippet_filename": snippet.filename},
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        preview_section = next(
            section for section in body["forms"] if section["title"] == "Script preview"
        )
        preview_field = next(
            field
            for field in preview_section["fields"]
            if field["type"] == "script_preview"
        )
        # The baked URL must round-trip through the same builder shape so a
        # client following it lands on the right preview endpoint.
        assert preview_field["endpoint_url"] == (
            "/apps/snippets/snippet/preview?snippet_filename=diag%2Fslow-query.sh"
        )

    async def test_get_script_preview(self, test_client, create_snippet):
        """The preview endpoint returns 200 and UTF-8 body text for a nested-path snippet key."""
        snippet = await create_snippet(self.NESTED_FILENAME, approved=True)

        response = test_client.get(
            f"{API_BASE}/snippet/preview",
            params={"snippet_filename": snippet.filename},
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert "echo hi" in body["content"]

    async def test_get_download(self, test_client, create_snippet, snippets_dir):
        """The download endpoint streams on-disk bytes and quotes the full relative filename in ``Content-Disposition``."""
        snippet = await create_snippet(self.NESTED_FILENAME, approved=True)
        on_disk = (snippets_dir / snippet.filename).read_bytes()

        response = test_client.get(
            f"{API_BASE}/snippet/download",
            params={"snippet_filename": snippet.filename},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.content == on_disk
        disposition = response.headers["content-disposition"]
        # ``FileResponse`` keeps the raw filename including the ``/``.
        assert f'filename="{snippet.filename}"' in disposition

    async def test_get_history(self, test_client, mock_task_api_dep, create_snippet):
        """History endpoint passes the nested ``snippet_filename`` through to the tasks API filter unchanged."""
        snippet = await create_snippet(self.NESTED_FILENAME, approved=True)
        mock_task_api_dep.get = AsyncMock(
            return_value={"items": [], "total": 0, "offset": 0, "limit": 50}
        )

        response = test_client.get(
            f"{API_BASE}/snippet/history",
            params={"snippet_filename": snippet.filename},
        )

        assert response.status_code == status.HTTP_200_OK
        call = mock_task_api_dep.get.call_args_list[0]
        assert call.kwargs["params"] == {"snippet_filename": snippet.filename}

    async def test_post_execute(self, test_client, mock_task_api_dep, create_snippet):
        """Successful execution returns 201 and posts task ``meta`` with the nested snippet filename."""
        snippet = await create_snippet(self.NESTED_FILENAME, approved=True)
        mock_task_api_dep.post = AsyncMock(return_value={"id": 7})

        response = test_client.post(
            f"{API_BASE}/snippet/execute",
            params={"snippet_filename": snippet.filename},
            json={"executor_host": "host1", "args": {}},
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["snippet_filename"] == snippet.filename
        meta = mock_task_api_dep.post.call_args.kwargs["json"]["meta"]
        assert meta["_snippet_filename"] == snippet.filename

    async def test_put_approval(
        self, api_admin_client, create_snippet, session: AsyncSession
    ):
        """PUT approval flips a nested-path snippet to approved and persists it."""
        snippet = await create_snippet(self.NESTED_FILENAME, approved=False)

        response = api_admin_client.put(
            f"{API_BASE}/snippet/approval",
            params={"snippet_filename": snippet.filename},
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["filename"] == snippet.filename
        assert body["is_approved"] is True
        await session.refresh(snippet)
        assert snippet.is_approved is True

    async def test_delete_approval(
        self, api_admin_client, create_snippet, session: AsyncSession
    ):
        """DELETE approval clears approval for a nested-path snippet (204 + DB state)."""
        snippet = await create_snippet(self.NESTED_FILENAME, approved=True)

        response = api_admin_client.delete(
            f"{API_BASE}/snippet/approval",
            params={"snippet_filename": snippet.filename},
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        await session.refresh(snippet)
        assert snippet.is_approved is False

    async def test_legacy_path_shape_does_not_match(self, test_client, create_snippet):
        """Legacy ``GET /{snippet_filename}/preview`` with a nested key returns 404 — no compatibility alias."""
        snippet = await create_snippet(self.NESTED_FILENAME, approved=True)

        response = test_client.get(f"{API_BASE}/{snippet.filename}/preview")

        assert response.status_code == status.HTTP_404_NOT_FOUND


# Override the module-level test_client fixture so it uses the same in-memory
# session as the other snippet plugin tests; otherwise the snippets table is
# absent on the default global session.


@pytest.fixture
def test_client(regular_user, session, snippets_dir):
    """Return a TestClient sharing the in-memory session and snippets dir."""
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user
    sep_app.dependency_overrides[get_api_authenticated_user] = lambda: regular_user
    sep_app.dependency_overrides[get_session] = lambda: session
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}
