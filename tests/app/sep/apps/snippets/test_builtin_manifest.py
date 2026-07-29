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

"""Define tests for the built-in snippets checksum manifest helpers."""

import hashlib

import pytest

from app.sep.apps.snippets.builtin_manifest import (
    load_builtin_checksum_manifest,
    sha256_file,
)
from app.sep.apps.snippets.constants import BUILTIN_CHECKSUM_MANIFEST

MODULE = "app.sep.apps.snippets.builtin_manifest"


class TestLoadBuiltinChecksumManifest:
    """Test load_builtin_checksum_manifest parser branches."""

    @pytest.mark.asyncio
    async def test_missing_manifest_returns_empty(self, tmp_path, caplog):
        """Assert a missing manifest file yields an empty mapping."""
        with caplog.at_level("WARNING", logger=MODULE):
            result = await load_builtin_checksum_manifest(tmp_path)

        assert result == {}
        assert "unavailable" in caplog.text
        assert BUILTIN_CHECKSUM_MANIFEST in caplog.text

    @pytest.mark.asyncio
    async def test_unreadable_manifest_returns_empty(self, tmp_path, caplog):
        """Assert an unreadable manifest path yields an empty mapping."""
        # A directory at the manifest path makes open raise IsADirectoryError.
        (tmp_path / BUILTIN_CHECKSUM_MANIFEST).mkdir()

        with caplog.at_level("WARNING", logger=MODULE):
            result = await load_builtin_checksum_manifest(tmp_path)

        assert result == {}
        assert "unavailable" in caplog.text

    @pytest.mark.asyncio
    async def test_parses_valid_two_space_lines(self, tmp_path):
        """Assert well-formed sha256sum lines become filename-to-digest entries."""
        (tmp_path / BUILTIN_CHECKSUM_MANIFEST).write_text(
            "abc123  foo.sh\ndef456  nested/bar.py\n",
            encoding="utf-8",
        )

        assert await load_builtin_checksum_manifest(tmp_path) == {
            "foo.sh": "abc123",
            "nested/bar.py": "def456",
        }

    @pytest.mark.asyncio
    async def test_skips_blank_and_comment_lines(self, tmp_path):
        """Assert blank lines and ``#`` comments are ignored."""
        (tmp_path / BUILTIN_CHECKSUM_MANIFEST).write_text(
            "\n# header comment\n  \nabc123  keep.sh\n# trailing comment\n\n",
            encoding="utf-8",
        )

        assert await load_builtin_checksum_manifest(tmp_path) == {"keep.sh": "abc123"}

    @pytest.mark.parametrize(
        "bad_line",
        [
            "abc123 keep.sh",  # single space, not two
            "  keep.sh",  # empty digest
            "abc123  ",  # empty filename
            "nospace",  # no separator
        ],
        ids=["single-space", "empty-digest", "empty-filename", "no-separator"],
    )
    @pytest.mark.asyncio
    async def test_skips_malformed_lines(self, tmp_path, caplog, bad_line):
        """Assert malformed lines are skipped and logged, valid peers kept."""
        (tmp_path / BUILTIN_CHECKSUM_MANIFEST).write_text(
            f"{bad_line}\nabc123  good.sh\n",
            encoding="utf-8",
        )

        with caplog.at_level("WARNING", logger=MODULE):
            result = await load_builtin_checksum_manifest(tmp_path)

        assert result == {"good.sh": "abc123"}
        assert "Ignoring malformed checksum manifest line 1" in caplog.text

    @pytest.mark.asyncio
    async def test_empty_manifest_returns_empty(self, tmp_path):
        """Assert an empty or comment-only manifest yields an empty mapping."""
        (tmp_path / BUILTIN_CHECKSUM_MANIFEST).write_text(
            "# nothing here\n\n",
            encoding="utf-8",
        )

        assert await load_builtin_checksum_manifest(tmp_path) == {}


class TestSha256File:
    """Test sha256_file against known content."""

    @pytest.mark.asyncio
    async def test_hashes_file_contents(self, tmp_path):
        """Assert the digest matches hashlib over the same bytes."""
        path = tmp_path / "snippet.sh"
        content = b"echo hello\n"
        path.write_bytes(content)

        assert await sha256_file(path) == hashlib.sha256(content).hexdigest()
