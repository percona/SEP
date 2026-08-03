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

"""Tests for the snippets plugin routes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth.providers.casdoor.models import CasdoorUser
from app.sep.apps.framework.deprecation import DeprecatedJinja2Route
from app.sep.apps.snippets.routes import router as snippets_jinja_router
from app.sep.config import sep_settings
from app.sep.deps import (
    get_current_user,
    get_session,
)
from app.sep.main import sep_app
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models.snippet import EXECUTOR_HOSTS_INPUT_NAME

_BATCH_APPROVE_URL = "/snippets/approve-batch"
_INDEX_URL_PATH = "/snippets/"
_COMPLETED_TASKS_PARTIAL = "tasks/partials/completed-tasks.html.j2"
_EXECUTE_URL = "/snippets/execute"


async def _seed_gated_snippet(create_snippet, session, parameters, *, filename):
    """Seed an approved snippet whose meta declares ``parameters`` (persisted).

    The execute route reloads the snippet from the DB by filename, so the gated
    parameter metadata must be persisted and the ``validated_parameters`` cache
    dropped so the new meta is re-validated.
    """
    snippet = await create_snippet(filename, approved=True)
    snippet.meta = {**snippet.meta, "parameters": parameters}
    snippet.__dict__.pop("validated_parameters", None)
    await SnippetManager.save(session, snippet, flag_modified_fields=["meta"])
    return snippet


_GATED_PARAMS = [
    {"name": "list", "type": "bool", "label": "List"},
    {"name": "start", "type": "str", "label": "Start", "visible_when_not": "list"},
]


class TestSnippetsApproveBatch:
    """Test the POST /snippets/approve-batch endpoint."""

    @pytest.mark.asyncio
    async def test_success_approves_all_unapproved(
        self,
        admin_client: TestClient,
        session: AsyncSession,
        create_snippet,
        admin_user: CasdoorUser,
        mocker: MockerFixture,
    ):
        """Assert a clean batch flips every row to approved and flashes success."""
        for name in ("a.sh", "b.sh", "c.sh"):
            await create_snippet(name)
        success = mocker.patch("app.sep.apps.snippets.routes.messages.success")
        error = mocker.patch("app.sep.apps.snippets.routes.messages.error")

        response = admin_client.post(
            _BATCH_APPROVE_URL,
            data={"filenames": ["a.sh", "b.sh", "c.sh"]},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"].endswith(_INDEX_URL_PATH)
        error.assert_not_called()
        success.assert_called_once()
        flashed = success.call_args.args[1]
        assert flashed == "3 snippet(s) approved"
        approved = await SnippetManager.list(session)
        assert all(snippet.is_approved for snippet in approved)
        assert all(
            snippet.updated_by == str(admin_user.id)
            and snippet.reason == f"Batch approved by {admin_user.username}"
            and snippet.is_human_revoked is False
            for snippet in approved
        )

    @pytest.mark.asyncio
    async def test_duplicate_filenames_are_deduplicated(
        self,
        admin_client: TestClient,
        create_snippet,
        mocker: MockerFixture,
    ):
        """Assert duplicate filenames in the payload are silently deduped."""
        for name in ("a.sh", "b.sh"):
            await create_snippet(name)
        success = mocker.patch("app.sep.apps.snippets.routes.messages.success")

        response = admin_client.post(
            _BATCH_APPROVE_URL,
            data={"filenames": ["a.sh", "a.sh", "b.sh"]},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        flashed = success.call_args.args[1]
        assert flashed == "2 snippet(s) approved"

    @pytest.mark.asyncio
    async def test_unknown_filename_rejects_whole_batch(
        self,
        admin_client: TestClient,
        session: AsyncSession,
        create_snippet,
        mocker: MockerFixture,
    ):
        """Assert one unknown filename aborts the whole batch with a flash error."""
        await create_snippet("exists.sh")
        error = mocker.patch("app.sep.apps.snippets.routes.messages.error")
        success = mocker.patch("app.sep.apps.snippets.routes.messages.success")

        response = admin_client.post(
            _BATCH_APPROVE_URL,
            data={"filenames": ["exists.sh", "ghost.sh"]},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        success.assert_not_called()
        error.assert_called_once()
        message = error.call_args.args[1]
        assert "ghost.sh" in message
        existing = await SnippetManager.get(session, filename="exists.sh")
        assert not existing.is_approved

    @pytest.mark.asyncio
    async def test_missing_file_on_disk_rejects_whole_batch(
        self,
        admin_client: TestClient,
        session: AsyncSession,
        create_snippet,
        mocker: MockerFixture,
    ):
        """Assert the batch aborts when any snippet's file is missing on disk."""
        await create_snippet("present.sh")
        await create_snippet("gone.sh", create_file=False)
        error = mocker.patch("app.sep.apps.snippets.routes.messages.error")

        response = admin_client.post(
            _BATCH_APPROVE_URL,
            data={"filenames": ["present.sh", "gone.sh"]},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        error.assert_called_once()
        message = error.call_args.args[1]
        assert "gone.sh" in message
        assert "missing on disk" in message
        all_snippets = await SnippetManager.list(session)
        assert all(not snippet.is_approved for snippet in all_snippets)

    @pytest.mark.asyncio
    async def test_already_approved_rejects_whole_batch(
        self,
        admin_client: TestClient,
        session: AsyncSession,
        create_snippet,
        mocker: MockerFixture,
    ):
        """Assert an already-approved snippet in the payload aborts the batch."""
        await create_snippet("fresh.sh")
        await create_snippet("old.sh", approved=True)
        error = mocker.patch("app.sep.apps.snippets.routes.messages.error")

        response = admin_client.post(
            _BATCH_APPROVE_URL,
            data={"filenames": ["fresh.sh", "old.sh"]},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        error.assert_called_once()
        message = error.call_args.args[1]
        assert "old.sh" in message
        fresh = await SnippetManager.get(session, filename="fresh.sh")
        assert not fresh.is_approved

    def test_empty_payload_rejected_by_validator(
        self, admin_client: TestClient, mocker: MockerFixture
    ):
        """Assert missing ``filenames`` is rejected before any DB mutation.

        The sep_app's ``RequestValidationError`` handler converts the 422 into
        a flash error + 303 redirect for non-API form submissions, so assert
        on the side effects (flash error fired) rather than the raw 422.
        """
        from_validation_error = mocker.patch(
            "app.sep.main.messages.from_validation_error"
        )

        response = admin_client.post(
            _BATCH_APPROVE_URL, data={}, follow_redirects=False
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        from_validation_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_admin_blocked_by_admin_dep(
        self,
        non_admin_client: TestClient,
        session: AsyncSession,
        create_snippet,
        mocker: MockerFixture,
    ):
        """Assert regular users are blocked by the ``AdminUser`` dependency.

        The sep_app's ``HTTPException`` handler converts the 403 into a flash
        error + 303 redirect, so assert on the side effects (no approval,
        flash error fired) rather than the raw status code.
        """
        await create_snippet("a.sh")
        error = mocker.patch("app.sep.main.messages.error")

        response = non_admin_client.post(
            _BATCH_APPROVE_URL,
            data={"filenames": ["a.sh"]},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        error.assert_called_once()
        existing = await SnippetManager.get(session, filename="a.sh")
        assert not existing.is_approved

    @pytest.mark.asyncio
    async def test_missing_csrf_token_blocked(
        self,
        admin_user: CasdoorUser,
        session: AsyncSession,
        create_snippet,
        mocker: MockerFixture,
    ):
        """Assert CSRF validation runs when not overridden — missing token blocks.

        Like the non-admin case, the 400 surfaces as a 303 redirect through the
        global exception handler, so assert on the flash + absence of approval.
        """
        sep_app.dependency_overrides[get_current_user] = lambda: admin_user
        sep_app.dependency_overrides[get_session] = lambda: session
        await create_snippet("a.sh")
        error = mocker.patch("app.sep.main.messages.error")
        try:
            client = TestClient(sep_app, raise_server_exceptions=False)
            response = client.post(
                _BATCH_APPROVE_URL,
                data={"filenames": ["a.sh"]},
                follow_redirects=False,
            )
        finally:
            sep_app.dependency_overrides = {}

        assert response.status_code == status.HTTP_303_SEE_OTHER
        error.assert_called_once()
        message = error.call_args.args[1]
        assert "CSRF" in message
        existing = await SnippetManager.get(session, filename="a.sh")
        assert not existing.is_approved

    @pytest.mark.asyncio
    async def test_concurrent_partial_success_reports_accurate_counts(
        self,
        admin_client: TestClient,
        create_snippet,
        mocker: MockerFixture,
    ):
        """Assert partial success reports actual rowcount + skipped count.

        The UPDATE auto-commits, so once rows are persisted we cannot rollback.
        Instead of falsely flashing "aborted" while leaving the committed rows
        approved, the route reports the real outcome: N approved, M skipped
        (because another admin approved them between the precheck and UPDATE).
        """
        await create_snippet("a.sh")
        await create_snippet("b.sh")
        fake_result = AsyncMock()
        fake_result.rowcount = 1
        mocker.patch.object(
            SnippetManager, "update_where", new=AsyncMock(return_value=fake_result)
        )
        success = mocker.patch("app.sep.apps.snippets.routes.messages.success")
        error = mocker.patch("app.sep.apps.snippets.routes.messages.error")

        response = admin_client.post(
            _BATCH_APPROVE_URL,
            data={"filenames": ["a.sh", "b.sh"]},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        error.assert_not_called()
        success.assert_called_once()
        flashed = success.call_args.args[1]
        assert "1 snippet(s) approved" in flashed
        assert "1 skipped" in flashed

    @pytest.mark.asyncio
    async def test_concurrent_full_snipe_flashes_error(
        self,
        admin_client: TestClient,
        create_snippet,
        mocker: MockerFixture,
    ):
        """Assert a rowcount-zero result flashes an error and no success."""
        await create_snippet("a.sh")
        await create_snippet("b.sh")
        fake_result = AsyncMock()
        fake_result.rowcount = 0
        mocker.patch.object(
            SnippetManager, "update_where", new=AsyncMock(return_value=fake_result)
        )
        success = mocker.patch("app.sep.apps.snippets.routes.messages.success")
        error = mocker.patch("app.sep.apps.snippets.routes.messages.error")

        response = admin_client.post(
            _BATCH_APPROVE_URL,
            data={"filenames": ["a.sh", "b.sh"]},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        success.assert_not_called()
        error.assert_called_once()
        assert "No snippets were approved" in error.call_args.args[1]

    @pytest.mark.asyncio
    async def test_large_batch(
        self,
        admin_client: TestClient,
        create_snippet,
        mocker: MockerFixture,
    ):
        """Assert a 100-item batch issues a single UPDATE and reports 100 rows."""
        expected_count = 100
        names = [f"s{n:03d}.sh" for n in range(expected_count)]
        for name in names:
            await create_snippet(name)
        success = mocker.patch("app.sep.apps.snippets.routes.messages.success")

        response = admin_client.post(
            _BATCH_APPROVE_URL,
            data={"filenames": names},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        flashed = success.call_args.args[1]
        assert flashed == f"{expected_count} snippet(s) approved"

    @pytest.mark.asyncio
    async def test_success_redirect_targets_index(
        self,
        admin_client: TestClient,
        create_snippet,
        mocker: MockerFixture,
    ):
        """Assert the 303 lands on the snippets index on happy path."""
        await create_snippet("a.sh")
        mocker.patch("app.sep.apps.snippets.routes.messages.success")
        mocker.patch("app.sep.apps.snippets.routes.messages.error")

        response = admin_client.post(
            _BATCH_APPROVE_URL,
            data={"filenames": ["a.sh"]},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"].endswith(_INDEX_URL_PATH)


class TestCompletedTasksPartialHasLogs:
    """Render the shared completed-tasks partial to verify the ``has_logs`` gating.

    Renders the template directly via the SEP Jinja environment instead of
    spinning up the full snippets-detail HTTP flow. A Jinja typo on the gating
    line would silently swallow the **View Logs** button across every
    plugin that includes the partial.
    """

    @staticmethod
    def _make_history(*, history_id: int, has_logs: bool) -> SimpleNamespace:
        """Build a minimal history namespace matching the template's attribute reads."""
        return SimpleNamespace(
            id=history_id,
            status="success",
            task=SimpleNamespace(name="snippet-task"),
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:00:01Z",
            duration=1,
            executed_by="alice",
            execution_request=SimpleNamespace(meta={}),
            available_files={},
            has_logs=has_logs,
        )

    def _render(self, history: SimpleNamespace) -> str:
        template = sep_settings.JINJA_ENVIRONMENT.get_template(_COMPLETED_TASKS_PARTIAL)
        return template.render(history_tasks=[history], user_id_to_username={})

    def test_view_logs_button_rendered_when_has_logs_true(self) -> None:
        """Assert the View Logs button appears when ``has_logs`` is ``True``."""
        rendered = self._render(self._make_history(history_id=1, has_logs=True))

        assert "view-logs-button" in rendered
        assert 'data-task-id="1"' in rendered

    def test_view_logs_button_absent_when_has_logs_false(self) -> None:
        """Assert the View Logs button is absent when ``has_logs`` is ``False``."""
        rendered = self._render(self._make_history(history_id=1, has_logs=False))

        assert "view-logs-button" not in rendered


class TestSnippetsRouterDeprecation:
    """The snippets Jinja2 router uses the deprecation route class."""

    def test_router_uses_deprecated_route_class(self):
        """Confirm the router is constructed with ``DeprecatedJinja2Route``."""
        assert snippets_jinja_router.route_class is DeprecatedJinja2Route


class TestSnippetsRemoveApprovalHumanRevocation:
    """Verify Jinja remove-approval leaves ``updated_by`` set for sticky sync."""

    @pytest.mark.asyncio
    async def test_remove_approval_records_human_revocation(
        self,
        admin_client: TestClient,
        session: AsyncSession,
        create_snippet,
        admin_user: CasdoorUser,
    ):
        """Assert administrator revoke keeps ``updated_by`` and ``is_human_revoked``."""
        snippet = await create_snippet("hello.sh", approved=True)

        response = admin_client.post(
            "/snippets/remove-approval",
            params={"snippet_filename": snippet.filename},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        await session.refresh(snippet)
        assert snippet.is_approved is False
        assert snippet.updated_by == str(admin_user.id)
        assert snippet.is_human_revoked is True


class TestSnippetsApprovalRouteDeprecationHeaders:
    """The three Jinja2 approval routes emit ``Deprecation: true`` (RFC 8594)."""

    @pytest.mark.asyncio
    async def test_approve_emits_deprecation_header(
        self, admin_client: TestClient, create_snippet
    ):
        """Assert approve route carries the RFC 8594 Deprecation header."""
        snippet = await create_snippet("hello.sh", approved=False)

        response = admin_client.post(
            "/snippets/approve",
            params={"snippet_filename": snippet.filename},
            follow_redirects=False,
        )

        assert response.headers.get("Deprecation") == "true"

    @pytest.mark.asyncio
    async def test_remove_approval_emits_deprecation_header(
        self, admin_client: TestClient, create_snippet
    ):
        """Assert remove-approval route carries the RFC 8594 Deprecation header."""
        snippet = await create_snippet("hello.sh", approved=True)

        response = admin_client.post(
            "/snippets/remove-approval",
            params={"snippet_filename": snippet.filename},
            follow_redirects=False,
        )

        assert response.headers.get("Deprecation") == "true"

    @pytest.mark.asyncio
    async def test_approve_batch_emits_deprecation_header(
        self, admin_client: TestClient, create_snippet
    ):
        """Assert approve-batch route carries the RFC 8594 Deprecation header."""
        await create_snippet("a.sh", approved=False)

        response = admin_client.post(
            _BATCH_APPROVE_URL,
            data={"filenames": ["a.sh"]},
            follow_redirects=False,
        )

        assert response.headers.get("Deprecation") == "true"

    @pytest.mark.asyncio
    async def test_refresh_emits_deprecation_header(
        self, admin_client: TestClient, mocker: MockerFixture
    ):
        """Assert legacy refresh route carries the RFC 8594 Deprecation header."""
        mocker.patch(
            "app.sep.apps.snippets.routes.snippets_settings.ENABLE_MANUAL_SYNC",
            new=True,
        )
        mocker.patch(
            "app.sep.apps.snippets.routes.update_snippets",
            new=AsyncMock(return_value=None),
        )

        response = admin_client.post("/snippets/refresh", follow_redirects=False)

        assert response.headers.get("Deprecation") == "true"


class TestSnippetsCsrfEnforcement:
    """Single-snippet approve/remove-approval require a valid CSRF token."""

    @pytest.mark.asyncio
    async def test_approve_without_csrf_token_redirects_with_error(
        self,
        admin_client_no_csrf: TestClient,
        create_snippet,
        mocker: MockerFixture,
    ):
        """POST approve with no form CSRF token → 303 redirect with CSRF error flash.

        The global exception handler converts HTTPBadRequestException (from the
        missing CSRF token) into a 303 redirect with a flash message rather than
        returning a 400 directly — consistent with the batch-approve behaviour.
        """
        snippet = await create_snippet("hello.sh", approved=False)
        error = mocker.patch("app.sep.main.messages.error")

        response = admin_client_no_csrf.post(
            "/snippets/approve",
            params={"snippet_filename": snippet.filename},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        error.assert_called_once()
        message = str(error.call_args.args[1])
        assert "CSRF" in message or "csrf" in message.lower()

    @pytest.mark.asyncio
    async def test_remove_approval_without_csrf_token_redirects_with_error(
        self,
        admin_client_no_csrf: TestClient,
        create_snippet,
        mocker: MockerFixture,
    ):
        """POST remove-approval with no form CSRF token → 303 redirect with CSRF error flash.

        Same global-exception-handler behaviour as the approve route above.
        """
        snippet = await create_snippet("hello.sh", approved=True)
        error = mocker.patch("app.sep.main.messages.error")

        response = admin_client_no_csrf.post(
            "/snippets/remove-approval",
            params={"snippet_filename": snippet.filename},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        error.assert_called_once()
        message = str(error.call_args.args[1])
        assert "CSRF" in message or "csrf" in message.lower()

    @pytest.mark.asyncio
    async def test_refresh_without_csrf_token_redirects_with_error(
        self,
        admin_client_no_csrf: TestClient,
        mocker: MockerFixture,
    ):
        """POST refresh with no form CSRF token → 303 redirect with CSRF error flash.

        The CSRF dependency runs before the route body, so the snippet sync is
        never triggered when the token is missing.
        """
        mocker.patch(
            "app.sep.apps.snippets.routes.snippets_settings.ENABLE_MANUAL_SYNC",
            new=True,
        )
        update = mocker.patch(
            "app.sep.apps.snippets.routes.update_snippets",
            new=AsyncMock(return_value=None),
        )
        error = mocker.patch("app.sep.main.messages.error")

        response = admin_client_no_csrf.post(
            "/snippets/refresh", follow_redirects=False
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        error.assert_called_once()
        message = str(error.call_args.args[1])
        assert "CSRF" in message or "csrf" in message.lower()
        update.assert_not_awaited()


class TestSnippetsExecuteVisibilityGates:
    """Route-level coverage that POST /snippets/execute enforces visibility gates.

    Complements the unit coverage on ``get_validated_execution_args`` in
    ``test_deps.py`` by directly posting a hidden-field value through the live
    legacy form route — the path a non-browser client would abuse.
    """

    @pytest.mark.asyncio
    async def test_rejects_submitted_value_for_gated_hidden_param(
        self,
        admin_client: TestClient,
        session: AsyncSession,
        create_snippet,
        mock_task_api_dep: AsyncMock,
        mocker: MockerFixture,
    ):
        """A value for a gate-hidden field is rejected: flash + redirect, no dispatch."""
        await _seed_gated_snippet(
            create_snippet, session, _GATED_PARAMS, filename="gated-form.sh"
        )
        error = mocker.patch("app.sep.snippets.deps.messages.error")

        response = admin_client.post(
            _EXECUTE_URL,
            params={"snippet_filename": "gated-form.sh"},
            # ``list`` truthy hides ``start``; submitting ``start`` fires the gate.
            data={EXECUTOR_HOSTS_INPUT_NAME: "host1", "list": "1", "start": "2020"},
            headers={"referer": "http://testserver/snippets/detail"},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        error.assert_called_once()
        assert "start" in str(error.call_args.args[1])
        mock_task_api_dep.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_allows_value_when_gate_not_fired(
        self,
        admin_client: TestClient,
        session: AsyncSession,
        create_snippet,
        mock_task_api_dep: AsyncMock,
    ):
        """When the gate stays shut the value is accepted and the task dispatches."""
        await _seed_gated_snippet(
            create_snippet, session, _GATED_PARAMS, filename="open-form.sh"
        )
        mock_task_api_dep.post = AsyncMock(return_value={"id": 11})

        response = admin_client.post(
            _EXECUTE_URL,
            params={"snippet_filename": "open-form.sh"},
            # ``list`` omitted -> ``start`` visible -> value allowed.
            data={EXECUTOR_HOSTS_INPUT_NAME: "host1", "start": "2020"},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        mock_task_api_dep.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_multiple_gated_fields_flash_lists_each_failure(
        self,
        admin_client: TestClient,
        session: AsyncSession,
        create_snippet,
        mock_task_api_dep: AsyncMock,
        mocker: MockerFixture,
    ):
        """Submitting several hidden fields flashes each failure; nothing dispatches."""
        await _seed_gated_snippet(
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
            filename="multi-form.sh",
        )
        error = mocker.patch("app.sep.snippets.deps.messages.error")

        response = admin_client.post(
            _EXECUTE_URL,
            params={"snippet_filename": "multi-form.sh"},
            data={
                EXECUTOR_HOSTS_INPUT_NAME: "host1",
                "list": "1",
                "start": "2020",
                "end": "2021",
            },
            headers={"referer": "http://testserver/snippets/detail"},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        message = str(error.call_args.args[1])
        assert "start" in message
        assert "end" in message
        mock_task_api_dep.post.assert_not_called()
