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

"""Frontmatter regression tests for the PostgreSQL snippet ``dbname`` parameter.

Several PostgreSQL snippets gain a configurable target-database parameter
(``dbname``, default ``postgres``) so every ``psql`` call connects to a real
database. These scripts' frontmatter is hand-edited YAML-in-comments; a typo
silently drops the parameter or raises when the execution form loads. This
module loads each real snippet through the production parsing path and asserts
the ``dbname`` parameter parses cleanly with the expected default, type, and
form metadata.
"""

import pytest

from app.sep.snippets.models.meta import SnippetMetaParameterType
from app.sep.snippets.models.snippet import BaseSnippet

# The PostgreSQL snippet scripts that gain an optional ``dbname`` parameter.
# Excludes ``postgresql_pg_gather.sh`` / ``postgresql_query_tuning.sh`` (already
# ship a required ``dbname``) and ``postgresql_exporter_error_check.sh`` (no psql
# call).
POSTGRESQL_DBNAME_SCRIPTS = (
    "postgresql_archive_failed_check.sh",
    "postgresql_commit_ratio_check.sh",
    "postgresql_config_files.sh",
    "postgresql_deadlocks_check.sh",
    "postgresql_is_down_uptime_check.sh",
    "postgresql_lock_conflicts_check.sh",
    "postgresql_log_extractor.sh",
    "postgresql_max_connections_check.sh",
    "postgresql_replication_lag_check.sh",
    "postgresql_transaction_duration_too_many_locks_acquired_check.sh",
    "postgresql_wraparound_check.sh",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", POSTGRESQL_DBNAME_SCRIPTS)
async def test_dbname_parameter_parses(filename):
    """Verify each PostgreSQL snippet declares a valid ``dbname`` parameter."""
    snippet = await BaseSnippet.from_path(filename, update_meta=True)

    result = snippet.validated_parameters
    assert result.errors == []

    dbname_params = [param for param in result.parameters if param.name == "dbname"]
    assert len(dbname_params) == 1, f"{filename} must declare exactly one dbname param"

    dbname = dbname_params[0]
    assert dbname.default == "postgres"
    assert dbname.py_type is SnippetMetaParameterType.STR
    assert dbname.label, f"{filename} dbname param must have a label"
    assert dbname.description, f"{filename} dbname param must have a description"
