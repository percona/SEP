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

"""Define tests for the app.sep.apps.snippets.celery module."""

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.sep.apps.snippets.celery as sep_celery
from app.sep.apps.snippets.constants import (
    BUILTIN_APPROVAL_REASON,
    BUILTIN_APPROVAL_USER_ID,
    BUILTIN_CHECKSUM_MANIFEST,
)
from app.sep.snippets.config import SnippetFilter, SnippetFilterType, snippets_settings
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models import Snippet

MODULE = "app.sep.apps.snippets.celery"


def _patch_session(mocker, session):
    """Patch get_async_session_maker to return the test session."""
    mock_session_maker = MagicMock()
    mock_session_maker.return_value.__aenter__ = AsyncMock(return_value=session)
    mock_session_maker.return_value.__aexit__ = AsyncMock(return_value=False)
    mocker.patch(f"{MODULE}.get_async_session_maker", return_value=mock_session_maker)


def _sha256(content: bytes) -> str:
    """Return the SHA-256 hex digest of ``content``."""
    return hashlib.sha256(content).hexdigest()


def _write_manifest(tmp_path: Path, entries: dict[str, bytes]) -> None:
    """Write snippet files and a matching built-in checksum manifest.

    :param tmp_path: The temporary snippets directory.
    :param entries: Mapping of relative filename to file contents.
    """
    lines: list[str] = []
    for filename, content in entries.items():
        (tmp_path / filename).write_bytes(content)
        lines.append(f"{_sha256(content)}  {filename}\n")
    (tmp_path / BUILTIN_CHECKSUM_MANIFEST).write_text("".join(lines), encoding="utf-8")


class TestShouldSkipSnippet:
    """Test should_skip_snippet."""

    def test_no_filter_returns_false(self):
        """Assert no filtering when SYNC_FILTER is None."""
        from app.sep.apps.snippets.celery import should_skip_snippet

        with patch(f"{MODULE}.snippets_settings") as mock_settings:
            mock_settings.SYNC_FILTER = None
            result = should_skip_snippet(Path("test.sh"))

        assert result is False

    def test_extension_matches_returns_false(self):
        """Assert file is not skipped when extension matches filter."""
        from app.sep.apps.snippets.celery import should_skip_snippet

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
        from app.sep.apps.snippets.celery import should_skip_snippet

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
        from app.sep.apps.snippets.celery import should_skip_snippet

        with (
            patch(f"{MODULE}.snippets_settings") as mock_settings,
            patch(f"{MODULE}.guess_mime_type", return_value="text/plain"),
        ):
            mock_settings.SYNC_FILTER = {
                SnippetFilter(".sh", SnippetFilterType.EXTENSION),
            }
            result = should_skip_snippet(Path("readme.txt"))

        assert result is True

    def test_uppercase_extension_matches_lowercase_filter(self):
        """Assert an uppercase ``.SH`` matches a lowercase ``.sh`` filter.

        ``should_skip_snippet`` lowercases ``suffix`` before comparing, so a
        case-variant file name must not be spuriously skipped.
        """
        from app.sep.apps.snippets.celery import should_skip_snippet

        with (
            patch(f"{MODULE}.snippets_settings") as mock_settings,
            patch(f"{MODULE}.guess_mime_type", return_value="text/plain"),
        ):
            mock_settings.SYNC_FILTER = {
                SnippetFilter(".sh", SnippetFilterType.EXTENSION),
            }
            result = should_skip_snippet(Path("SCRIPT.SH"))

        assert result is False


class TestUpdateSnippets:
    """Test update_snippets against a real AsyncSession."""

    @staticmethod
    def _patch_snippets_dir(mocker, tmp_path):
        """Point snippets_settings.SNIPPETS_DIR and Snippet.BASE_DIR at tmp_path."""
        mocker.patch.object(snippets_settings, "SNIPPETS_DIR", tmp_path)
        # BASE_DIR patched alongside SNIPPETS_DIR so Snippet.from_path(...).relative_to(BASE_DIR) resolves under tmp_path.
        mocker.patch.object(Snippet, "BASE_DIR", tmp_path)

    @pytest.mark.asyncio
    async def test_creates_new_snippet(self, session, mocker, tmp_path):
        """Assert a new file on disk creates a corresponding DB row."""
        _patch_session(mocker, session)
        self._patch_snippets_dir(mocker, tmp_path)
        content = b"#!/bin/bash\necho test\n"
        (tmp_path / "test.sh").write_bytes(content)

        await sep_celery.update_snippets()

        rows = await SnippetManager.list(session, filename="test.sh")
        assert len(rows) == 1
        assert rows[0].size == len(content)
        assert (
            rows[0].md5_digest
            == hashlib.md5(content, usedforsecurity=False).hexdigest()
        )

    @pytest.mark.asyncio
    async def test_updates_existing_snippet(self, session, mocker, tmp_path):
        """Assert an existing row is updated when the file content changes."""
        _patch_session(mocker, session)
        self._patch_snippets_dir(mocker, tmp_path)
        await SnippetManager.create(
            session,
            Snippet(filename="test.sh", size=1, md5_digest="0" * 32),
        )
        content = b"#!/bin/bash\necho updated\n"
        (tmp_path / "test.sh").write_bytes(content)

        await sep_celery.update_snippets()

        row = await SnippetManager.first(session, filename="test.sh")
        assert row is not None
        assert row.md5_digest == hashlib.md5(content, usedforsecurity=False).hexdigest()
        assert row.size == len(content)

    @pytest.mark.asyncio
    async def test_skips_filtered_snippet(self, session, mocker, tmp_path):
        """Assert files filtered out by SYNC_FILTER are not persisted."""
        _patch_session(mocker, session)
        self._patch_snippets_dir(mocker, tmp_path)
        mocker.patch.object(
            snippets_settings,
            "SYNC_FILTER",
            {SnippetFilter(".sh", SnippetFilterType.EXTENSION)},
        )
        (tmp_path / "readme.txt").write_text("not a script\n")

        await sep_celery.update_snippets()

        assert len(await SnippetManager.list(session)) == 0

    @pytest.mark.asyncio
    async def test_deletes_orphaned_snippets(self, session, mocker, tmp_path):
        """Assert rows for files no longer on disk are deleted."""
        _patch_session(mocker, session)
        self._patch_snippets_dir(mocker, tmp_path)
        # Single batch covers the common path; if delete_where ever chunks, add a >batch_size case.
        for filename in ("orphan1.sh", "orphan2.sh", "orphan3.sh"):
            await SnippetManager.create(
                session,
                Snippet(filename=filename, size=10, md5_digest="a" * 32),
            )

        await sep_celery.update_snippets()

        assert len(await SnippetManager.list(session)) == 0

    @pytest.mark.asyncio
    async def test_retains_approved_snippet_now_filtered_out(
        self, session, mocker, tmp_path
    ):
        """Assert the skipped-file cleanup deletes only *unapproved* rows.

        Both files are on disk (so neither is an orphan) but fail ``SYNC_FILTER``,
        so both are skipped. ``_delete_unsynced_snippets`` deletes skipped rows
        under an ``approved_at IS NULL`` guard, so the approved row survives while
        the unapproved one is purged.
        """
        _patch_session(mocker, session)
        self._patch_snippets_dir(mocker, tmp_path)
        mocker.patch.object(
            snippets_settings,
            "SYNC_FILTER",
            {SnippetFilter(".sh", SnippetFilterType.EXTENSION)},
        )
        approved = Snippet(filename="keep.txt", size=1, md5_digest="a" * 32)
        approved.approve("Seeded as approved", "seed-user")
        await SnippetManager.create(session, approved)
        await SnippetManager.create(
            session, Snippet(filename="drop.txt", size=1, md5_digest="b" * 32)
        )
        (tmp_path / "keep.txt").write_text("not a script\n")
        (tmp_path / "drop.txt").write_text("not a script\n")

        await sep_celery.update_snippets()

        remaining = {s.filename for s in await SnippetManager.list(session)}
        assert remaining == {"keep.txt"}

    @pytest.mark.asyncio
    async def test_batch_saves_modified_snippets(self, session, mocker, tmp_path):
        """Assert multiple modified rows have their digests updated in one run."""
        _patch_session(mocker, session)
        self._patch_snippets_dir(mocker, tmp_path)
        await SnippetManager.create(
            session, Snippet(filename="a.sh", size=1, md5_digest="0" * 32)
        )
        await SnippetManager.create(
            session, Snippet(filename="b.sh", size=1, md5_digest="1" * 32)
        )
        a_content = b"#!/bin/bash\necho a\n"
        b_content = b"#!/bin/bash\necho b\n"
        (tmp_path / "a.sh").write_bytes(a_content)
        (tmp_path / "b.sh").write_bytes(b_content)

        await sep_celery.update_snippets()

        a_row = await SnippetManager.first(session, filename="a.sh")
        b_row = await SnippetManager.first(session, filename="b.sh")
        assert (
            a_row.md5_digest
            == hashlib.md5(a_content, usedforsecurity=False).hexdigest()
        )
        assert (
            b_row.md5_digest
            == hashlib.md5(b_content, usedforsecurity=False).hexdigest()
        )


class TestBuiltinAutoApproval:
    """Test built-in checksum auto-approval during ``update_snippets``."""

    @staticmethod
    def _patch_snippets_dir(mocker, tmp_path, *, auto_approve: bool = True):
        """Point the snippets dir at ``tmp_path`` and set the auto-approve toggle."""
        mocker.patch.object(snippets_settings, "SNIPPETS_DIR", tmp_path)
        mocker.patch.object(Snippet, "BASE_DIR", tmp_path)
        mocker.patch.object(
            snippets_settings, "AUTO_APPROVE_BUILTIN_SNIPPETS", auto_approve
        )

    @pytest.mark.asyncio
    async def test_creates_and_auto_approves_manifest_match(
        self, session, mocker, tmp_path
    ):
        """Assert a new manifest-matching file is created already approved."""
        _patch_session(mocker, session)
        self._patch_snippets_dir(mocker, tmp_path)
        content = b"#!/bin/bash\necho builtin\n"
        _write_manifest(tmp_path, {"builtin.sh": content})

        await sep_celery.update_snippets()

        row = await SnippetManager.first(session, filename="builtin.sh")
        assert row is not None
        assert row.is_approved is True
        assert row.updated_by == BUILTIN_APPROVAL_USER_ID
        assert row.reason == BUILTIN_APPROVAL_REASON

    @pytest.mark.asyncio
    async def test_verified_content_change_auto_approves(
        self, session, mocker, tmp_path
    ):
        """Assert a content change that still matches the manifest stays approved."""
        _patch_session(mocker, session)
        self._patch_snippets_dir(mocker, tmp_path)
        old_content = b"#!/bin/bash\necho old\n"
        new_content = b"#!/bin/bash\necho new\n"
        await SnippetManager.create(
            session,
            Snippet(
                filename="builtin.sh",
                size=len(old_content),
                md5_digest=hashlib.md5(old_content, usedforsecurity=False).hexdigest(),
            ),
        )
        _write_manifest(tmp_path, {"builtin.sh": new_content})

        await sep_celery.update_snippets()

        row = await SnippetManager.first(session, filename="builtin.sh")
        assert row is not None
        assert row.is_approved is True
        assert row.updated_by == BUILTIN_APPROVAL_USER_ID
        assert row.reason == BUILTIN_APPROVAL_REASON
        assert (
            row.md5_digest
            == hashlib.md5(new_content, usedforsecurity=False).hexdigest()
        )

    @pytest.mark.asyncio
    async def test_digest_mismatch_keeps_manual_gate(self, session, mocker, tmp_path):
        """Assert a file whose digest differs from the manifest stays unapproved."""
        _patch_session(mocker, session)
        self._patch_snippets_dir(mocker, tmp_path)
        content = b"#!/bin/bash\necho local\n"
        (tmp_path / "builtin.sh").write_bytes(content)
        (tmp_path / BUILTIN_CHECKSUM_MANIFEST).write_text(
            f"{'0' * 64}  builtin.sh\n", encoding="utf-8"
        )

        await sep_celery.update_snippets()

        row = await SnippetManager.first(session, filename="builtin.sh")
        assert row is not None
        assert row.is_approved is False

    @pytest.mark.asyncio
    async def test_absent_from_manifest_keeps_manual_gate(
        self, session, mocker, tmp_path
    ):
        """Assert a file missing from the manifest stays unapproved."""
        _patch_session(mocker, session)
        self._patch_snippets_dir(mocker, tmp_path)
        (tmp_path / "custom.sh").write_bytes(b"#!/bin/bash\necho custom\n")
        (tmp_path / BUILTIN_CHECKSUM_MANIFEST).write_text("", encoding="utf-8")

        await sep_celery.update_snippets()

        row = await SnippetManager.first(session, filename="custom.sh")
        assert row is not None
        assert row.is_approved is False

    @pytest.mark.asyncio
    async def test_content_change_auto_clear_is_not_human_revocation(
        self, session, mocker, tmp_path
    ):
        """Assert sync content-change clears ``updated_by`` (not a human revocation).

        Pins the writer invariant: automatic removals pass ``user_id=None`` so
        ``is_human_revoked`` stays false and a later matching sync may re-approve.
        """
        _patch_session(mocker, session)
        self._patch_snippets_dir(mocker, tmp_path)
        old_content = b"#!/bin/bash\necho old\n"
        new_content = b"#!/bin/bash\necho new\n"
        snippet = Snippet(
            filename="builtin.sh",
            size=len(old_content),
            md5_digest=hashlib.md5(old_content, usedforsecurity=False).hexdigest(),
        )
        snippet.approve("Approved by admin", "admin-1")
        await SnippetManager.create(session, snippet)
        # Manifest lists the old digest so the new contents are a mismatch.
        (tmp_path / "builtin.sh").write_bytes(new_content)
        (tmp_path / BUILTIN_CHECKSUM_MANIFEST).write_text(
            f"{_sha256(old_content)}  builtin.sh\n",
            encoding="utf-8",
        )

        await sep_celery.update_snippets()

        row = await SnippetManager.first(session, filename="builtin.sh")
        assert row is not None
        assert row.is_approved is False
        assert row.updated_by is None
        assert row.is_human_revoked is False

    @pytest.mark.asyncio
    async def test_human_revoke_sticky_across_manifest_matching_update(
        self, session, mocker, tmp_path
    ):
        """Assert an administrator revocation survives a later matching content update."""
        _patch_session(mocker, session)
        self._patch_snippets_dir(mocker, tmp_path)
        old_content = b"#!/bin/bash\necho old\n"
        new_content = b"#!/bin/bash\necho new\n"
        snippet = Snippet(
            filename="builtin.sh",
            size=len(old_content),
            md5_digest=hashlib.md5(old_content, usedforsecurity=False).hexdigest(),
        )
        snippet.approve("Approved by admin", "admin-1")
        snippet.remove_approval("Approval removed by admin", "admin-1")
        await SnippetManager.create(session, snippet)
        _write_manifest(tmp_path, {"builtin.sh": new_content})

        await sep_celery.update_snippets()

        row = await SnippetManager.first(session, filename="builtin.sh")
        assert row is not None
        assert row.is_approved is False
        assert row.is_human_revoked is True
        assert row.updated_by == "admin-1"

    @pytest.mark.asyncio
    async def test_manifest_file_excluded_from_sync(self, session, mocker, tmp_path):
        """Assert the checksum manifest never becomes a snippet row."""
        _patch_session(mocker, session)
        self._patch_snippets_dir(mocker, tmp_path)
        content = b"#!/bin/bash\necho builtin\n"
        _write_manifest(tmp_path, {"builtin.sh": content})

        await sep_celery.update_snippets()

        filenames = {s.filename for s in await SnippetManager.list(session)}
        assert BUILTIN_CHECKSUM_MANIFEST not in filenames
        assert filenames == {"builtin.sh"}

    @pytest.mark.asyncio
    async def test_toggle_disabled_skips_auto_approval(self, session, mocker, tmp_path):
        """Assert disabling the setting skips manifest load and leaves matches unapproved."""
        _patch_session(mocker, session)
        self._patch_snippets_dir(mocker, tmp_path, auto_approve=False)
        content = b"#!/bin/bash\necho builtin\n"
        _write_manifest(tmp_path, {"builtin.sh": content})
        load_manifest = mocker.spy(sep_celery, "load_builtin_checksum_manifest")

        await sep_celery.update_snippets()

        load_manifest.assert_not_called()
        row = await SnippetManager.first(session, filename="builtin.sh")
        assert row is not None
        assert row.is_approved is False

    @pytest.mark.asyncio
    async def test_unchanged_unapproved_row_auto_approved_on_upgrade(
        self, session, mocker, tmp_path
    ):
        """Assert an existing unapproved matching row is approved without a content change."""
        _patch_session(mocker, session)
        self._patch_snippets_dir(mocker, tmp_path)
        content = b"#!/bin/bash\necho builtin\n"
        await SnippetManager.create(
            session,
            Snippet(
                filename="builtin.sh",
                size=len(content),
                md5_digest=hashlib.md5(content, usedforsecurity=False).hexdigest(),
            ),
        )
        _write_manifest(tmp_path, {"builtin.sh": content})

        await sep_celery.update_snippets()

        row = await SnippetManager.first(session, filename="builtin.sh")
        assert row is not None
        assert row.is_approved is True
        assert row.updated_by == BUILTIN_APPROVAL_USER_ID
        assert row.reason == BUILTIN_APPROVAL_REASON

    @pytest.mark.asyncio
    async def test_approvals_and_content_changes_use_split_batches(
        self, session, mocker, tmp_path
    ):
        """Assert approval-only and content-change rows use separate save batches."""
        _patch_session(mocker, session)
        self._patch_snippets_dir(mocker, tmp_path)
        create_content = b"#!/bin/bash\necho create\n"
        old_content = b"#!/bin/bash\necho old\n"
        new_content = b"#!/bin/bash\necho new\n"
        await SnippetManager.create(
            session,
            Snippet(
                filename="changed.sh",
                size=len(old_content),
                md5_digest=hashlib.md5(old_content, usedforsecurity=False).hexdigest(),
            ),
        )
        _write_manifest(
            tmp_path,
            {"create.sh": create_content, "changed.sh": new_content},
        )
        save_batch = mocker.spy(SnippetManager, "save_batch")

        await sep_celery.update_snippets()

        meta_batch, approval_batch = save_batch.call_args_list
        assert meta_batch.kwargs.get("flag_modified_fields") == ["meta"]
        assert {s.filename for s in meta_batch.args[1:]} == {"changed.sh"}
        assert approval_batch.kwargs.get("flag_modified_fields", ()) == ()
        assert {s.filename for s in approval_batch.args[1:]} == {"create.sh"}
        create_row = await SnippetManager.first(session, filename="create.sh")
        assert create_row is not None
        assert create_row.is_approved is True


class TestSyncSnippets:
    """Test sync_snippets Celery task."""

    def test_calls_update_snippets(self):
        """Assert sync_snippets runs update_snippets via the event loop."""
        from app.sep.apps.snippets.celery import sync_snippets

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


class TestUpdateSnippetsCooperativeCancel:
    """``update_snippets`` honours the cooperative-cancel safe point."""

    @pytest.mark.asyncio
    async def test_stops_at_safe_point_preserving_committed_creates(
        self, session, mocker, tmp_path
    ):
        """Keep committed creates and skip post-loop writes on a mid-loop cancel."""
        _patch_session(mocker, session)
        mocker.patch.object(snippets_settings, "SNIPPETS_DIR", tmp_path)
        mocker.patch.object(Snippet, "BASE_DIR", tmp_path)
        (tmp_path / "a.sh").write_bytes(b"#!/bin/bash\necho a\n")
        (tmp_path / "b.sh").write_bytes(b"#!/bin/bash\necho b\n")
        mocker.patch(
            f"{MODULE}.should_cancel", new=AsyncMock(side_effect=[False, True])
        )
        save_batch = mocker.spy(SnippetManager, "save_batch")
        delete_where = mocker.spy(SnippetManager, "delete_where")

        await sep_celery.update_snippets()

        assert len(await SnippetManager.list(session)) == 1
        save_batch.assert_not_called()
        delete_where.assert_not_called()

    @pytest.mark.asyncio
    async def test_stops_after_loop_skipping_post_loop_writes(
        self, session, mocker, tmp_path
    ):
        """Skip the batch save and cleanup when the cancel is seen only after the loop."""
        _patch_session(mocker, session)
        mocker.patch.object(snippets_settings, "SNIPPETS_DIR", tmp_path)
        mocker.patch.object(Snippet, "BASE_DIR", tmp_path)
        await SnippetManager.create(
            session, Snippet(filename="present.sh", size=1, md5_digest="0" * 32)
        )
        await SnippetManager.create(
            session, Snippet(filename="orphan.sh", size=10, md5_digest="a" * 32)
        )
        (tmp_path / "present.sh").write_bytes(b"#!/bin/bash\necho present\n")
        mocker.patch(
            f"{MODULE}.should_cancel", new=AsyncMock(side_effect=[False, True])
        )
        save_batch = mocker.spy(SnippetManager, "save_batch")
        delete_where = mocker.spy(SnippetManager, "delete_where")

        await sep_celery.update_snippets()

        save_batch.assert_not_called()
        delete_where.assert_not_called()
        assert await SnippetManager.first(session, filename="orphan.sh") is not None
