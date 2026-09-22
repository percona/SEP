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

"""Test how the probe tells Percona, Enterprise and Community MongoDB apart.

The fixtures below are trimmed ``buildInfo`` output captured from real running
nodes, not invented: a Percona Server for MongoDB 7.0 container
(``psmdbVersion`` present, ``modules: []``) and a MongoDB Enterprise 7.0
container (no ``psmdbVersion`` key at all, ``modules: ["enterprise"]``).
"""

from app.sep.apps.om_inventory.payload.probe import determine_vendor

PSMDB_BUILD_INFO = {
    "version": "7.0.40-22",
    "psmdbVersion": "7.0.40-22",
    "gitVersion": "9cedd522b7f9d950f6028736440100edd525b890",
    "modules": [],
}
ENTERPRISE_BUILD_INFO = {
    "version": "7.0.17",
    "gitVersion": "f099987179b0e9919aa2fcba25afe48f35e53ae9",
    "modules": ["enterprise"],
}
COMMUNITY_BUILD_INFO = {
    "version": "7.0.14",
    "gitVersion": "191be96bb2effd0e0308d6dbf88a1a15d9c5e6bd",
    "modules": [],
}


def test_a_psmdb_version_field_identifies_percona() -> None:
    """Detect Percona from psmdbVersion, which nothing else carries."""
    assert determine_vendor(PSMDB_BUILD_INFO) == "Percona"


def test_the_enterprise_module_identifies_enterprise() -> None:
    """Detect Enterprise from the documented module marker, with no psmdbVersion."""
    assert determine_vendor(ENTERPRISE_BUILD_INFO) == "MongoDB Enterprise"


def test_neither_marker_is_community() -> None:
    """Detect Community when neither marker is present."""
    assert determine_vendor(COMMUNITY_BUILD_INFO) == "MongoDB Community"


def test_no_build_info_collected_is_none() -> None:
    """Report no vendor when the buildInfo command failed, rather than guessing."""
    assert determine_vendor({}) is None
