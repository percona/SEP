"""Tests for SnippetManager CRUD operations."""

from unittest.mock import AsyncMock, patch

import pytest

from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models import Snippet


class TestSnippetManagerGetOrCreate:
    """Test the get_or_create method override."""

    @pytest.mark.asyncio
    async def test_creates_new_snippet_and_calls_update_meta(self):
        """Verify new snippet is created and update_meta is called."""
        session = AsyncMock()
        snippet = Snippet(filename="new.sh", size=50, md5_digest="c" * 32)

        with (
            patch.object(
                SnippetManager, "first", new_callable=AsyncMock, return_value=None
            ),
            patch.object(
                SnippetManager,
                "create",
                new_callable=AsyncMock,
                return_value=snippet,
            ) as mock_create,
            patch.object(
                Snippet, "update_meta", new_callable=AsyncMock
            ) as mock_update_meta,
        ):
            result, created = await SnippetManager.get_or_create(
                session, snippet, filter_include={"filename"}
            )

        assert created is True
        assert result is snippet
        mock_update_meta.assert_awaited_once()
        mock_create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_existing_snippet(self):
        """Verify existing snippet is returned without creating."""
        session = AsyncMock()
        existing = Snippet(filename="existing.sh", size=100, md5_digest="d" * 32)
        new_snippet = Snippet(filename="existing.sh", size=100, md5_digest="d" * 32)

        with (
            patch.object(
                SnippetManager,
                "first",
                new_callable=AsyncMock,
                return_value=existing,
            ),
            patch.object(
                SnippetManager, "create", new_callable=AsyncMock
            ) as mock_create,
        ):
            result, created = await SnippetManager.get_or_create(
                session, new_snippet, filter_include={"filename"}
            )

        assert created is False
        assert result is existing
        mock_create.assert_not_awaited()
