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
"""Tests for the pcs-collect-environment-valkey.sh payload script."""

from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).parents[5]
    / "app/sep/apps/dipper/payloads/pcs-collect-environment-valkey.sh"
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


class TestPcsCollectEnvironmentValkeyFrontmatter:
    """The frontmatter declares the expected Valkey environment parameters."""

    def test_frontmatter_declares_expected_parameters(self):
        """Each getopts-derived form parameter appears in the frontmatter."""
        frontmatter = _frontmatter()
        for name in ("o", "d", "i", "t", "p", "l", "c", "s"):
            assert f"name: {name}" in frontmatter

    @pytest.mark.parametrize("name", ["l", "c", "s"])
    def test_mode_flags_are_bool(self, name):
        """The Valkey mode flags (-l legacy, -c cluster, -s sentinel) are booleans."""
        assert "type: bool" in _parameter_block(_frontmatter(), name)


class TestPcsCollectEnvironmentValkeyParses:
    """The hand-authored metadata header parses without validation errors."""

    @pytest.mark.asyncio
    async def test_metadata_header_parses_without_errors(self):
        """A malformed header would surface as parameter validation errors."""
        from app.sep.snippets.models.snippet import BaseSnippet

        meta = await BaseSnippet.get_meta_by_path(SCRIPT)
        snippet = BaseSnippet(
            filename="pcs-collect-environment-valkey.sh",
            size=1,
            md5_digest="a" * 32,
            meta=meta,
        )
        assert snippet.validated_parameters.errors == []
