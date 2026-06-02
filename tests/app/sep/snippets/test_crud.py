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

"""Tests for SnippetManager CRUD operations."""

from unittest.mock import AsyncMock, patch

import pytest

from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models import Snippet


class TestSnippetManagerGetOrCreate:
    """Test the get_or_create method override."""

    @pytest.mark.asyncio
    async def test_creates_new_snippet_and_calls_update_meta(self, session):
        """Verify new snippet is created and update_meta is called."""
        snippet = Snippet(filename="new.sh", size=50, md5_digest="c" * 32)

        with patch.object(
            Snippet, "update_meta", new_callable=AsyncMock
        ) as mock_update_meta:
            result, created = await SnippetManager.get_or_create(
                session, snippet, filter_include={"filename"}
            )

        assert created is True
        assert result.filename == "new.sh"
        assert result.md5_digest == "c" * 32
        mock_update_meta.assert_awaited_once()

        persisted = await SnippetManager.list(session, filename="new.sh")
        assert len(persisted) == 1
        assert persisted[0].md5_digest == "c" * 32

    @pytest.mark.asyncio
    async def test_returns_existing_snippet(self, session):
        """Verify existing snippet is returned without creating a duplicate."""
        existing = await SnippetManager.create(
            session,
            Snippet(filename="existing.sh", size=100, md5_digest="d" * 32),
        )

        new_snippet = Snippet(filename="existing.sh", size=200, md5_digest="e" * 32)

        with patch.object(
            Snippet, "update_meta", new_callable=AsyncMock
        ) as mock_update_meta:
            result, created = await SnippetManager.get_or_create(
                session, new_snippet, filter_include={"filename"}
            )

        assert created is False
        assert result.id == existing.id
        mock_update_meta.assert_not_awaited()

        persisted = await SnippetManager.list(session, filename="existing.sh")
        assert len(persisted) == 1
        assert persisted[0].md5_digest == "d" * 32
