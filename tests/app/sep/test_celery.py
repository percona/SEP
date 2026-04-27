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

from datetime import datetime, timedelta, UTC
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.core.alerts.models import AlertService, AlertSeverity
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils import json_serializer
from app.sep.celery import (
    _backup_alert_config,
    _check_nomad_cert_expiry,
    check_nomad_cert_expiry,
)
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
from app.sep.plugins.alerts.config import AlertsPMMConfig
from app.sep.plugins.alerts.crud import AlertBackupManager
from app.sep.plugins.alerts.models import AlertBackup
from app.sep.snippets.config import SnippetFilter, SnippetFilterType
from app.tasks.execution.executors.nomad import NomadExecutor

MODULE = "app.sep.celery"
EXPECTED_DELETE_WHERE_CALLS = 2
EXPECTED_BACKUP_COUNT_AFTER_DIFF = 2
EXPECTED_NOMAD_CERT_RESOLVE_CALLS = 2
ANCHOR = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


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


_MOCK_CONTACT_POINT_COUNT = 2


@pytest_asyncio.fixture(name="session")
async def session_fixture() -> AsyncSession:
    """Create an async db session for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session_maker = get_async_session_maker_from_engine(engine)
    async with async_session_maker() as session:
        yield session


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
        "app.sep.plugins.alerts.config.alerts_pmm_config",
        MagicMock(spec=AlertsPMMConfig, backup_retention=retention),
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

    @pytest.mark.asyncio
    async def test_backup_success(self, session, mocker) -> None:
        """Assert a backup row is created with correct data and metadata."""
        mock_api = _mock_pmm_api()
        _patch_pmm_settings(mocker)
        mocker.patch(
            "app.sep.plugins.alerts.deps.get_pmm_api",
            new=AsyncMock(return_value=mock_api),
        )
        _patch_session(mocker, session)

        await _backup_alert_config()

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
            "app.sep.plugins.alerts.deps.get_pmm_api",
            new=AsyncMock(return_value=None),
        )
        mock_session_maker = mocker.patch("app.sep.celery.get_async_session_maker")

        await _backup_alert_config()

        mock_session_maker.assert_not_called()

    @pytest.mark.asyncio
    async def test_backup_pmm_api_error(self, mocker) -> None:
        """Assert API errors are logged without crashing the task."""
        mock_api = AsyncMock(spec=PMMRemoteAPI)
        mock_api.list_templates = AsyncMock(
            side_effect=ConnectionError("PMM unreachable")
        )
        mocker.patch(
            "app.sep.plugins.alerts.deps.get_pmm_api",
            new=AsyncMock(return_value=mock_api),
        )
        mock_session_maker = mocker.patch("app.sep.celery.get_async_session_maker")

        await _backup_alert_config()

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
            "app.sep.plugins.alerts.deps.get_pmm_api",
            new=AsyncMock(return_value=mock_api),
        )
        _patch_session(mocker, session)

        await _backup_alert_config()

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
            "app.sep.plugins.alerts.deps.get_pmm_api",
            new=AsyncMock(return_value=mock_api),
        )
        _patch_session(mocker, session)

        await _backup_alert_config()

        results = await AlertBackupManager.list(session)
        assert len(results) == retention

    @pytest.mark.asyncio
    async def test_backup_skips_duplicate(self, session, mocker) -> None:
        """Assert no new backup is created when data is unchanged."""
        mock_api = _mock_pmm_api()
        _patch_pmm_settings(mocker)
        mocker.patch(
            "app.sep.plugins.alerts.deps.get_pmm_api",
            new=AsyncMock(return_value=mock_api),
        )
        _patch_session(mocker, session)

        await _backup_alert_config()
        results_after_first = await AlertBackupManager.list(session)
        assert len(results_after_first) == 1

        await _backup_alert_config()
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
            "app.sep.plugins.alerts.deps.get_pmm_api",
            new=AsyncMock(return_value=mock_api),
        )
        _patch_session(mocker, session)

        await _backup_alert_config()

        mock_api.list_contact_points = AsyncMock(
            return_value=[
                ContactPoint(uid="cp2", name="CP 2", type="slack"),
                ContactPoint(uid="cp1", name="CP 1", type="email"),
            ]
        )

        await _backup_alert_config()
        results = await AlertBackupManager.list(session)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_backup_saves_when_data_differs(self, session, mocker) -> None:
        """Assert a new backup is created when data changes."""
        mock_api = _mock_pmm_api()
        _patch_pmm_settings(mocker)
        mocker.patch(
            "app.sep.plugins.alerts.deps.get_pmm_api",
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

        await _backup_alert_config()

        results = await AlertBackupManager.list(session)
        assert len(results) == EXPECTED_BACKUP_COUNT_AFTER_DIFF


def _write_self_signed_pem(
    path: Path,
    *,
    not_valid_after: datetime,
    not_valid_before: datetime | None = None,
    common_name: str = "test",
) -> None:
    """Build and write a minimal self-signed PEM certificate for tests."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, common_name)])
    nvb = not_valid_before or (ANCHOR - timedelta(days=1))
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(nvb)
        .not_valid_after(not_valid_after)
        .sign(key, hashes.SHA256())
    )
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _nomad_config_for_paths(
    *,
    ca: Path | None = None,
    cert: Path | None = None,
    warn_days: int = 7,
) -> NomadExecutor:
    """Return a NomadExecutor config object for cert-expiry task tests."""
    return NomadExecutor(
        endpoint="http://127.0.0.1:4646",
        verify_ssl=False,
        ssl_cafile=ca,
        ssl_certfile=cert,
        cert_expiry_warn_days=warn_days,
    )


class TestCheckNomadCertExpiry:
    """Test _check_nomad_cert_expiry and check_nomad_cert_expiry."""

    @pytest.mark.asyncio
    async def test_healthy_certs_call_resolve_not_trigger(
        self, mocker, tmp_path: Path
    ) -> None:
        """Assert long-lived CA and client PEMs call resolve and do not trigger."""
        ca = tmp_path / "ca.pem"
        cl = tmp_path / "client.pem"
        _write_self_signed_pem(
            ca, not_valid_after=ANCHOR + timedelta(days=30), common_name="ca"
        )
        _write_self_signed_pem(
            cl, not_valid_after=ANCHOR + timedelta(days=30), common_name="cl"
        )
        mocker.patch(
            "app.tasks.config.tasks_settings",
            MagicMock(NOMAD=_nomad_config_for_paths(ca=ca, cert=cl)),
        )
        mocker.patch("app.core.utils.utc_now", return_value=ANCHOR)
        mock_trigger = mocker.patch.object(
            AlertService, "trigger", new_callable=AsyncMock
        )
        mock_resolve = mocker.patch.object(
            AlertService, "resolve", new_callable=AsyncMock
        )

        await _check_nomad_cert_expiry()

        mock_trigger.assert_not_called()
        assert mock_resolve.call_count == EXPECTED_NOMAD_CERT_RESOLVE_CALLS
        called = {c.args[0] for c in mock_resolve.call_args_list}
        assert called == {
            f"nomad-cert-expiry:{ca.name}",
            f"nomad-cert-expiry:{cl.name}",
        }

    @pytest.mark.asyncio
    async def test_within_window_triggers_warning(self, mocker, tmp_path: Path) -> None:
        """Assert a cert within the warning window triggers WARNING."""
        ca = tmp_path / "w.pem"
        _write_self_signed_pem(
            ca, not_valid_after=ANCHOR + timedelta(days=7), common_name="w"
        )
        mocker.patch(
            "app.tasks.config.tasks_settings",
            MagicMock(NOMAD=_nomad_config_for_paths(ca=ca, cert=None)),
        )
        mocker.patch("app.core.utils.utc_now", return_value=ANCHOR)
        mock_trigger = mocker.patch.object(
            AlertService, "trigger", new_callable=AsyncMock
        )
        mocker.patch.object(AlertService, "resolve", new_callable=AsyncMock)

        await _check_nomad_cert_expiry()

        mock_trigger.assert_called_once()
        alert = mock_trigger.call_args[0][0]
        assert alert["severity"] is AlertSeverity.WARNING
        assert alert["dedup_key"] == f"nomad-cert-expiry:{ca.name}"
        assert "7 day" in alert["summary"]

    @pytest.mark.asyncio
    async def test_just_beyond_window_resolves_only(
        self, mocker, tmp_path: Path
    ) -> None:
        """Assert a cert just past the warning window only resolves and does not trigger."""
        ca = tmp_path / "ok.pem"
        _write_self_signed_pem(
            ca, not_valid_after=ANCHOR + timedelta(days=8), common_name="ok"
        )
        mocker.patch(
            "app.tasks.config.tasks_settings",
            MagicMock(NOMAD=_nomad_config_for_paths(ca=ca, cert=None)),
        )
        mocker.patch("app.core.utils.utc_now", return_value=ANCHOR)
        mock_trigger = mocker.patch.object(
            AlertService, "trigger", new_callable=AsyncMock
        )
        mock_resolve = mocker.patch.object(
            AlertService, "resolve", new_callable=AsyncMock
        )

        await _check_nomad_cert_expiry()

        mock_trigger.assert_not_called()
        mock_resolve.assert_called_once_with(f"nomad-cert-expiry:{ca.name}")

    @pytest.mark.asyncio
    async def test_expired_triggers_critical(self, mocker, tmp_path: Path) -> None:
        """Assert an expired cert triggers CRITICAL."""
        ca = tmp_path / "x.pem"
        _write_self_signed_pem(
            ca, not_valid_after=ANCHOR - timedelta(hours=1), common_name="x"
        )
        mocker.patch(
            "app.tasks.config.tasks_settings",
            MagicMock(NOMAD=_nomad_config_for_paths(ca=ca, cert=None)),
        )
        mocker.patch("app.core.utils.utc_now", return_value=ANCHOR)
        mock_trigger = mocker.patch.object(
            AlertService, "trigger", new_callable=AsyncMock
        )
        mock_resolve = mocker.patch.object(
            AlertService, "resolve", new_callable=AsyncMock
        )

        await _check_nomad_cert_expiry()

        mock_trigger.assert_called_once()
        mock_resolve.assert_not_called()
        alert = mock_trigger.call_args[0][0]
        assert alert["severity"] is AlertSeverity.CRITICAL
        assert alert["dedup_key"] == f"nomad-cert-expiry:{ca.name}"

    @pytest.mark.asyncio
    async def test_path_read_bytes_oserror_logs_and_skips(
        self, mocker, tmp_path: Path
    ) -> None:
        """Assert OSError from read_bytes is logged and does not raise."""
        ca = tmp_path / "io.pem"
        ca.write_bytes(b"unused")
        mocker.patch(
            "app.tasks.config.tasks_settings",
            MagicMock(NOMAD=_nomad_config_for_paths(ca=ca, cert=None)),
        )
        mocker.patch("app.core.utils.utc_now", return_value=ANCHOR)
        mocker.patch.object(
            Path, "read_bytes", side_effect=OSError("simulated read failure")
        )
        mock_trigger = mocker.patch.object(
            AlertService, "trigger", new_callable=AsyncMock
        )
        mock_resolve = mocker.patch.object(
            AlertService, "resolve", new_callable=AsyncMock
        )
        log_warning = mocker.patch(f"{MODULE}.logger.warning")

        await _check_nomad_cert_expiry()

        log_warning.assert_called()
        assert "Could not read" in str(log_warning.call_args)
        mock_trigger.assert_not_called()
        mock_resolve.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_pem_valueerror_logs_and_skips(
        self, mocker, tmp_path: Path
    ) -> None:
        """Assert non-PEM file bytes log and ValueError is handled (no raise)."""
        bad = tmp_path / "not-pem.pem"
        bad.write_bytes(b"not a pem")
        mocker.patch(
            "app.tasks.config.tasks_settings",
            MagicMock(NOMAD=_nomad_config_for_paths(ca=bad, cert=None)),
        )
        mocker.patch("app.core.utils.utc_now", return_value=ANCHOR)
        mocker.patch.object(AlertService, "trigger", new_callable=AsyncMock)
        mocker.patch.object(AlertService, "resolve", new_callable=AsyncMock)
        log_warning = mocker.patch(f"{MODULE}.logger.warning")

        await _check_nomad_cert_expiry()

        log_warning.assert_called()
        assert "Could not parse" in str(log_warning.call_args)

    @pytest.mark.asyncio
    async def test_missing_file_warns_and_skips(self, mocker, tmp_path: Path) -> None:
        """Assert a missing PEM path logs a warning and does not call the alert service."""
        mock_nomad = MagicMock()
        mock_nomad.ssl_cafile = tmp_path / "missing.pem"
        mock_nomad.ssl_certfile = None
        mock_nomad.cert_expiry_warn_days = 7
        mocker.patch("app.tasks.config.tasks_settings", MagicMock(NOMAD=mock_nomad))
        mocker.patch("app.core.utils.utc_now", return_value=ANCHOR)
        mock_trigger = mocker.patch.object(
            AlertService, "trigger", new_callable=AsyncMock
        )
        mock_resolve = mocker.patch.object(
            AlertService, "resolve", new_callable=AsyncMock
        )
        log_warning = mocker.patch(f"{MODULE}.logger.warning")

        await _check_nomad_cert_expiry()

        log_warning.assert_called()
        assert "Could not read" in str(log_warning.call_args)
        mock_trigger.assert_not_called()
        mock_resolve.assert_not_called()

    def test_celery_entrypoint_uses_event_loop(self, mocker) -> None:
        """Assert check_nomad_cert_expiry runs the async helper via the event loop."""
        from app.celery import celery as app_celery

        coro = MagicMock()
        mock_check = MagicMock(return_value=coro)
        mocker.patch(f"{MODULE}._check_nomad_cert_expiry", mock_check)
        mocker.patch.object(
            app_celery.loop,
            "run_until_complete",
            autospec=True,
        )

        check_nomad_cert_expiry()
        app_celery.loop.run_until_complete.assert_called_once_with(coro)
