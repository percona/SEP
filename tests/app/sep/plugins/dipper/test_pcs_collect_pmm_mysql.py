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
"""Tests for the pcs-collect-pmm-mysql.py payload script."""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).parents[5]
    / "app/sep/plugins/dipper/payloads/pcs-collect-pmm-mysql.py"
)


class TestPcsCollectPmmMysqlInsecureFlag:
    """Tests for the --insecure flag of pcs-collect-pmm-mysql.py."""

    @pytest.fixture(scope="class")
    def help_output(self):
        """Run the script with --help and capture the output."""
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_insecure_flag_in_help(self, help_output):
        """--insecure must appear in --help output."""
        assert help_output.returncode == 0
        assert "--insecure" in help_output.stdout

    def test_insecure_flag_description_in_help(self, help_output):
        """--insecure help text must mention self-signed certs."""
        assert "self-signed" in help_output.stdout

    def test_yaml_frontmatter_contains_insecure_parameter(self):
        """YAML frontmatter must expose insecure so it surfaces in the dipper UI."""
        content = SCRIPT.read_text()
        frontmatter_end = content.index("# ---", content.index("# ---") + 1)
        frontmatter = content[:frontmatter_end]
        assert "name: insecure" in frontmatter
        assert "type: bool" in frontmatter

    def test_no_hardcoded_verify_false(self):
        """Regression: no requests call site must use a literal verify=False."""
        assert "verify=False" not in SCRIPT.read_text()
