"""Tests for the pgBackRest payload script."""

import datetime
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PAYLOAD_PATH = str(
    Path(__file__).resolve().parents[5] / "app" / "sep" / "apps" / "backup_pg" / "payload"
)


def _load_payload_module():
    """Load the pgBackRest payload script as an importable module."""
    loader = SourceFileLoader("backup_pg_payload_module", PAYLOAD_PATH)
    spec = importlib.util.spec_from_loader("backup_pg_payload_module", loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def payload_module():
    return _load_payload_module()


def _make_pgbackrest(payload_module, tmp_path, **overrides):
    (tmp_path / "backup").mkdir(exist_ok=True)
    (tmp_path / "logs").mkdir(exist_ok=True)
    server_data = {
        "ALIAS": "test-pg",
        "BACKUP_DIR": str(tmp_path / "backup"),
        "LOGGING_DIR": str(tmp_path / "logs"),
    }
    server_data.update(overrides)
    return payload_module.PgBackRest(server_data, logger=MagicMock())


class TestPgBackRestConfigKeys:
    """Tests for PGBACKREST_-prefixed config key reads."""
    
    def test_reads_pgbackrest_prefixed_keys(self, payload_module, tmp_path):
        """A PgBackRest instance should read PGBACKREST_-prefixed keys."""
        pg = _make_pgbackrest(
            payload_module,
            tmp_path,
            PGBACKREST_DATADIR="/custom/datadir",
            PGBACKREST_RETENTION_FULL=3,
            PGBACKREST_RETENTION_ARCHIVE=5,
            PGBACKREST_INCREMENTAL_CYCLE="4",
        )
        assert pg.pg_datadir == "/custom/datadir"
        assert pg.pg_retention_full == 3
        assert pg.pg_retention_archive == 5
        assert pg.pg_incremental_cycle == "4"


class TestIncrementalCycleValidation:
    """Tests for incremental-cycle normalization and validation."""
    
    def test_weekly_normalizes_to_1(self, payload_module, tmp_path):
        """A "weekly" cycle should normalize to "1" (Monday)."""
        pg = _make_pgbackrest(payload_module, tmp_path, PGBACKREST_INCREMENTAL_CYCLE="weekly")
        assert pg.pg_incremental_cycle == "1"

    def test_invalid_cycle_raises_backup_error(self, payload_module, tmp_path):
        """An invalid cycle value should raise a BackupError."""
        with pytest.raises(payload_module.BackupError):
            _make_pgbackrest(payload_module, tmp_path, PGBACKREST_INCREMENTAL_CYCLE="bogus")


class TestFullBackupDecision:
    """Tests for the FULL-backup weekday decision in _run_backup_command()."""
    
    def test_matching_weekday_triggers_full(self, payload_module, tmp_path):
        """A numeric cycle matching today's ISO weekday should trigger a FULL backup."""
        today_iso = datetime.datetime.today().isoweekday()
        pg = _make_pgbackrest(
            payload_module, tmp_path, PGBACKREST_INCREMENTAL_CYCLE=str(today_iso)
        )
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value.returncode = 0
            pg._run_backup_command()
            cmd = mock_popen.call_args[0][0]
        assert "--type=full" in cmd

    def test_non_matching_weekday_does_not_trigger_full(self, payload_module, tmp_path):
        """A numeric cycle not matching today's ISO weekday should not trigger a FULL backup."""
        today_iso = datetime.datetime.today().isoweekday()
        other_day = "1" if today_iso != 1 else "2"
        pg = _make_pgbackrest(
            payload_module, tmp_path, PGBACKREST_INCREMENTAL_CYCLE=other_day
        )
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value.returncode = 0
            pg._run_backup_command()
            cmd = mock_popen.call_args[0][0]
        assert "--type=full" not in cmd

    def test_daily_always_triggers_full(self, payload_module, tmp_path):
        """A "daily" cycle should always trigger a FULL backup."""
        pg = _make_pgbackrest(payload_module, tmp_path, PGBACKREST_INCREMENTAL_CYCLE="daily")
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value.returncode = 0
            pg._run_backup_command()
            cmd = mock_popen.call_args[0][0]
        assert "--type=full" in cmd


class TestCreateStanzaRetentionCoercion:
    """Tests for str() coercion of retention values in _create_stanza()."""
    
    def test_int_retention_values_do_not_raise(self, payload_module, tmp_path):
        """Integer retention values should not raise a TypeError in configparser."""
        cfg_file = tmp_path / "pgbackrest.conf"
        pg = _make_pgbackrest(
            payload_module,
            tmp_path,
            PGBACKREST_CONFIG_FILE=str(cfg_file),
            PGBACKREST_RETENTION_FULL=3,
            PGBACKREST_RETENTION_ARCHIVE=5,
        )
        with patch("subprocess.check_output") as mock_check_output:
            mock_check_output.return_value = b"OK"
            pg._create_stanza()
        content = cfg_file.read_text()
        assert "repo1-retention-full = 3" in content
        assert "repo1-retention-archive = 5" in content
