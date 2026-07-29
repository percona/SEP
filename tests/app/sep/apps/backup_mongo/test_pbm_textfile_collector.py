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

"""Define tests for the PBM textfile-collector metric writer across the Mongo payloads."""

import builtins
import os
import subprocess
from pathlib import Path

import pytest

from app.sep.apps.backup_mongo.pbm_creds_common import (
    _escape_label_value,
    _metric_alias,
    _safe_filename_alias,
    _textfile_collector_dir,
    TEXTFILE_BEGIN,
    TEXTFILE_END,
    textfile_source,
    write_backup_enabled,
    write_backup_status,
)
from tests.app.sep.apps.backup_mongo._payload_codegen import (
    assignment_line,
    GEN,
    payloads_with,
    region_between,
)
from tests.app.sep.apps.backup_mongo.pbm_payload_exec import FakePopen, run_payload

# The three backup payloads that emit stale-backup metrics. Restore payloads are
# out of scope, so they do not carry the textfile-collector region.
_EXPECTED_TEXTFILE_PAYLOADS = {
    "pbm_logical_payload",
    "pbm_physical_payload",
    "pbm_snapshot_payload",
}

# Each backup payload's distinct, stable ``type`` label. The values must be
# distinct so the three payloads' ``.prom`` files and series never collide.
_EXPECTED_METRIC_TYPES = {
    "pbm_logical_payload": "PBM Logical",
    "pbm_physical_payload": "PBM Physical",
    "pbm_snapshot_payload": "PBM Snapshot",
}

# The two aborting backup payloads (logical/physical) that exec ``pbm backup``
# via ``subprocess.Popen`` and exit non-zero on failure.
_ABORTING_PAYLOADS = {
    "pbm_logical_payload": "PBM Logical",
    "pbm_physical_payload": "PBM Physical",
}


def _textfile_payloads() -> list[Path]:
    """Return the payloads carrying the textfile-collector region marker."""
    return payloads_with(TEXTFILE_BEGIN)


def _payload_path(name: str) -> Path:
    """Return the path of the named textfile-collector payload."""
    return next(p for p in _textfile_payloads() if p.name == name)


def _read_single_prom(collector_dir: Path) -> tuple[str, str]:
    """Return the ``(name, contents)`` of the one ``.prom`` file in ``collector_dir``."""
    proms = sorted(collector_dir.glob("*.prom"))
    assert len(proms) == 1, f"expected one .prom file, found {proms}"
    return proms[0].name, proms[0].read_text(encoding="utf-8")


def _read_prom(collector_dir: Path, name: str) -> str:
    """Return the contents of the named ``.prom`` file under ``collector_dir``."""
    return (collector_dir / name).read_text(encoding="utf-8")


class TestTextfileCollectorDir:
    """Cover the collector-directory resolution."""

    def test_honors_env_override(self, monkeypatch) -> None:
        """Honour ``PERCONA_BACKUP_TEXTFILE_COLLECTOR_DIR`` verbatim."""
        monkeypatch.setenv("PERCONA_BACKUP_TEXTFILE_COLLECTOR_DIR", "/custom/dir")
        assert _textfile_collector_dir() == "/custom/dir/"

    def test_preserves_trailing_slash(self, monkeypatch) -> None:
        """Do not double a trailing slash already present in the override."""
        monkeypatch.setenv("PERCONA_BACKUP_TEXTFILE_COLLECTOR_DIR", "/custom/dir/")
        assert _textfile_collector_dir() == "/custom/dir/"

    def test_falls_back_to_home(self, monkeypatch) -> None:
        """Fall back to the PMM low-resolution collector under ``$HOME``."""
        monkeypatch.delenv("PERCONA_BACKUP_TEXTFILE_COLLECTOR_DIR", raising=False)
        monkeypatch.setenv("HOME", "/home/pbm")
        assert _textfile_collector_dir() == (
            "/home/pbm/pmm/collectors/textfile-collector/low-resolution/"
        )

    def test_returns_empty_when_home_unresolvable(self, monkeypatch) -> None:
        """Return ``""`` -- not a relative path -- when no home can be resolved."""
        monkeypatch.delenv("PERCONA_BACKUP_TEXTFILE_COLLECTOR_DIR", raising=False)
        monkeypatch.setattr(os.path, "expanduser", lambda _path: "~")
        assert _textfile_collector_dir() == ""


class TestMetricAlias:
    """Cover the alias resolved from ``NOMAD_META_TARGET``."""

    def test_reads_target(self, monkeypatch) -> None:
        """Return the host identity Nomad sets as ``NOMAD_META_TARGET``."""
        monkeypatch.setenv("NOMAD_META_TARGET", "target-host")
        assert _metric_alias() == "target-host"

    def test_empty_when_target_unset(self, monkeypatch) -> None:
        """Return ``""`` when the target is unset, so a missing label never aborts."""
        monkeypatch.delenv("NOMAD_META_TARGET", raising=False)
        assert _metric_alias() == ""


class TestLabelAndFilenameSafety:
    """Cover the label escaping and filename sanitisation for host-controlled aliases."""

    def test_escapes_backslash_quote_and_newline(self) -> None:
        """Escape the exposition-breaking characters in a label value."""
        assert _escape_label_value(r'a"b\c') == r"a\"b\\c"
        assert _escape_label_value("a\nb") == "a\\nb"

    def test_leaves_ordinary_aliases_untouched(self) -> None:
        """Leave an ordinary hostname untouched when escaping."""
        assert _escape_label_value("db-host.example.com") == "db-host.example.com"

    def test_filename_strips_path_and_control_chars(self) -> None:
        """Collapse path separators, NUL and newlines so the write stays in-dir."""
        assert _safe_filename_alias("a/b") == "a_b"
        assert _safe_filename_alias("a\x00b\nc\rd") == "a_b_c_d"

    def test_status_escapes_label_and_sanitises_filename(
        self, tmp_path, monkeypatch
    ) -> None:
        """Escape labels and sanitise the filename for a quote/slash-bearing target."""
        monkeypatch.setenv("PERCONA_BACKUP_TEXTFILE_COLLECTOR_DIR", str(tmp_path))
        # Drive the real seam: the alias production reads NOMAD_META_TARGET.
        monkeypatch.setenv("NOMAD_META_TARGET", 'ev/il"host')
        write_backup_status("PBM Logical", 0)
        name, body = _read_single_prom(tmp_path)
        # The filename never escapes the collector dir and carries no raw quote/slash.
        assert "/" not in name.replace(".prom", "")
        assert (tmp_path / name).parent == tmp_path
        # The label value is escaped, so the exposition line is well-formed.
        assert r'alias="ev/il\"host"' in body


class TestWriteBackupStatus:
    """Cover the ``msp_backup_status`` / ``msp_backup_last_report_ts`` writer."""

    @pytest.fixture
    def collector(self, tmp_path, monkeypatch) -> Path:
        """Point the collector dir at a tmp dir and set the target host alias."""
        monkeypatch.setenv("PERCONA_BACKUP_TEXTFILE_COLLECTOR_DIR", str(tmp_path))
        monkeypatch.setenv("NOMAD_META_TARGET", "host-1")
        return tmp_path

    def test_writes_success_status(self, collector) -> None:
        """Write status ``0`` with ``type``/``alias`` labels and a fresh timestamp."""
        write_backup_status("PBM Logical", 0)
        name, body = _read_single_prom(collector)
        assert name == "backup.PBM Logical.host-1.prom"
        assert "# HELP msp_backup_status The status of the job" in body
        assert "# TYPE msp_backup_status Untyped" in body
        assert "# HELP msp_backup_last_report_ts The Last Report Time" in body
        assert "# TYPE msp_backup_last_report_ts Untyped" in body
        assert 'msp_backup_status{type="PBM Logical", alias="host-1"} 0' in body
        ts_line = next(
            line
            for line in body.splitlines()
            if line.startswith("msp_backup_last_report_ts")
        )
        assert ts_line.startswith(
            'msp_backup_last_report_ts{type="PBM Logical", alias="host-1"} '
        )
        assert ts_line.rsplit(" ", 1)[1].isdigit()

    def test_writes_failure_status(self, collector) -> None:
        """Write status ``1`` on the failure path (matching PG and the report map)."""
        write_backup_status("PBM Physical", 1)
        _name, body = _read_single_prom(collector)
        assert 'msp_backup_status{type="PBM Physical", alias="host-1"} 1' in body

    def test_missing_collector_dir_writes_nothing(self, tmp_path, monkeypatch) -> None:
        """Skip the write (no file, no error) when the collector dir is absent."""
        absent = tmp_path / "does-not-exist"
        monkeypatch.setenv("PERCONA_BACKUP_TEXTFILE_COLLECTOR_DIR", str(absent))
        monkeypatch.setenv("NOMAD_META_TARGET", "host-1")
        write_backup_status("PBM Logical", 0)
        assert not absent.exists()

    def test_write_error_is_swallowed(self, collector, monkeypatch, capsys) -> None:
        """Swallow a write error so metric emission never aborts the backup."""

        def _deny(*_args, **_kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(builtins, "open", _deny)
        # Must not raise.
        write_backup_status("PBM Logical", 0)
        assert "Failed to write textfile-collector metric" in capsys.readouterr().err

    def test_empty_alias_still_writes(self, tmp_path, monkeypatch) -> None:
        """Fall back to an empty alias label (never abort) when none is resolved."""
        monkeypatch.setenv("PERCONA_BACKUP_TEXTFILE_COLLECTOR_DIR", str(tmp_path))
        monkeypatch.delenv("NOMAD_META_TARGET", raising=False)
        write_backup_status("PBM Logical", 0)
        _name, body = _read_single_prom(tmp_path)
        assert 'msp_backup_status{type="PBM Logical", alias=""} 0' in body


class TestWriteBackupEnabled:
    """Cover the ``msp_backup_enabled`` writer (the join's load-bearing series)."""

    def test_writes_enabled(self, tmp_path, monkeypatch) -> None:
        """Write ``msp_backup_enabled == 1`` with ``type``/``alias`` labels."""
        monkeypatch.setenv("PERCONA_BACKUP_TEXTFILE_COLLECTOR_DIR", str(tmp_path))
        monkeypatch.setenv("NOMAD_META_TARGET", "host-1")
        write_backup_enabled("PBM Snapshot")
        name, body = _read_single_prom(tmp_path)
        assert name == "driver.backup.PBM Snapshot.host-1.prom"
        assert "# HELP msp_backup_enabled The status of the cron" in body
        assert "# TYPE msp_backup_enabled Untyped" in body
        assert 'msp_backup_enabled{type="PBM Snapshot", alias="host-1"} 1' in body

    def test_missing_collector_dir_writes_nothing(self, tmp_path, monkeypatch) -> None:
        """Skip the enable write when the collector dir is absent."""
        absent = tmp_path / "nope"
        monkeypatch.setenv("PERCONA_BACKUP_TEXTFILE_COLLECTOR_DIR", str(absent))
        monkeypatch.setenv("NOMAD_META_TARGET", "host-1")
        write_backup_enabled("PBM Logical")
        assert not absent.exists()


class TestTextfileRegionSync:
    """Assert the shared metric-writer region is embedded byte-identically."""

    def test_discovers_exactly_the_backup_payloads(self) -> None:
        """Discover exactly the three backup payloads carrying the region."""
        found = {path.name for path in _textfile_payloads()}
        assert found == _EXPECTED_TEXTFILE_PAYLOADS

    @pytest.mark.parametrize("payload", _textfile_payloads(), ids=lambda p: p.name)
    def test_region_matches_canonical(self, payload: Path) -> None:
        """The block between a payload's markers equals ``textfile_source()``."""
        region = region_between(
            payload.read_text(encoding="utf-8"), TEXTFILE_BEGIN, TEXTFILE_END
        )
        assert region == textfile_source()

    @pytest.mark.parametrize("payload", _textfile_payloads(), ids=lambda p: p.name)
    def test_render_is_idempotent(self, payload: Path) -> None:
        """Re-rendering an in-sync payload's region is a no-op."""
        current = payload.read_text(encoding="utf-8")
        rendered = GEN.render(current, textfile_source(), TEXTFILE_BEGIN, TEXTFILE_END)
        assert rendered == current


class TestPayloadCallSites:
    """Assert each payload wires the metric writer into its backup flow."""

    @pytest.mark.parametrize(
        ("payload_name", "expected_type"), sorted(_EXPECTED_METRIC_TYPES.items())
    )
    def test_distinct_metric_type(self, payload_name: str, expected_type: str) -> None:
        """Require each payload to declare its own distinct, stable ``PBM_METRIC_TYPE``."""
        payload = _payload_path(payload_name)
        line = assignment_line(payload.read_text(encoding="utf-8"), "PBM_METRIC_TYPE")
        assert line == f'PBM_METRIC_TYPE = "{expected_type}"'

    def test_snapshot_stays_non_aborting(self) -> None:
        """Keep swallowing failure -- the snapshot payload must not abort (no ``sys.exit``)."""
        text = _payload_path("pbm_snapshot_payload").read_text(encoding="utf-8")
        assert "sys.exit" not in text
        # A missing PBM_CREATE_SNAPSHOT still records a failure without aborting.
        assert "except (OSError, KeyError)" in text


def _drive_aborting_payload(
    monkeypatch,
    tmp_path,
    *,
    returncode: int = 0,
    with_creds: bool = True,
) -> None:
    """Wire the env and a stubbed ``Popen`` to exec a logical/physical payload.

    Point the collector dir and Nomad target at a tmp dir, and stub
    ``subprocess.Popen`` with a :class:`FakePopen` reporting ``returncode``. When
    ``with_creds`` is false, both the config and ``$HOME`` are unset so the
    credential preflight aborts via ``sys.exit`` before the backup runs.

    :param monkeypatch: The pytest monkeypatch fixture.
    :param tmp_path: The pytest tmp_path used as the collector dir.
    :param returncode: The exit code the stubbed ``pbm backup`` reports.
    :param with_creds: Provide a resolvable credentials file when true.
    """
    monkeypatch.setenv("PERCONA_BACKUP_TEXTFILE_COLLECTOR_DIR", str(tmp_path))
    monkeypatch.setenv("NOMAD_META_TARGET", "host-1")
    monkeypatch.setenv("NOMAD_TASK_DIR", str(tmp_path))
    monkeypatch.delenv("NOMAD_META_CONFIG", raising=False)
    if with_creds:
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".mongodb_uri").write_text("mongodb://localhost:27017/")
    else:
        monkeypatch.delenv("HOME", raising=False)
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda cmd, *a, **kw: FakePopen(cmd, *a, returncode=returncode, **kw),
    )


class TestAbortingPayloadStatusByExitPath:
    """Exec the logical/physical payloads and assert the status emitted per exit path.

    Driving the real payload once per exit path pins the *value* written, so an
    inverted literal -- ``1`` on the success path or ``0`` on the failure path --
    fails here rather than slipping past a source-text presence check.
    """

    @pytest.mark.parametrize(
        ("payload_name", "metric_type"), sorted(_ABORTING_PAYLOADS.items())
    )
    def test_success_writes_status_zero(
        self, payload_name: str, metric_type: str, monkeypatch, tmp_path
    ) -> None:
        """Write status ``0`` when the backup command succeeds."""
        _drive_aborting_payload(monkeypatch, tmp_path, returncode=0)
        run_payload(_payload_path(payload_name))
        body = _read_prom(tmp_path, f"backup.{metric_type}.host-1.prom")
        assert f'msp_backup_status{{type="{metric_type}", alias="host-1"}} 0' in body

    @pytest.mark.parametrize(
        ("payload_name", "metric_type"), sorted(_ABORTING_PAYLOADS.items())
    )
    def test_command_failure_writes_status_one(
        self, payload_name: str, metric_type: str, monkeypatch, tmp_path
    ) -> None:
        """Write status ``1`` and exit non-zero when the backup command fails."""
        _drive_aborting_payload(monkeypatch, tmp_path, returncode=1)
        with pytest.raises(SystemExit) as exc_info:
            run_payload(_payload_path(payload_name))
        assert exc_info.value.code == 1
        body = _read_prom(tmp_path, f"backup.{metric_type}.host-1.prom")
        assert f'msp_backup_status{{type="{metric_type}", alias="host-1"}} 1' in body

    @pytest.mark.parametrize(
        ("payload_name", "metric_type"), sorted(_ABORTING_PAYLOADS.items())
    )
    def test_preflight_abort_writes_status_one(
        self, payload_name: str, metric_type: str, monkeypatch, tmp_path
    ) -> None:
        """Write status ``1`` when the credential preflight aborts before the backup."""
        _drive_aborting_payload(monkeypatch, tmp_path, with_creds=False)
        with pytest.raises(SystemExit):
            run_payload(_payload_path(payload_name))
        body = _read_prom(tmp_path, f"backup.{metric_type}.host-1.prom")
        assert f'msp_backup_status{{type="{metric_type}", alias="host-1"}} 1' in body

    @pytest.mark.parametrize(
        ("payload_name", "metric_type"), sorted(_ABORTING_PAYLOADS.items())
    )
    def test_enable_written_even_on_preflight_abort(
        self, payload_name: str, metric_type: str, monkeypatch, tmp_path
    ) -> None:
        """Emit the enabled metric before the backup try, so a preflight abort still shows it."""
        _drive_aborting_payload(monkeypatch, tmp_path, with_creds=False)
        with pytest.raises(SystemExit):
            run_payload(_payload_path(payload_name))
        body = _read_prom(tmp_path, f"driver.backup.{metric_type}.host-1.prom")
        assert f'msp_backup_enabled{{type="{metric_type}", alias="host-1"}} 1' in body


class TestSnapshotPayloadStatus:
    """Exec the snapshot payload and assert its status per outcome, never aborting."""

    @staticmethod
    def _fake_run_success(*_args, **_kwargs):
        """Return a completed-process stand-in for a clean snapshot run."""

        class _Result:
            stdout = ""
            stderr = ""
            returncode = 0

        return _Result()

    def test_success_writes_status_zero(self, monkeypatch, tmp_path) -> None:
        """Write status ``0`` when the snapshot script exits cleanly."""
        monkeypatch.setenv("PERCONA_BACKUP_TEXTFILE_COLLECTOR_DIR", str(tmp_path))
        monkeypatch.setenv("NOMAD_META_TARGET", "host-1")
        monkeypatch.setenv("PBM_CREATE_SNAPSHOT", "/usr/local/bin/pbm_create_snapshot")
        monkeypatch.setattr(subprocess, "run", self._fake_run_success)
        run_payload(_payload_path("pbm_snapshot_payload"))
        body = _read_prom(tmp_path, "backup.PBM Snapshot.host-1.prom")
        assert 'msp_backup_status{type="PBM Snapshot", alias="host-1"} 0' in body

    def test_missing_script_writes_status_one_without_aborting(
        self, monkeypatch, tmp_path
    ) -> None:
        """Record status ``1`` without aborting when ``PBM_CREATE_SNAPSHOT`` is unset."""
        monkeypatch.setenv("PERCONA_BACKUP_TEXTFILE_COLLECTOR_DIR", str(tmp_path))
        monkeypatch.setenv("NOMAD_META_TARGET", "host-1")
        monkeypatch.delenv("PBM_CREATE_SNAPSHOT", raising=False)
        # Must not raise -- the snapshot payload records failure and returns.
        run_payload(_payload_path("pbm_snapshot_payload"))
        body = _read_prom(tmp_path, "backup.PBM Snapshot.host-1.prom")
        assert 'msp_backup_status{type="PBM Snapshot", alias="host-1"} 1' in body
