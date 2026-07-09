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

"""Snapshot each plugin's ``GET …/schema`` payload against committed golden files."""

import pytest
from fastapi import status

from tests.app.sep import snapshot_utils as su

OPENAPI = su.build_plugins_openapi()
SCHEMA_PATHS = su.discover_schema_paths(OPENAPI, set(su.configured_plugin_keys()))


@pytest.mark.parametrize("path", SCHEMA_PATHS, ids=su.schema_path_to_slug)
def test_schema_payload_matches_snapshot(test_client, path):
    """Byte-compare the plugin's ``GET …/schema`` payload against its golden."""
    response = test_client.get(path)
    assert response.status_code == status.HTTP_200_OK
    golden = su.SNAPSHOTS_DIR / "schema" / f"{su.schema_path_to_slug(path)}.json"
    su.assert_or_update(golden, su.canonical_json(response.json()))


def test_schema_golden_set_is_complete():
    """Assert the committed schema goldens match the discovered schema routes."""
    su.assert_golden_set_matches(
        "schema", {su.schema_path_to_slug(p) for p in SCHEMA_PATHS}
    )
