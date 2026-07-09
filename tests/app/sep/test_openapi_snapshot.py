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

"""Snapshot each plugin's OpenAPI subtree against committed golden files."""

import pytest

from tests.app.sep import snapshot_utils as su

OPENAPI = su.build_plugins_openapi()
KEYS = su.configured_plugin_keys()


def _child_prefixes(key):
    """Return the ``/api/apps`` prefixes of scoped sub-apps nested under ``key``."""
    return [
        f"{su.PLUGIN_PREFIX}/{other}"
        for other in KEYS
        if other != key and other.startswith(key + "/")
    ]


@pytest.mark.parametrize("key", KEYS)
def test_openapi_subtree_matches_snapshot(key):
    """Byte-compare the plugin's OpenAPI subtree against its committed golden."""
    subtree = su.slice_openapi_subtree(
        OPENAPI, f"{su.PLUGIN_PREFIX}/{key}", _child_prefixes(key)
    )
    golden = su.SNAPSHOTS_DIR / "openapi" / f"{key.replace('/', '__')}.json"
    su.assert_or_update(golden, su.canonical_json(subtree))


def test_openapi_golden_set_is_complete():
    """Assert the committed OpenAPI goldens match the configured plugin set."""
    su.assert_golden_set_matches("openapi", {key.replace("/", "__") for key in KEYS})
