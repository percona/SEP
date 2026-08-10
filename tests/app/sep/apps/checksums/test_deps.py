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

"""Define tests for the app.sep.apps.checksums.deps module."""

from app.sep.apps.checksums.deps import (
    parse_checksums_task_args,
)


class TestParseChecksumsTaskArgs:
    """Cover the reverse parser that rebuilds form values from a stored args string."""

    def test_golden_full_args_round_trip(self):
        """Rebuild the complete form-value dict from a full checksums args string."""
        meta = {
            "args": (
                "P=3306,D=percona,t=checksums "
                "--recursion-method=dsn=h=1,P=2,D=x,t=y "
                "--databases=db1,db2 --tables=t1,t2 --pause-file=/tmp/p "
                "--set-vars=x=1 --max-load=Threads_running=50 --chunk-time=0.5 "
                "--max-lag=100 --progress=time,10 "
                "--binary-index --explain --fail-on-stopped-replication "
                "--truncate-replicate-table"
            ),
        }

        assert parse_checksums_task_args(meta) == {
            "recursion_method": "dsn=h=1,P=2,D=x,t=y",
            "databases": "db1,db2",
            "tables": "t1,t2",
            "pause_file": "/tmp/p",
            "binary_index": True,
            "explain_arg": True,
            "fail_on_stopped_replication": True,
            "truncate_replicate_table": True,
            "progress": "time,10",
            "set_vars": "x=1",
            "max_load": "Threads_running=50",
            "chunk_time": "0.5",
            "max_lag": "100",
            "extra_args": "",
        }

    def test_missing_or_empty_args_return_defaults(self):
        """Return the default form values when args are missing or empty."""
        defaults = parse_checksums_task_args({})
        assert defaults["recursion_method"] == "processlist"
        assert parse_checksums_task_args({"args": ""}) == defaults

    def test_first_token_is_always_dropped(self):
        """Drop the leading positional DSN token before parsing the rest."""
        out = parse_checksums_task_args({"args": "--binary-index --explain"})
        assert out["binary_index"] is False
        assert out["explain_arg"] is True

    def test_recursion_method_dsn_is_stored_raw(self):
        """Store ``--recursion-method=dsn=…`` verbatim (checksums defers the split)."""
        out = parse_checksums_task_args(
            {"args": "leading --recursion-method=dsn=h=1,D=x,t=y"}
        )
        assert out["recursion_method"] == "dsn=h=1,D=x,t=y"
        assert "dsn_table" not in out

    def test_unknown_args_are_dropped(self):
        """Drop unrecognized args silently (checksums keeps no extra_args)."""
        out = parse_checksums_task_args(
            {"args": "leading --unknown-flag --databases=db"}
        )
        assert out["databases"] == "db"
        assert out["extra_args"] == ""
