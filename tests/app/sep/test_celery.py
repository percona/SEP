"""Define tests for the app.sep.celery module."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.sep.snippets.config import SnippetFilter, SnippetFilterType

MODULE = "app.sep.celery"
EXPECTED_DELETE_WHERE_CALLS = 2


def _make_async_session_maker():
    """Build a mock async session maker that yields an async context manager."""
    session = AsyncMock()
    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session_cm), session


class TestShouldSkipSnippet:
    """Test should_skip_snippet."""

    def test_no_filter_returns_false(self):
        """Assert no filtering when SYNC_FILTER is None."""
        from app.sep.celery import should_skip_snippet

        with patch(f"{MODULE}.snippets_settings") as mock_settings:
            mock_settings.SYNC_FILTER = None
            result = should_skip_snippet(Path("test.sh"))

        assert result is False

    def test_extension_matches_returns_false(self):
        """Assert file is not skipped when extension matches filter."""
        from app.sep.celery import should_skip_snippet

        with (
            patch(f"{MODULE}.snippets_settings") as mock_settings,
            patch(f"{MODULE}.guess_mime_type", return_value="text/plain"),
        ):
            mock_settings.SYNC_FILTER = {
                SnippetFilter(".sh", SnippetFilterType.EXTENSION),
            }
            result = should_skip_snippet(Path("script.sh"))

        assert result is False

    def test_mime_matches_returns_false(self):
        """Assert file is not skipped when MIME type matches filter."""
        from app.sep.celery import should_skip_snippet

        with (
            patch(f"{MODULE}.snippets_settings") as mock_settings,
            patch(
                f"{MODULE}.guess_mime_type", return_value="application/x-shellscript"
            ),
        ):
            mock_settings.SYNC_FILTER = {
                SnippetFilter("application/x-shellscript", SnippetFilterType.MIME_TYPE),
            }
            result = should_skip_snippet(Path("script.bin"))

        assert result is False

    def test_no_match_returns_true(self):
        """Assert file is skipped when neither extension nor MIME matches."""
        from app.sep.celery import should_skip_snippet

        with (
            patch(f"{MODULE}.snippets_settings") as mock_settings,
            patch(f"{MODULE}.guess_mime_type", return_value="text/plain"),
        ):
            mock_settings.SYNC_FILTER = {
                SnippetFilter(".sh", SnippetFilterType.EXTENSION),
            }
            result = should_skip_snippet(Path("readme.txt"))

        assert result is True


class TestUpdateSnippets:
    """Test update_snippets."""

    @pytest.mark.asyncio
    async def test_creates_new_snippet(self):
        """Assert new snippet is counted when get_or_create returns created=True."""
        from app.sep.celery import update_snippets

        session_maker, session = _make_async_session_maker()
        mock_snippet = MagicMock()
        mock_snippet.filename = "test.sh"
        snippet_path = MagicMock(spec=Path)
        snippet_path.is_file.return_value = True
        snippet_path.suffix = ".sh"
        snippet_path.relative_to.return_value = Path("test.sh")

        with (
            patch(f"{MODULE}.get_async_session_maker", return_value=session_maker),
            patch(f"{MODULE}.snippets_settings") as mock_settings,
            patch(f"{MODULE}.should_skip_snippet", return_value=False),
            patch(
                f"{MODULE}.Snippet.from_path", new_callable=AsyncMock
            ) as mock_from_path,
            patch(f"{MODULE}.SnippetManager") as mock_manager,
        ):
            mock_settings.SNIPPETS_DIR.rglob.return_value = [snippet_path]
            mock_from_path.return_value = mock_snippet
            mock_manager.get_or_create = AsyncMock(return_value=(mock_snippet, True))
            mock_manager.delete_where = AsyncMock(return_value=MagicMock(rowcount=0))

            await update_snippets()

            mock_manager.get_or_create.assert_called_once_with(
                session, mock_snippet, {"filename"}
            )

    @pytest.mark.asyncio
    async def test_updates_existing_snippet(self):
        """Assert update_from_snippet called when hash differs."""
        from app.sep.celery import update_snippets

        session_maker, session = _make_async_session_maker()
        existing_snippet = MagicMock()
        existing_snippet.md5_digest = "old_hash"
        existing_snippet.filename = "test.sh"
        existing_snippet.update_from_snippet = AsyncMock()

        new_snippet = MagicMock()
        new_snippet.md5_digest = "new_hash"
        new_snippet.filename = "test.sh"

        snippet_path = MagicMock(spec=Path)
        snippet_path.is_file.return_value = True
        snippet_path.suffix = ".sh"
        snippet_path.relative_to.return_value = Path("test.sh")

        with (
            patch(f"{MODULE}.get_async_session_maker", return_value=session_maker),
            patch(f"{MODULE}.snippets_settings") as mock_settings,
            patch(f"{MODULE}.should_skip_snippet", return_value=False),
            patch(
                f"{MODULE}.Snippet.from_path", new_callable=AsyncMock
            ) as mock_from_path,
            patch(f"{MODULE}.SnippetManager") as mock_manager,
        ):
            mock_settings.SNIPPETS_DIR.rglob.return_value = [snippet_path]
            mock_from_path.return_value = new_snippet
            mock_manager.get_or_create = AsyncMock(
                return_value=(existing_snippet, False)
            )
            mock_manager.save_batch = AsyncMock()
            mock_manager.delete_where = AsyncMock(return_value=MagicMock(rowcount=0))

            await update_snippets()

            existing_snippet.update_from_snippet.assert_called_once_with(new_snippet)
            mock_manager.save_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_filtered_snippet(self):
        """Assert filtered files are skipped and not processed."""
        from app.sep.celery import update_snippets

        session_maker, session = _make_async_session_maker()
        snippet_path = MagicMock(spec=Path)
        snippet_path.is_file.return_value = True
        snippet_path.suffix = ".txt"
        snippet_path.relative_to.return_value = Path("readme.txt")

        with (
            patch(f"{MODULE}.get_async_session_maker", return_value=session_maker),
            patch(f"{MODULE}.snippets_settings") as mock_settings,
            patch(f"{MODULE}.should_skip_snippet", return_value=True),
            patch(
                f"{MODULE}.Snippet.from_path", new_callable=AsyncMock
            ) as mock_from_path,
            patch(f"{MODULE}.SnippetManager") as mock_manager,
        ):
            mock_settings.SNIPPETS_DIR.rglob.return_value = [snippet_path]
            mock_manager.delete_where = AsyncMock(return_value=MagicMock(rowcount=0))

            await update_snippets()

            mock_from_path.assert_not_called()

    @pytest.mark.asyncio
    async def test_deletes_orphaned_snippets(self):
        """Assert delete_where is called for files not on filesystem."""
        from app.sep.celery import update_snippets

        session_maker, session = _make_async_session_maker()

        with (
            patch(f"{MODULE}.get_async_session_maker", return_value=session_maker),
            patch(f"{MODULE}.snippets_settings") as mock_settings,
            patch(f"{MODULE}.SnippetManager") as mock_manager,
        ):
            mock_settings.SNIPPETS_DIR.rglob.return_value = []
            mock_manager.delete_where = AsyncMock(return_value=MagicMock(rowcount=3))

            await update_snippets()

            assert mock_manager.delete_where.call_count == EXPECTED_DELETE_WHERE_CALLS

    @pytest.mark.asyncio
    async def test_batch_saves_modified_snippets(self):
        """Assert save_batch is called with the list of modified snippets."""
        from app.sep.celery import update_snippets

        session_maker, session = _make_async_session_maker()
        existing1 = MagicMock()
        existing1.md5_digest = "old1"
        existing1.filename = "a.sh"
        existing1.update_from_snippet = AsyncMock()

        existing2 = MagicMock()
        existing2.md5_digest = "old2"
        existing2.filename = "b.sh"
        existing2.update_from_snippet = AsyncMock()

        new1 = MagicMock()
        new1.md5_digest = "new1"
        new1.filename = "a.sh"

        new2 = MagicMock()
        new2.md5_digest = "new2"
        new2.filename = "b.sh"

        path1 = MagicMock(spec=Path)
        path1.is_file.return_value = True
        path1.suffix = ".sh"
        path1.relative_to.return_value = Path("a.sh")

        path2 = MagicMock(spec=Path)
        path2.is_file.return_value = True
        path2.suffix = ".sh"
        path2.relative_to.return_value = Path("b.sh")

        with (
            patch(f"{MODULE}.get_async_session_maker", return_value=session_maker),
            patch(f"{MODULE}.snippets_settings") as mock_settings,
            patch(f"{MODULE}.should_skip_snippet", return_value=False),
            patch(
                f"{MODULE}.Snippet.from_path",
                new_callable=AsyncMock,
                side_effect=[new1, new2],
            ),
            patch(f"{MODULE}.SnippetManager") as mock_manager,
        ):
            mock_settings.SNIPPETS_DIR.rglob.return_value = [path1, path2]
            mock_manager.get_or_create = AsyncMock(
                side_effect=[(existing1, False), (existing2, False)]
            )
            mock_manager.save_batch = AsyncMock()
            mock_manager.delete_where = AsyncMock(return_value=MagicMock(rowcount=0))

            await update_snippets()

            mock_manager.save_batch.assert_called_once()
            saved_snippets = mock_manager.save_batch.call_args[0]
            assert saved_snippets[0] == session
            assert existing1 in saved_snippets[1:]
            assert existing2 in saved_snippets[1:]


class TestSyncSnippets:
    """Test sync_snippets Celery task."""

    def test_calls_update_snippets(self):
        """Assert sync_snippets runs update_snippets via the event loop."""
        from app.sep.celery import sync_snippets

        mock_loop = MagicMock()
        sentinel_coro = MagicMock()
        mock_update = MagicMock(return_value=sentinel_coro)

        with (
            patch(f"{MODULE}.celery") as mock_celery,
            patch(f"{MODULE}.update_snippets", mock_update),
        ):
            mock_celery.loop = mock_loop

            sync_snippets()

            mock_update.assert_called_once()
            mock_loop.run_until_complete.assert_called_once_with(sentinel_coro)
