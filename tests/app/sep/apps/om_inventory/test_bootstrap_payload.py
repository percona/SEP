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

"""Test the parts of ``payload/bootstrap.py`` that do not touch a real host.

Everything else in that module -- installing packages, writing to ``/etc``, managing
a systemd unit, talking to a live mongod -- is exercised by actually running it
against a target host, not by a unit test faking every subprocess call. That is the
whole point of the PoC: prove the real thing works, not prove a mock of it does.
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from app.sep.apps.om_inventory.payload.bootstrap import (
    percona_series_for_version,
    run,
    StageFailed,
)


class TestPerconaSeriesForVersion:
    """Assert the MongoDB version -> percona-release series mapping."""

    @pytest.mark.parametrize(
        ("version", "series"),
        [
            ("7.0.8", "psmdb-70"),
            ("7.0.39-21", "psmdb-70"),
            ("8.0.1", "psmdb-80"),
            ("6", "psmdb-60"),
        ],
    )
    def test_derives_the_series_from_the_major_version(
        self, version: str, series: str
    ) -> None:
        """Only the major version selects the series -- see psmdb/Dockerfile."""
        assert percona_series_for_version(version) == series

    @pytest.mark.parametrize("version", [None, "", "latest", "v7.0.8"])
    def test_an_unparseable_version_fails_loudly(self, version: str | None) -> None:
        """A version this cannot map to a series must not silently install nothing."""
        with pytest.raises(StageFailed):
            percona_series_for_version(version)


class TestRun:
    """Assert :func:`run`'s failure wrapping -- every later stage depends on it."""

    def test_a_missing_binary_raises_stage_failed(self) -> None:
        """The most common real failure: the command does not exist on this host."""
        with pytest.raises(StageFailed, match="not found"):
            run(["definitely-not-a-real-binary-xyz"])

    def test_a_nonzero_exit_raises_stage_failed_with_the_tail_of_stderr(self) -> None:
        """The error must survive -- it becomes the NDJSON ``detail`` a human reads."""
        completed = MagicMock(returncode=1, stdout="", stderr="permission denied")
        with (
            patch("subprocess.run", return_value=completed),
            pytest.raises(StageFailed, match="permission denied"),
        ):
            run(["some-command"])

    def test_a_timeout_raises_stage_failed(self) -> None:
        """A hung install must end the run, not the whole payload's timeout budget."""
        with (
            patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="some-command", timeout=1),
            ),
            pytest.raises(StageFailed),
        ):
            run(["some-command"], timeout=1)
