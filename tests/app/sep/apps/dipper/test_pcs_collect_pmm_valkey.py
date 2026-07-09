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
"""Tests for the pcs-collect-pmm-valkey.py payload script."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).parents[5] / "app/sep/apps/dipper/payloads/pcs-collect-pmm-valkey.py"
)


def _frontmatter() -> str:
    """Return the YAML frontmatter block from the collector script."""
    content = SCRIPT.read_text()
    frontmatter_end = content.index("# ---", content.index("# ---") + 1)
    return content[:frontmatter_end]


def _parameter_block(frontmatter: str, parameter_name: str) -> str:
    """Return the frontmatter slice for a single parameter declaration."""
    marker = f"name: {parameter_name}"
    start = frontmatter.index(marker)
    next_parameter_index = frontmatter.find("name: ", start + len(marker))
    if next_parameter_index == -1:
        return frontmatter[start:]
    return frontmatter[start:next_parameter_index]


class TestPcsCollectPmmValkeyHelp:
    """Tests for the --help output of pcs-collect-pmm-valkey.py."""

    @pytest.fixture(scope="class")
    def help_output(self):
        """Run the script with --help and capture the output.

        Pin ``COLUMNS`` so argparse wraps the help text at a fixed width: under
        ``pytest -n`` (no tty) the inherited terminal width can be narrow enough
        to split ``self-signed`` across lines and break a substring assertion.
        """
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "COLUMNS": "80"},
        )

    def test_help_exits_zero(self, help_output):
        """--help must exit cleanly."""
        assert help_output.returncode == 0

    def test_help_shows_valkey_flags(self, help_output):
        """The Valkey-specific and SEP-added flags appear in --help output."""
        stdout = help_output.stdout
        assert "--insecure" in stdout
        assert "--skip-valkey" in stdout
        assert "--sentinel" in stdout
        assert "--cluster" in stdout

    def test_insecure_flag_description_in_help(self, help_output):
        """--insecure help text must mention self-signed certs."""
        assert "self-signed" in help_output.stdout


class TestPcsCollectPmmValkeyVerifySsl:
    """Regression: TLS verification must be controllable, never hard-disabled."""

    def test_no_hardcoded_verify_false(self):
        """No requests call site may use a literal verify=False."""
        assert "verify=False" not in SCRIPT.read_text()


class TestPcsCollectPmmValkeyFrontmatter:
    """Tests for the YAML frontmatter declarations."""

    def test_insecure_parameter_is_bool(self):
        """The SEP-added insecure parameter is a boolean form field."""
        assert "type: bool" in _parameter_block(_frontmatter(), "insecure")

    def test_apikey_marked_hidden(self):
        """The apikey parameter declares ``hidden: true`` in the frontmatter."""
        assert "hidden: true" in _parameter_block(_frontmatter(), "apikey")

    def test_pmmserver_is_positional_and_not_hidden(self):
        """Pmmserver is positional and must remain visible in the form."""
        block = _parameter_block(_frontmatter(), "pmmserver")
        assert "positional: true" in block
        assert "hidden: true" not in block

    def test_sibling_parameters_are_not_hidden(self):
        """Visible sibling params do not declare ``hidden``."""
        frontmatter = _frontmatter()
        for name in ("node", "service", "list"):
            assert "hidden: true" not in _parameter_block(frontmatter, name)

    def test_sentinel_marked_hidden(self):
        """Sentinel collection is always on and not user-controllable, so it is hidden."""
        assert "hidden: true" in _parameter_block(_frontmatter(), "sentinel")


class TestPcsCollectPmmValkeyParses:
    """The hand-authored metadata header parses without validation errors."""

    @pytest.mark.asyncio
    async def test_metadata_header_parses_without_errors(self):
        """A malformed header would surface as parameter validation errors."""
        from app.sep.snippets.models.snippet import BaseSnippet

        meta = await BaseSnippet.get_meta_by_path(SCRIPT)
        snippet = BaseSnippet(
            filename="pcs-collect-pmm-valkey.py",
            size=1,
            md5_digest="a" * 32,
            meta=meta,
        )
        validated = snippet.validated_parameters
        assert validated.errors == []
        by_name = {p.name: p for p in validated.parameters}
        assert by_name["apikey"].hidden is True
        assert by_name["pmmserver"].hidden is False
