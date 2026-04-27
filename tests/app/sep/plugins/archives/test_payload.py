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

"""Tests for the archives payload script — specifically pt_archive_runner."""

import types
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(scope="module")
def payload():
    """Import the archives payload script as a module (no .py extension)."""
    payload_path = Path(__file__).parents[5] / "app/sep/plugins/archives/payload"
    loader = SourceFileLoader("archives_payload", str(payload_path))
    mod = types.ModuleType("archives_payload")
    loader.exec_module(mod)
    return mod


def _base_conf(overrides: dict | None = None) -> dict:
    """Return a minimal conf dict for pt_archive_runner."""
    conf = {
        "prg_alias": "test_task",
        "src_host": "source_host",
        "src_port": 3306,
        "src_db": "mydb",
        "src_tbl": "mytable",
        "dst_host": "dest_host",
        "dst_port": 3306,
        "dst_db": "destdb",
        "dst_tbl": "desttable",
        "dst_file": None,
        "prg_where": "id > 100",
        "prg_limit": 1000,
        "prg_sleep": 1,
        "prg_purge": 0,
        "prg_extra_args": None,
        "prg_disable_binlog": 0,
        "prg_disable_bulk_insert": 0,
        "prg_use_index": None,
    }
    if overrides:
        conf.update(overrides)
    return conf


class TestPtArchiveRunnerBulkInsert:
    """Test --bulk-insert flag behaviour in pt_archive_runner."""

    def test_bulk_insert_included_by_default(self, payload):
        """--bulk-insert is added to the dest-table branch when disable_bulk_insert=0."""
        conf = _base_conf()
        with patch.object(payload, "run_cmd", return_value=0) as mock_run:
            payload.pt_archive_runner("pt-archiver", "mydb", "mytable", conf)

        args = mock_run.call_args[0]
        assert "--bulk-insert" in args

    def test_bulk_insert_omitted_when_disabled(self, payload):
        """--bulk-insert is not added when prg_disable_bulk_insert=1."""
        conf = _base_conf({"prg_disable_bulk_insert": 1})
        with patch.object(payload, "run_cmd", return_value=0) as mock_run:
            payload.pt_archive_runner("pt-archiver", "mydb", "mytable", conf)

        args = mock_run.call_args[0]
        assert "--bulk-insert" not in args

    def test_dest_arg_still_present_when_bulk_insert_disabled(self, payload):
        """--dest=... is always included regardless of disable_bulk_insert."""
        conf = _base_conf({"prg_disable_bulk_insert": 1})
        with patch.object(payload, "run_cmd", return_value=0) as mock_run:
            payload.pt_archive_runner("pt-archiver", "mydb", "mytable", conf)

        args = mock_run.call_args[0]
        assert any(a.startswith("--dest=") for a in args)

    def test_bulk_insert_not_in_purge_branch(self, payload):
        """--bulk-insert is never added in the purge-only (prg_purge=1) branch."""
        conf = _base_conf({"prg_purge": 1, "prg_disable_bulk_insert": 0})
        with patch.object(payload, "run_cmd", return_value=0) as mock_run:
            payload.pt_archive_runner("pt-archiver", "mydb", "mytable", conf)

        args = mock_run.call_args[0]
        assert "--bulk-insert" not in args
        assert "--purge" in args

    def test_bulk_insert_not_in_dest_file_branch(self, payload):
        """--bulk-insert is never added in the dest-file branch."""
        conf = _base_conf(
            {"dst_file": "/tmp/archive.csv", "prg_disable_bulk_insert": 0}
        )
        with patch.object(payload, "run_cmd", return_value=0) as mock_run:
            payload.pt_archive_runner("pt-archiver", "mydb", "mytable", conf)

        args = mock_run.call_args[0]
        assert "--bulk-insert" not in args
        assert any(a.startswith("--file=") for a in args)

    def test_disable_bulk_insert_zero_explicit_still_includes_bulk_insert(
        self, payload
    ):
        """prg_disable_bulk_insert=0 (explicit) keeps --bulk-insert, matching default."""
        conf = _base_conf({"prg_disable_bulk_insert": 0})
        with patch.object(payload, "run_cmd", return_value=0) as mock_run:
            payload.pt_archive_runner("pt-archiver", "mydb", "mytable", conf)

        args = mock_run.call_args[0]
        assert "--bulk-insert" in args

    def test_use_index_does_not_affect_bulk_insert_behavior(self, payload):
        """disable_bulk_insert=1 omits --bulk-insert even when use_index is set."""
        conf = _base_conf({"prg_disable_bulk_insert": 1, "prg_use_index": "PRIMARY"})
        with patch.object(payload, "run_cmd", return_value=0) as mock_run:
            payload.pt_archive_runner("pt-archiver", "mydb", "mytable", conf)

        args = mock_run.call_args[0]
        assert "--bulk-insert" not in args
        assert any(a.startswith("--dest=") for a in args)
