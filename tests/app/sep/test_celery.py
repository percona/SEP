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

"""Define tests for the app.sep.celery module."""

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.sep.celery as sep_celery
from app.sep.apps.alerts.config import AlertsSettings
from app.sep.apps.alerts.crud import AlertBackupManager
from app.sep.apps.alerts.models import AlertBackup
from app.sep.clients.pmm import (
    AlertRule,
    ContactPoint,
    Folder,
    NotificationPolicy,
    PMMRemoteAPI,
)
from app.sep.clients.pmm import (
    AlertTemplate as PMMAlertTemplate,
)
from app.sep.snippets.config import SnippetFilter, SnippetFilterType, snippets_settings
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models import Snippet

EXPECTED_BACKUP_COUNT_AFTER_DIFF = 2
MODULE = "app.sep.celery"


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


_MOCK_CONTACT_POINT_COUNT = 2


def _mock_pmm_api():
    """Build a mock PMMRemoteAPI with alert methods."""
    api = AsyncMock(spec=PMMRemoteAPI)
    api.list_templates = AsyncMock(
        return_value=[
            PMMAlertTemplate(name="t1", summary="Template 1", template="yaml1"),
        ]
    )
    api.list_rules = AsyncMock(
        return_value=[
            AlertRule(uid="r1", title="Rule 1"),
        ]
    )
    api.list_contact_points = AsyncMock(
        return_value=[
            ContactPoint(uid="cp1", name="CP 1", type="email"),
            ContactPoint(uid="cp2", name="CP 2", type="slack"),
        ]
    )
    api.get_notification_policy = AsyncMock(
        return_value=NotificationPolicy(
            receiver="default",
        )
    )
    api.list_folders = AsyncMock(
        return_value=[
            Folder(uid="f1", title="Folder 1", id=1),
        ]
    )
    return api


def _patch_pmm_settings(mocker, *, retention=10):
    """Patch alerts PMM config inside _backup_alert_config."""
    mocker.patch(
        "app.sep.apps.alerts.config.alerts_settings",
        MagicMock(spec=AlertsSettings, BACKUP_RETENTION=retention),
    )


def _patch_session(mocker, session):
    """Patch get_async_session_maker to return the test session."""
    mock_session_maker = MagicMock()
    mock_session_maker.return_value.__aenter__ = AsyncMock(return_value=session)
    mock_session_maker.return_value.__aexit__ = AsyncMock(return_value=False)
    mocker.patch(
        "app.sep.celery.get_async_session_maker", return_value=mock_session_maker
    )


class TestBackupAlertConfig:
    """Test the _backup_alert_config async function."""

    @pytest.fixture(autouse=True)
    def _never_cancel(self, mocker):
        """Keep the drain check from reading the real DB in happy-path tests."""
        mocker.patch(f"{MODULE}.should_cancel", new=AsyncMock(return_value=False))

    @pytest.mark.asyncio
    async def test_backup_success(self, session, mocker) -> None:
        """Assert a backup row is created with correct data and metadata."""
        mock_api = _mock_pmm_api()
        _patch_pmm_settings(mocker)
        mocker.patch(
            "app.sep.apps.alerts.deps.get_pmm_api",
            new=AsyncMock(return_value=mock_api),
        )
        _patch_session(mocker, session)

        await sep_celery._backup_alert_config()

        results = await AlertBackupManager.list(session)
        assert len(results) == 1
        backup = results[0]
        assert backup.metadata_["template_count"] == 1
        assert backup.metadata_["rule_count"] == 1
        assert backup.metadata_["contact_point_count"] == _MOCK_CONTACT_POINT_COUNT
        assert backup.metadata_["folder_count"] == 1
        assert len(backup.data["templates"]) == 1
        assert len(backup.data["rules"]) == 1
        assert len(backup.data["contact_points"]) == _MOCK_CONTACT_POINT_COUNT
        assert len(backup.data["folders"]) == 1

    @pytest.mark.asyncio
    async def test_backup_pmm_not_configured(self, mocker) -> None:
        """Assert no backup is created when PMM is not configured."""
        mocker.patch(
            "app.sep.apps.alerts.deps.get_pmm_api",
            new=AsyncMock(return_value=None),
        )
        mock_session_maker = mocker.patch("app.sep.celery.get_async_session_maker")

        await sep_celery._backup_alert_config()

        mock_session_maker.assert_not_called()

    @pytest.mark.asyncio
    async def test_backup_pmm_api_error(self, mocker) -> None:
        """Assert API errors are logged without crashing the task."""
        mock_api = AsyncMock(spec=PMMRemoteAPI)
        mock_api.list_templates = AsyncMock(
            side_effect=ConnectionError("PMM unreachable")
        )
        mocker.patch(
            "app.sep.apps.alerts.deps.get_pmm_api",
            new=AsyncMock(return_value=mock_api),
        )
        mock_session_maker = mocker.patch("app.sep.celery.get_async_session_maker")

        await sep_celery._backup_alert_config()

        mock_session_maker.assert_not_called()

    @pytest.mark.asyncio
    async def test_backup_retention_cleanup(self, session, mocker) -> None:
        """Assert oldest backups beyond retention limit are deleted."""
        retention = 3
        for i in range(5):
            backup = AlertBackup(
                data={"index": i},
                metadata_={"count": i},
            )
            await AlertBackupManager.save(session, backup)

        mock_api = _mock_pmm_api()
        _patch_pmm_settings(mocker, retention=retention)
        mocker.patch(
            "app.sep.apps.alerts.deps.get_pmm_api",
            new=AsyncMock(return_value=mock_api),
        )
        _patch_session(mocker, session)

        await sep_celery._backup_alert_config()

        results = await AlertBackupManager.list(session)
        assert len(results) == retention

    @pytest.mark.asyncio
    async def test_backup_retention_configurable(self, session, mocker) -> None:
        """Assert retention limit is respected with custom value."""
        retention = 2
        for i in range(4):
            backup = AlertBackup(
                data={"index": i},
                metadata_={"count": i},
            )
            await AlertBackupManager.save(session, backup)

        mock_api = _mock_pmm_api()
        _patch_pmm_settings(mocker, retention=retention)
        mocker.patch(
            "app.sep.apps.alerts.deps.get_pmm_api",
            new=AsyncMock(return_value=mock_api),
        )
        _patch_session(mocker, session)

        await sep_celery._backup_alert_config()

        results = await AlertBackupManager.list(session)
        assert len(results) == retention

    @pytest.mark.asyncio
    async def test_backup_skips_duplicate(self, session, mocker) -> None:
        """Assert no new backup is created when data is unchanged."""
        mock_api = _mock_pmm_api()
        _patch_pmm_settings(mocker)
        mocker.patch(
            "app.sep.apps.alerts.deps.get_pmm_api",
            new=AsyncMock(return_value=mock_api),
        )
        _patch_session(mocker, session)

        await sep_celery._backup_alert_config()
        results_after_first = await AlertBackupManager.list(session)
        assert len(results_after_first) == 1

        await sep_celery._backup_alert_config()
        results_after_second = await AlertBackupManager.list(session)
        assert len(results_after_second) == 1

    @pytest.mark.asyncio
    async def test_backup_skips_duplicate_despite_reordered_api_response(
        self, session, mocker
    ) -> None:
        """Assert dedup works even when the API returns items in different order."""
        mock_api = _mock_pmm_api()
        _patch_pmm_settings(mocker)
        mocker.patch(
            "app.sep.apps.alerts.deps.get_pmm_api",
            new=AsyncMock(return_value=mock_api),
        )
        _patch_session(mocker, session)

        await sep_celery._backup_alert_config()

        mock_api.list_contact_points = AsyncMock(
            return_value=[
                ContactPoint(uid="cp2", name="CP 2", type="slack"),
                ContactPoint(uid="cp1", name="CP 1", type="email"),
            ]
        )

        await sep_celery._backup_alert_config()
        results = await AlertBackupManager.list(session)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_backup_saves_when_data_differs(self, session, mocker) -> None:
        """Assert a new backup is created when data changes."""
        mock_api = _mock_pmm_api()
        _patch_pmm_settings(mocker)
        mocker.patch(
            "app.sep.apps.alerts.deps.get_pmm_api",
            new=AsyncMock(return_value=mock_api),
        )
        _patch_session(mocker, session)

        existing = AlertBackup(
            data={
                "templates": [],
                "rules": [],
                "contact_points": [],
                "notification_policy": {},
                "folders": [],
            },
            metadata_={
                "template_count": 0,
                "rule_count": 0,
                "contact_point_count": 0,
                "folder_count": 0,
            },
        )
        await AlertBackupManager.save(session, existing)

        await sep_celery._backup_alert_config()

        results = await AlertBackupManager.list(session)
        assert len(results) == EXPECTED_BACKUP_COUNT_AFTER_DIFF


class TestUpdateSnippetsCooperativeCancel:
    """``update_snippets`` honours the cooperative-cancel safe point."""

    @pytest.mark.asyncio
    async def test_stops_at_safe_point_preserving_committed_creates(
        self, session, mocker, tmp_path
    ):
        """A mid-loop cancel keeps committed creates and skips post-loop writes."""
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
        """A cancel observed only after the loop skips the batch save and cleanup."""
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


class TestBackupAlertConfigCooperativeCancel:
    """``_backup_alert_config`` honours the cooperative-cancel safe points."""

    @pytest.mark.asyncio
    async def test_stops_before_fetch_on_cancel(self, mocker):
        """A cancel before the fetch skips the PMM round-trip entirely."""
        mock_api = _mock_pmm_api()
        mocker.patch(
            "app.sep.apps.alerts.deps.get_pmm_api",
            new=AsyncMock(return_value=mock_api),
        )
        mocker.patch(f"{MODULE}.should_cancel", new=AsyncMock(return_value=True))

        await sep_celery._backup_alert_config()

        mock_api.list_templates.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stops_before_write_on_cancel(self, session, mocker):
        """A cancel after the fetch skips the backup write, leaving prior data."""
        mock_api = _mock_pmm_api()
        _patch_pmm_settings(mocker)
        mocker.patch(
            "app.sep.apps.alerts.deps.get_pmm_api",
            new=AsyncMock(return_value=mock_api),
        )
        _patch_session(mocker, session)
        mocker.patch(
            f"{MODULE}.should_cancel", new=AsyncMock(side_effect=[False, True])
        )
        save = mocker.spy(AlertBackupManager, "save")

        await sep_celery._backup_alert_config()

        mock_api.list_templates.assert_awaited()
        assert len(await AlertBackupManager.list(session)) == 0
        save.assert_not_called()
