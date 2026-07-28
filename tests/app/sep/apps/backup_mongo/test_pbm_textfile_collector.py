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


def _textfile_payloads() -> list[Path]:
    """Return the payloads carrying the textfile-collector region marker."""
    return payloads_with(TEXTFILE_BEGIN)


def _read_single_prom(collector_dir: Path) -> tuple[str, str]:
    """Return the ``(name, contents)`` of the one ``.prom`` file in ``collector_dir``."""
    proms = sorted(collector_dir.glob("*.prom"))
    assert len(proms) == 1, f"expected one .prom file, found {proms}"
    return proms[0].name, proms[0].read_text(encoding="utf-8")


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
    """Cover the alias resolved from ``NOMAD_META_CONFIG`` / ``NOMAD_META_TARGET``."""

    @pytest.fixture(autouse=True)
    def _clear_target(self, monkeypatch) -> None:
        """Clear the target fallback so each test controls both alias sources."""
        monkeypatch.delenv("NOMAD_META_TARGET", raising=False)

    def test_reads_alias_from_config(self, monkeypatch) -> None:
        """Return the ``alias`` value parsed out of the config YAML."""
        monkeypatch.setenv(
            "NOMAD_META_CONFIG", "alias: host-1\ncredentials_path: /secrets/uri"
        )
        assert _metric_alias() == "host-1"

    def test_prefers_config_alias_over_target(self, monkeypatch) -> None:
        """Prefer the config ``alias`` even when the target fallback is present."""
        monkeypatch.setenv("NOMAD_META_CONFIG", "alias: host-1")
        monkeypatch.setenv("NOMAD_META_TARGET", "target-host")
        assert _metric_alias() == "host-1"

    def test_falls_back_to_target_when_config_lacks_alias(self, monkeypatch) -> None:
        """Fall back to ``NOMAD_META_TARGET`` for tasks stored before the alias key."""
        monkeypatch.setenv("NOMAD_META_CONFIG", "credentials_path: /secrets/uri")
        monkeypatch.setenv("NOMAD_META_TARGET", "target-host")
        assert _metric_alias() == "target-host"

    def test_falls_back_to_target_when_config_unset(self, monkeypatch) -> None:
        """Fall back to ``NOMAD_META_TARGET`` when the config is absent entirely."""
        monkeypatch.delenv("NOMAD_META_CONFIG", raising=False)
        monkeypatch.setenv("NOMAD_META_TARGET", "target-host")
        assert _metric_alias() == "target-host"

    def test_falls_back_to_target_on_malformed_yaml(self, monkeypatch) -> None:
        """Fall back to the target (never raise) on unparseable config YAML."""
        monkeypatch.setenv("NOMAD_META_CONFIG", "key: [unclosed")
        monkeypatch.setenv("NOMAD_META_TARGET", "target-host")
        assert _metric_alias() == "target-host"

    def test_empty_when_no_source_resolves(self, monkeypatch) -> None:
        """Return ``""`` only when neither the config alias nor the target exists."""
        monkeypatch.delenv("NOMAD_META_CONFIG", raising=False)
        assert _metric_alias() == ""

    def test_empty_on_non_mapping_config(self, monkeypatch) -> None:
        """Fall through to the (absent) target when the config is a non-mapping."""
        monkeypatch.setenv("NOMAD_META_CONFIG", "- a\n- b")
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
        """A quote/slash-bearing alias yields valid labels and an in-dir filename."""
        monkeypatch.setenv("PERCONA_BACKUP_TEXTFILE_COLLECTOR_DIR", str(tmp_path))
        monkeypatch.delenv("NOMAD_META_TARGET", raising=False)
        monkeypatch.setenv("NOMAD_META_CONFIG", 'alias: "ev/il\\"host"')
        write_backup_status("PBM Logical", 0)
        name, body = _read_single_prom(tmp_path)
        # The filename never escapes the collector dir and carries no raw quote/slash.
        assert "/" not in name.replace(".prom", "")
        assert (tmp_path / name).parent == tmp_path
        # The label value is escaped, so the exposition line is well-formed.
        assert r'alias="ev/il\"host"' in body

    def test_nul_in_alias_does_not_raise(self, tmp_path, monkeypatch) -> None:
        """A NUL byte in the alias never raises (best-effort write is preserved)."""
        monkeypatch.setenv("PERCONA_BACKUP_TEXTFILE_COLLECTOR_DIR", str(tmp_path))
        monkeypatch.delenv("NOMAD_META_TARGET", raising=False)
        monkeypatch.setenv("NOMAD_META_CONFIG", "alias: host-1")
        # Force a raw NUL through, bypassing the config sanitisation, to prove the
        # writer's own guard also holds.
        monkeypatch.setattr(
            "app.sep.apps.backup_mongo.pbm_creds_common._metric_alias",
            lambda: "ho\x00st",
        )
        # Must not raise even though the label carries a NUL the collector rejects.
        write_backup_status("PBM Logical", 0)
        name, _body = _read_single_prom(tmp_path)
        assert "\x00" not in name


class TestWriteBackupStatus:
    """Cover the ``msp_backup_status`` / ``msp_backup_last_report_ts`` writer."""

    @pytest.fixture
    def collector(self, tmp_path, monkeypatch) -> Path:
        """Point the collector dir at a tmp dir and stamp an alias into the config."""
        monkeypatch.setenv("PERCONA_BACKUP_TEXTFILE_COLLECTOR_DIR", str(tmp_path))
        monkeypatch.setenv("NOMAD_META_CONFIG", "alias: host-1")
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
        monkeypatch.setenv("NOMAD_META_CONFIG", "alias: host-1")
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
        monkeypatch.delenv("NOMAD_META_CONFIG", raising=False)
        monkeypatch.delenv("NOMAD_META_TARGET", raising=False)
        write_backup_status("PBM Logical", 0)
        _name, body = _read_single_prom(tmp_path)
        assert 'msp_backup_status{type="PBM Logical", alias=""} 0' in body


class TestWriteBackupEnabled:
    """Cover the ``msp_backup_enabled`` writer (the join's load-bearing series)."""

    def test_writes_enabled(self, tmp_path, monkeypatch) -> None:
        """Write ``msp_backup_enabled == 1`` with ``type``/``alias`` labels."""
        monkeypatch.setenv("PERCONA_BACKUP_TEXTFILE_COLLECTOR_DIR", str(tmp_path))
        monkeypatch.setenv("NOMAD_META_CONFIG", "alias: host-1")
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
        monkeypatch.setenv("NOMAD_META_CONFIG", "alias: host-1")
        write_backup_enabled("PBM Logical")
        assert not absent.exists()


class TestTextfileRegionSync:
    """Assert the shared metric-writer region is embedded byte-identically."""

    def test_discovers_exactly_the_backup_payloads(self) -> None:
        """The three backup payloads (and only them) carry the region."""
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
        """Each payload declares its own distinct, stable ``PBM_METRIC_TYPE``."""
        payload = next(p for p in _textfile_payloads() if p.name == payload_name)
        line = assignment_line(payload.read_text(encoding="utf-8"), "PBM_METRIC_TYPE")
        assert line == f'PBM_METRIC_TYPE = "{expected_type}"'

    @pytest.mark.parametrize("payload", _textfile_payloads(), ids=lambda p: p.name)
    def test_enable_is_written_before_the_backup_try(self, payload: Path) -> None:
        """Enable is emitted before the backup ``try`` so a preflight abort still shows it."""
        # Anchor to the pbm() body -- the region helpers above also carry ``try:``.
        body = payload.read_text(encoding="utf-8").split("def pbm():", 1)[1]
        enable_at = body.index("write_backup_enabled(PBM_METRIC_TYPE)")
        # The enable call precedes the backup ``try:``, so it is emitted even when
        # credential/config-apply preflight aborts.
        assert enable_at < body.index("\n    try:")

    @pytest.mark.parametrize("payload", _textfile_payloads(), ids=lambda p: p.name)
    def test_wires_enable_and_both_statuses(self, payload: Path) -> None:
        """Each payload marks enabled and writes both success and failure status."""
        text = payload.read_text(encoding="utf-8")
        assert "write_backup_enabled(PBM_METRIC_TYPE)" in text
        assert "write_backup_status(PBM_METRIC_TYPE, 0)" in text
        assert "write_backup_status(PBM_METRIC_TYPE, 1)" in text

    @pytest.mark.parametrize(
        "payload",
        [p for p in _textfile_payloads() if p.name != "pbm_snapshot_payload"],
        ids=lambda p: p.name,
    )
    def test_aborting_payloads_record_failure_on_preflight_exit(
        self, payload: Path
    ) -> None:
        """Logical/physical write a failure status when preflight aborts via ``sys.exit``."""
        text = payload.read_text(encoding="utf-8")
        # The preflight abort is caught and recorded before the exit propagates.
        assert "except SystemExit:" in text
        exit_handler = text.index("except SystemExit:")
        assert "write_backup_status(PBM_METRIC_TYPE, 1)" in text[exit_handler:]

    @pytest.mark.parametrize(
        "payload",
        [p for p in _textfile_payloads() if p.name != "pbm_snapshot_payload"],
        ids=lambda p: p.name,
    )
    def test_aborting_payloads_record_failure_on_any_preflight_error(
        self, payload: Path
    ) -> None:
        """Logical/physical record a failure status for any preflight exception."""
        # The catch is ``except Exception``, not just ``OSError``, so a yaml/config
        # parse error records the failure metric before the payload exits.
        body = payload.read_text(encoding="utf-8").split("def pbm():", 1)[1]
        assert "except Exception as err:" in body
        handler = body.index("except Exception as err:")
        assert "write_backup_status(PBM_METRIC_TYPE, 1)" in body[handler:]

    def test_snapshot_stays_non_aborting(self) -> None:
        """The snapshot payload must keep swallowing failure (no ``sys.exit``)."""
        snapshot = GEN.DEFAULT_SEARCH_ROOT / "pbm_snapshot_payload"
        text = snapshot.read_text(encoding="utf-8")
        assert "sys.exit" not in text
        # A missing PBM_CREATE_SNAPSHOT still records a failure without aborting.
        assert "except (OSError, KeyError)" in text
