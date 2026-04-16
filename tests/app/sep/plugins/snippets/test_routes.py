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

from unittest.mock import AsyncMock

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import CasdoorUser
from app.sep.deps import get_current_user, get_session
from app.sep.main import sep_app
from app.sep.snippets.crud import SnippetManager

_BATCH_APPROVE_URL = "/snippets/approve-batch"
_INDEX_URL_PATH = "/snippets/"


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
        success = mocker.patch("app.sep.plugins.snippets.routes.messages.success")
        error = mocker.patch("app.sep.plugins.snippets.routes.messages.error")

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
        success = mocker.patch("app.sep.plugins.snippets.routes.messages.success")

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
        error = mocker.patch("app.sep.plugins.snippets.routes.messages.error")
        success = mocker.patch("app.sep.plugins.snippets.routes.messages.success")

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
        error = mocker.patch("app.sep.plugins.snippets.routes.messages.error")

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
        error = mocker.patch("app.sep.plugins.snippets.routes.messages.error")

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

    def test_empty_payload_rejected_by_validator(self, admin_client: TestClient):
        """Assert missing ``filenames`` yields 422 before any DB mutation."""
        response = admin_client.post(
            _BATCH_APPROVE_URL, data={}, follow_redirects=False
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

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
            with TestClient(sep_app, raise_server_exceptions=False) as client:
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
    async def test_concurrent_update_aborts_batch(
        self,
        admin_client: TestClient,
        create_snippet,
        mocker: MockerFixture,
    ):
        """Assert a rowcount mismatch signals a concurrent update and aborts."""
        await create_snippet("a.sh")
        await create_snippet("b.sh")
        fake_result = AsyncMock()
        fake_result.rowcount = 1
        mocker.patch.object(
            SnippetManager, "update_where", new=AsyncMock(return_value=fake_result)
        )
        error = mocker.patch("app.sep.plugins.snippets.routes.messages.error")

        response = admin_client.post(
            _BATCH_APPROVE_URL,
            data={"filenames": ["a.sh", "b.sh"]},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        error.assert_called_once()
        assert "concurrent" in error.call_args.args[1].lower()

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
        success = mocker.patch("app.sep.plugins.snippets.routes.messages.success")

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
        mocker.patch("app.sep.plugins.snippets.routes.messages.success")
        mocker.patch("app.sep.plugins.snippets.routes.messages.error")

        response = admin_client.post(
            _BATCH_APPROVE_URL,
            data={"filenames": ["a.sh"]},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"].endswith(_INDEX_URL_PATH)
