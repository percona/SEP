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

"""Define tests for the shared PBM creds preamble across the nine backup_mongo payloads."""

import builtins
import importlib.util
import sys
from pathlib import Path

import pytest

from app.sep.apps.backup_mongo.pbm_creds_common import (
    _creds_path,
    _creds_path_from_config,
    pbm_creds,
    PREAMBLE_BEGIN,
    PREAMBLE_END,
    preamble_source,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[5]
_SCRIPT_PATH = _PROJECT_ROOT / "scripts" / "gen_pbm_payloads.py"

_spec = importlib.util.spec_from_file_location("gen_pbm_payloads", _SCRIPT_PATH)
assert _spec is not None, f"cannot load {_SCRIPT_PATH}"
assert _spec.loader is not None, f"cannot load {_SCRIPT_PATH}"
gen_pbm_payloads = importlib.util.module_from_spec(_spec)
sys.modules["gen_pbm_payloads"] = gen_pbm_payloads
_spec.loader.exec_module(gen_pbm_payloads)

_EXPECTED_PAYLOADS = {
    "pbm_config_payload",
    "pbm_logical_payload",
    "pbm_physical_payload",
    "pbm_status_payload",
    "pbm_force_resync_payload",
    "pbm_list_payload",
    "pbm_logical_restore_payload",
    "pbm_physical_restore_payload",
    "pbm_restore_config_payload",
}

_EXPECTED_PBM_URI_CALLS = {
    "pbm_config_payload": "pbm_creds(_creds_path('backup'))",
    "pbm_logical_payload": "pbm_creds(_creds_path('backup'))",
    "pbm_physical_payload": "pbm_creds(_creds_path('backup'))",
    "pbm_status_payload": "pbm_creds(_creds_path('backup'))",
    "pbm_force_resync_payload": "pbm_creds(_creds_path('restore'))",
    "pbm_list_payload": "pbm_creds(_creds_path('restore'))",
    "pbm_logical_restore_payload": "pbm_creds(_creds_path_from_config(config))",
    "pbm_physical_restore_payload": "pbm_creds(_creds_path_from_config(config))",
    "pbm_restore_config_payload": "pbm_creds(_creds_path_from_config(script_config))",
}


def _shipped_payloads() -> list[Path]:
    """Return the opted-in payloads discovered under the real backup_mongo app.

    :return: The payload paths carrying the BEGIN marker line.
    :rtype: list[Path]
    """
    return gen_pbm_payloads.find_payloads(
        gen_pbm_payloads.DEFAULT_SEARCH_ROOT, PREAMBLE_BEGIN
    )


def _region_of(text: str) -> str:
    """Extract the text strictly between the preamble markers in ``text``.

    :param text: The payload source to slice.
    :type text: str
    :return: The region body, matching :func:`preamble_source`'s framing.
    :rtype: str
    """
    lines = text.split("\n")
    begin = lines.index(PREAMBLE_BEGIN)
    end = lines.index(PREAMBLE_END, begin + 1)
    return "\n".join(lines[begin + 1 : end]).strip("\n")


def _pbm_mongodb_uri_assignment(text: str) -> str:
    """Return the ``PBM_MONGODB_URI`` assignment line from a payload script.

    :param text: The payload source to scan.
    :type text: str
    :return: The stripped assignment line.
    :rtype: str
    """
    for line in text.splitlines():
        if "PBM_MONGODB_URI" in line and "=" in line:
            return line.strip()
    raise AssertionError("no PBM_MONGODB_URI assignment found")


class TestInSyncGuard:
    """Assert the shipped payloads match the canonical region (CI drift guard)."""

    def test_check_mode_reports_no_drift(self) -> None:
        """``gen_pbm_payloads.py --check`` exits 0 for the checked-in tree."""
        assert gen_pbm_payloads.main(["--check"]) == 0

    def test_discovers_exactly_the_nine_payloads(self) -> None:
        """Discover the nine credential-bearing payloads and nothing else."""
        found = {path.name for path in _shipped_payloads()}
        assert found == _EXPECTED_PAYLOADS
        assert set(_EXPECTED_PBM_URI_CALLS) == _EXPECTED_PAYLOADS

    def test_snapshot_payload_is_markerless(self) -> None:
        """``pbm_snapshot_payload`` stays out of scope (no preamble markers)."""
        snapshot = gen_pbm_payloads.DEFAULT_SEARCH_ROOT / "pbm_snapshot_payload"
        assert snapshot.is_file()
        assert PREAMBLE_BEGIN not in snapshot.read_text(encoding="utf-8").splitlines()

    def test_canonical_source_is_not_treated_as_a_payload(self) -> None:
        """The canonical module defines the region but is never a rewrite target."""
        found = {path.resolve() for path in _shipped_payloads()}
        assert gen_pbm_payloads.CANONICAL_SOURCE.resolve() not in found


class TestPerPayloadAssembly:
    """Assert every payload carries the canonical region verbatim."""

    @pytest.mark.parametrize("payload", _shipped_payloads(), ids=lambda p: p.name)
    def test_region_matches_canonical(self, payload: Path) -> None:
        """The block between a payload's markers equals ``preamble_source()``."""
        assert _region_of(payload.read_text(encoding="utf-8")) == preamble_source()

    @pytest.mark.parametrize("payload", _shipped_payloads(), ids=lambda p: p.name)
    def test_render_is_idempotent(self, payload: Path) -> None:
        """Re-rendering an in-sync payload is a no-op (round-trip stable)."""
        current = payload.read_text(encoding="utf-8")
        rendered = gen_pbm_payloads.render(
            current, preamble_source(), PREAMBLE_BEGIN, PREAMBLE_END
        )
        assert rendered == current

    @pytest.mark.parametrize(
        ("payload_name", "expected_call"),
        sorted(_EXPECTED_PBM_URI_CALLS.items()),
    )
    def test_pbm_mongodb_uri_cred_call_site(
        self, payload_name: str, expected_call: str
    ) -> None:
        """Assert each payload wires credentials via the expected resolver call."""
        payload = next(p for p in _shipped_payloads() if p.name == payload_name)
        assignment = _pbm_mongodb_uri_assignment(payload.read_text(encoding="utf-8"))
        assert expected_call in assignment


class TestCredsPathEnv:
    """Cover ``_creds_path`` (the ``NOMAD_META_CONFIG`` shape)."""

    def test_returns_credentials_path_from_config(self, monkeypatch) -> None:
        """Return the ``credentials_path`` parsed out of ``NOMAD_META_CONFIG``."""
        monkeypatch.setenv("NOMAD_META_CONFIG", "credentials_path: /secrets/uri")
        assert _creds_path("backup") == "/secrets/uri"

    def test_falls_back_to_home_when_unset(self, monkeypatch) -> None:
        """Fall back to ``$HOME/.mongodb_uri`` when the env var is absent."""
        monkeypatch.delenv("NOMAD_META_CONFIG", raising=False)
        monkeypatch.setenv("HOME", "/home/pbm")
        assert _creds_path("backup") == "/home/pbm/.mongodb_uri"

    def test_falls_back_when_config_has_no_path(self, monkeypatch) -> None:
        """Fall back to ``$HOME`` when the parsed config lacks ``credentials_path``."""
        monkeypatch.setenv("NOMAD_META_CONFIG", "other: value")
        monkeypatch.setenv("HOME", "/home/pbm")
        assert _creds_path("restore") == "/home/pbm/.mongodb_uri"

    def test_yaml_error_warns_and_falls_back(self, monkeypatch, capsys) -> None:
        """Emit the parse-failure warning and fall back on malformed YAML."""
        monkeypatch.setenv("NOMAD_META_CONFIG", "key: [unclosed")
        monkeypatch.setenv("HOME", "/home/pbm")
        assert _creds_path("backup") == "/home/pbm/.mongodb_uri"
        err = capsys.readouterr().err
        assert err.startswith("Failed to parse NOMAD_META_CONFIG as YAML: ")
        assert "Falling back to HOME-based credentials path." in err

    @pytest.mark.parametrize("source", ["backup", "restore"])
    def test_exits_when_home_unset(self, monkeypatch, capsys, source) -> None:
        """Exit 1 with the exact stderr when both the config and HOME are absent."""
        monkeypatch.delenv("NOMAD_META_CONFIG", raising=False)
        monkeypatch.delenv("HOME", raising=False)
        with pytest.raises(SystemExit) as exc:
            _creds_path(source)
        assert exc.value.code == 1
        assert capsys.readouterr().err == (
            f"PBM credentials path not set (credentials_path in {source} config) "
            "and HOME is unset\n"
        )


class TestCredsPathFromConfig:
    """Cover ``_creds_path_from_config`` (the parsed-dict shape)."""

    def test_returns_credentials_path_from_dict(self) -> None:
        """Return ``credentials_path`` straight from the parsed config dict."""
        assert _creds_path_from_config({"credentials_path": "/s/uri"}) == "/s/uri"

    @pytest.mark.parametrize(
        "config",
        [None, {}, {"other": 1}, "a bare scalar", ["a", "list"], 42],
    )
    def test_falls_back_to_home(self, monkeypatch, config) -> None:
        """Fall back to ``$HOME`` for missing/empty/path-less/non-dict configs.

        ``yaml.safe_load`` can legally return a truthy non-dict (a bare scalar or a
        list); those must be treated as missing config rather than raising
        ``AttributeError`` from a ``.get()`` call on a non-dict.
        """
        monkeypatch.setenv("HOME", "/home/pbm")
        assert _creds_path_from_config(config) == "/home/pbm/.mongodb_uri"

    @pytest.mark.parametrize("config", ["a bare scalar", ["a", "list"], 42])
    def test_exits_on_non_dict_when_home_unset(
        self, monkeypatch, capsys, config
    ) -> None:
        """Exit 1 with the exact stderr for a non-dict config when HOME is unset."""
        monkeypatch.delenv("HOME", raising=False)
        with pytest.raises(SystemExit) as exc:
            _creds_path_from_config(config, "backup")
        assert exc.value.code == 1
        assert capsys.readouterr().err == (
            "PBM credentials path not set (credentials_path in backup config) "
            "and HOME is unset\n"
        )

    def test_defaults_to_restore_label_on_exit(self, monkeypatch, capsys) -> None:
        """Default the error label to ``restore`` when HOME is unset."""
        monkeypatch.delenv("HOME", raising=False)
        with pytest.raises(SystemExit) as exc:
            _creds_path_from_config(None)
        assert exc.value.code == 1
        assert capsys.readouterr().err == (
            "PBM credentials path not set (credentials_path in restore config) "
            "and HOME is unset\n"
        )

    def test_honors_explicit_label_on_exit(self, monkeypatch, capsys) -> None:
        """Use the caller-supplied label in the exit message when provided."""
        monkeypatch.delenv("HOME", raising=False)
        with pytest.raises(SystemExit):
            _creds_path_from_config(None, "backup")
        assert "credentials_path in backup config" in capsys.readouterr().err


class TestPbmCreds:
    """Cover ``pbm_creds`` (reading the resolved credentials file)."""

    def test_reads_and_strips_uri(self, tmp_path) -> None:
        """Return the file contents with surrounding whitespace stripped."""
        creds = tmp_path / ".mongodb_uri"
        creds.write_text("  mongodb://u:p@host  \n", encoding="utf-8")
        assert pbm_creds(str(creds)) == "mongodb://u:p@host"

    def test_missing_file_exits_1(self, tmp_path, capsys) -> None:
        """Exit 1 with the not-found message for an absent credentials file."""
        missing = tmp_path / "nope"
        with pytest.raises(SystemExit) as exc:
            pbm_creds(str(missing))
        assert exc.value.code == 1
        assert capsys.readouterr().err.startswith(
            f"Credentials file not found: {missing}: "
        )

    def test_permission_error_exits_1(self, tmp_path, monkeypatch, capsys) -> None:
        """Exit 1 with the permission-denied message when the read is forbidden."""
        creds = tmp_path / ".mongodb_uri"
        creds.write_text("uri", encoding="utf-8")

        def _deny(*_args, **_kwargs):
            raise PermissionError("denied")

        monkeypatch.setattr(builtins, "open", _deny)
        with pytest.raises(SystemExit) as exc:
            pbm_creds(str(creds))
        assert exc.value.code == 1
        assert capsys.readouterr().err.startswith(
            f"Permission denied reading credentials file {creds}: "
        )

    def test_os_error_exits_1(self, tmp_path, capsys) -> None:
        """Exit 1 with the generic read-error message on an ``OSError`` read."""
        # A directory triggers IsADirectoryError (an OSError subclass) on read.
        with pytest.raises(SystemExit) as exc:
            pbm_creds(str(tmp_path))
        assert exc.value.code == 1
        assert capsys.readouterr().err.startswith(
            f"Error reading credentials file {tmp_path}: "
        )
