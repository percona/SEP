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

import getpass
import pwd
import subprocess
from pathlib import Path

import pytest

from app.sep.apps.backup_mongo.pbm_creds_common import (
    _backup_user_home,
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


def _stub_passwd(monkeypatch, homes: dict[str, str]) -> list[str]:
    """Stub ``pwd.getpwnam`` with a name-to-home table and record the names looked up.

    :param monkeypatch: The pytest monkeypatch fixture.
    :param homes: The passwd entries to serve, keyed by user name. A name absent
        from the table raises ``KeyError``, as the real ``getpwnam`` does.
    :return: The list the stub appends each looked-up name to.
    """
    looked_up: list[str] = []

    def _getpwnam(name: str) -> pwd.struct_passwd:
        looked_up.append(name)
        if name not in homes:
            raise KeyError(f"getpwnam(): name not found: {name}")
        return pwd.struct_passwd((name, "x", 0, 0, "", homes[name], "/bin/sh"))

    monkeypatch.setattr(pwd, "getpwnam", _getpwnam)
    return looked_up


class TestBackupUserHome:
    """Cover the passwd-based home resolution the collector directory falls back to."""

    def test_prefers_percona_backup_user(self, monkeypatch) -> None:
        """Resolve ``PERCONA_BACKUP_USER`` ahead of ``SUDO_USER`` and the login name."""
        monkeypatch.setenv("PERCONA_BACKUP_USER", "pbm")
        monkeypatch.setenv("SUDO_USER", "operator")
        _stub_passwd(monkeypatch, {"pbm": "/home/pbm", "operator": "/home/operator"})
        assert _backup_user_home() == Path("/home/pbm")

    def test_falls_back_to_sudo_user(self, monkeypatch) -> None:
        """Resolve ``SUDO_USER`` when no explicit backup user is configured."""
        monkeypatch.delenv("PERCONA_BACKUP_USER", raising=False)
        monkeypatch.setenv("SUDO_USER", "operator")
        _stub_passwd(monkeypatch, {"operator": "/home/operator"})
        assert _backup_user_home() == Path("/home/operator")

    def test_falls_back_to_login_name(self, monkeypatch) -> None:
        """Resolve the login name when neither override is set."""
        monkeypatch.delenv("PERCONA_BACKUP_USER", raising=False)
        monkeypatch.delenv("SUDO_USER", raising=False)
        monkeypatch.setattr(getpass, "getuser", lambda: "runner")
        _stub_passwd(monkeypatch, {"runner": "/home/runner"})
        assert _backup_user_home() == Path("/home/runner")

    def test_ignores_home_env(self, monkeypatch) -> None:
        """Read the home from passwd, never from ``$HOME``.

        Under ``sudo`` the two disagree. Honouring ``$HOME`` would put this
        payload's ``.prom`` files somewhere PMM never scrapes, while the
        MySQL/PostgreSQL payloads -- which resolve through passwd -- land
        correctly, and the mismatch is silent because the write then no-ops.
        """
        monkeypatch.setenv("HOME", "/root")
        monkeypatch.setenv("PERCONA_BACKUP_USER", "pbm")
        _stub_passwd(monkeypatch, {"pbm": "/home/pbm"})
        assert _backup_user_home() == Path("/home/pbm")

    def test_returns_none_when_user_not_in_passwd(self, monkeypatch) -> None:
        """Return ``None`` rather than raising when the user has no passwd entry."""
        monkeypatch.setenv("PERCONA_BACKUP_USER", "ghost")
        _stub_passwd(monkeypatch, {})
        assert _backup_user_home() is None

    def test_returns_none_when_login_name_unresolvable(self, monkeypatch) -> None:
        """Return ``None`` when even the login name cannot be determined."""
        monkeypatch.delenv("PERCONA_BACKUP_USER", raising=False)
        monkeypatch.delenv("SUDO_USER", raising=False)

        def _no_user() -> str:
            raise OSError("no login name")

        monkeypatch.setattr(getpass, "getuser", _no_user)
        assert _backup_user_home() is None

    def test_returns_none_for_relative_home(self, monkeypatch) -> None:
        """Return ``None`` for a relative passwd home, never a payload-cwd path."""
        monkeypatch.setenv("PERCONA_BACKUP_USER", "pbm")
        _stub_passwd(monkeypatch, {"pbm": "relative/home"})
        assert _backup_user_home() is None


class TestTextfileCollectorDir:
    """Cover the collector-directory resolution."""

    def test_honors_env_override(self, monkeypatch) -> None:
        """Honour ``PERCONA_BACKUP_TEXTFILE_COLLECTOR_DIR`` verbatim."""
        monkeypatch.setenv("PERCONA_BACKUP_TEXTFILE_COLLECTOR_DIR", "/custom/dir")
        assert _textfile_collector_dir() == Path("/custom/dir")

    def test_falls_back_to_backup_user_home(self, monkeypatch) -> None:
        """Fall back to the PMM low-resolution collector under the backup user's home."""
        monkeypatch.delenv("PERCONA_BACKUP_TEXTFILE_COLLECTOR_DIR", raising=False)
        monkeypatch.setenv("PERCONA_BACKUP_USER", "pbm")
        _stub_passwd(monkeypatch, {"pbm": "/home/pbm"})
        assert _textfile_collector_dir() == Path(
            "/home/pbm/pmm/collectors/textfile-collector/low-resolution"
        )

    def test_returns_none_when_home_unresolvable(self, monkeypatch) -> None:
        """Return ``None`` -- not a relative path -- when no home can be resolved."""
        monkeypatch.delenv("PERCONA_BACKUP_TEXTFILE_COLLECTOR_DIR", raising=False)
        monkeypatch.setenv("PERCONA_BACKUP_USER", "ghost")
        _stub_passwd(monkeypatch, {})
        assert _textfile_collector_dir() is None


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

    def test_escapes_carriage_return(self) -> None:
        """Escape a carriage return too, matching what the filename sanitiser strips."""
        assert _escape_label_value("a\rb") == "a\\rb"

    def test_leaves_ordinary_aliases_untouched(self) -> None:
        """Leave an ordinary hostname untouched when escaping."""
        assert _escape_label_value("db-host.example.com") == "db-host.example.com"

    def test_filename_strips_path_and_control_chars(self) -> None:
        """Collapse path separators, NUL and newlines so the write stays in-dir."""
        assert _safe_filename_alias("a/b") == "a_b"
        assert _safe_filename_alias("a\x00b\nc\rd") == "a_b_c_d"

    @pytest.mark.parametrize(
        ("write", "prefix"),
        [
            pytest.param(
                lambda: write_backup_status("PBM Logical", 0), "", id="status"
            ),
            pytest.param(
                lambda: write_backup_enabled("PBM Logical"), "driver.", id="enabled"
            ),
        ],
    )
    def test_writers_escape_label_and_sanitise_filename(
        self, write, prefix: str, tmp_path, monkeypatch
    ) -> None:
        """Escape labels and sanitise the filename for a quote/slash-bearing target.

        Both writers reach the same two helpers off the same host-controlled
        ``NOMAD_META_TARGET``, so both are driven through the real env seam.
        """
        monkeypatch.setenv("PERCONA_BACKUP_TEXTFILE_COLLECTOR_DIR", str(tmp_path))
        monkeypatch.setenv("NOMAD_META_TARGET", 'ev/il"host')
        write()
        name, body = _read_single_prom(tmp_path)
        assert name == f'{prefix}backup.PBM Logical.ev_il"host.prom'
        assert (tmp_path / name).parent == tmp_path
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

        def _deny(*_args, **_kwargs) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(Path, "write_text", _deny)
        write_backup_status("PBM Logical", 0)
        assert "Failed to write textfile-collector metric" in capsys.readouterr().err

    def test_leaves_no_temp_file_behind(self, collector) -> None:
        """Publish through a temp file that the rename consumes, leaving only the ``.prom``."""
        write_backup_status("PBM Logical", 0)
        assert sorted(p.name for p in collector.iterdir()) == [
            "backup.PBM Logical.host-1.prom"
        ]

    def test_partial_write_leaves_previous_prom_intact(
        self, collector, monkeypatch
    ) -> None:
        """Keep the last good ``.prom`` when a later write dies part-way through.

        This is what the temp file plus rename buys. Writing straight to the
        published path would truncate it first, so the collector would scrape a
        half-written file -- and reject every metric in it -- until the next run.
        """
        write_backup_status("PBM Logical", 0)
        target = collector / "backup.PBM Logical.host-1.prom"
        previous = target.read_text(encoding="utf-8")
        real_write_text = Path.write_text

        def _half_then_fail(self: Path, data: str, **kwargs) -> None:
            real_write_text(self, data[: len(data) // 2], **kwargs)
            raise OSError("disk full")

        monkeypatch.setattr(Path, "write_text", _half_then_fail)
        write_backup_status("PBM Logical", 1)
        assert target.read_text(encoding="utf-8") == previous
        # The half-written body landed on the temp path, not the published one.
        assert (collector / f"{target.name}.tmp").read_text(
            encoding="utf-8"
        ) != previous

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
        """Assert the block between a payload's markers equals ``textfile_source()``."""
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

    @staticmethod
    def _fake_run_failure(*_args, **_kwargs):
        """Raise ``CalledProcessError`` to stand in for a failed snapshot run."""
        raise subprocess.CalledProcessError(
            1, ["bash", "/usr/local/bin/pbm_create_snapshot"]
        )

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
        run_payload(_payload_path("pbm_snapshot_payload"))
        body = _read_prom(tmp_path, "backup.PBM Snapshot.host-1.prom")
        assert 'msp_backup_status{type="PBM Snapshot", alias="host-1"} 1' in body

    def test_script_failure_writes_status_one_without_aborting(
        self, monkeypatch, tmp_path
    ) -> None:
        """Record status ``1`` without aborting when the snapshot script exits non-zero."""
        monkeypatch.setenv("PERCONA_BACKUP_TEXTFILE_COLLECTOR_DIR", str(tmp_path))
        monkeypatch.setenv("NOMAD_META_TARGET", "host-1")
        monkeypatch.setenv("PBM_CREATE_SNAPSHOT", "/usr/local/bin/pbm_create_snapshot")
        monkeypatch.setattr(subprocess, "run", self._fake_run_failure)
        run_payload(_payload_path("pbm_snapshot_payload"))
        body = _read_prom(tmp_path, "backup.PBM Snapshot.host-1.prom")
        assert 'msp_backup_status{type="PBM Snapshot", alias="host-1"} 1' in body
