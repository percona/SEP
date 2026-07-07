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

"""Define tests for the report artifact staging store."""

import os
import time
from pathlib import Path

import pytest

from app.sep.apps.report import artifact_store

_TTL = 3600


@pytest.fixture(autouse=True)
def _stage_dir(mocker, tmp_path: Path):
    """Point the artifact store at an isolated temp directory."""
    mocker.patch.object(
        artifact_store.sep_settings.HEALTH_REPORT, "artifact_dir", str(tmp_path)
    )
    return tmp_path


class TestArtifactRoundTrip:
    """Write/read/exists behavior for staged artifacts."""

    def test_write_then_read_returns_same_bytes(self) -> None:
        """A staged artifact reads back byte-identical."""
        artifact_store.write_artifact("job-1", b"%PDF-1.4 data")

        assert artifact_store.artifact_exists("job-1") is True
        assert artifact_store.read_artifact("job-1") == b"%PDF-1.4 data"

    def test_read_missing_returns_none(self) -> None:
        """Reading an absent artifact yields ``None`` rather than raising."""
        assert artifact_store.read_artifact("missing") is None
        assert artifact_store.artifact_exists("missing") is False


class TestJobIdSafety:
    """Path-traversal guard on untrusted job ids."""

    @pytest.mark.parametrize("bad", ["../escape", "a/b", "..", "with space", ""])
    def test_unsafe_job_id_rejected(self, bad: str) -> None:
        """Job ids with separators or unsafe characters are rejected."""
        with pytest.raises(ValueError, match="Unsafe report artifact job id"):
            artifact_store.artifact_path(bad)


class TestPurgeExpired:
    """mtime-based reaping of staged artifacts."""

    def test_purges_only_expired_artifacts(self) -> None:
        """Files older than the TTL are removed; fresh ones are kept."""
        artifact_store.write_artifact("fresh", b"new")
        artifact_store.write_artifact("stale", b"old")
        stale = artifact_store.artifact_path("stale")
        old = time.time() - _TTL - 60
        os.utime(stale, (old, old))

        removed = artifact_store.purge_expired(_TTL)

        assert removed == 1
        assert artifact_store.artifact_exists("fresh") is True
        assert artifact_store.artifact_exists("stale") is False

    def test_purge_missing_dir_is_noop(self, mocker, tmp_path: Path) -> None:
        """Purging when the staging dir does not exist returns zero."""
        mocker.patch.object(
            artifact_store.sep_settings.HEALTH_REPORT,
            "artifact_dir",
            str(tmp_path / "absent"),
        )
        assert artifact_store.purge_expired(_TTL) == 0
