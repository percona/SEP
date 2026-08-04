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
"""Tests for the side-car image's app-package strip."""

import re

from tests.sidecar.conftest import INFRASTRUCTURE_PACKAGES, SIDECAR_DIR

CONTAINERFILE = SIDECAR_DIR / "Containerfile.sidecar"

STRIP_ANCHOR = "cd $APP_HOME/app/sep/apps"
"""The ``RUN`` fragment identifying the strip block.

The block is anchored on its ``cd`` rather than on the ``find`` it wraps, so the
anchor survives a rewrite of the strip command itself.
"""

RETAINED_NAME = re.compile(r"!\s+-name\s+'?([A-Za-z0-9_]+)'?")

FIND_COMMAND = re.compile(r"\bfind\b")


def _strip_block() -> str:
    """Return the strip ``RUN`` block including its continuation lines.

    :return: The block's lines, newline-joined.
    """
    lines = CONTAINERFILE.read_text(encoding="utf-8").splitlines()
    anchored = [index for index, line in enumerate(lines) if STRIP_ANCHOR in line]

    assert anchored, f"No line containing {STRIP_ANCHOR!r} in {CONTAINERFILE}"

    block: list[str] = []
    for line in lines[anchored[0] :]:
        block.append(line)
        if not line.rstrip().endswith("\\"):
            break
    return "\n".join(block)


def test_strip_retains_exactly_the_activated_apps(embedded_profile_data: dict):
    """Assert the retained packages are the activated apps plus infrastructure."""
    retained = set(RETAINED_NAME.findall(_strip_block()))
    activated = {
        entry["MODULE_NAME"]
        for entry in embedded_profile_data["default"]["SEP"]["APPS"]
    }

    assert retained == activated | INFRASTRUCTURE_PACKAGES


def test_strip_block_holds_no_per_package_retention_step():
    """Assert the strip is one allow-list pass with nothing thinned in place."""
    assert len(FIND_COMMAND.findall(_strip_block())) == 1
