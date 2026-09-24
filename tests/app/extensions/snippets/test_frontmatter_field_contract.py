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

"""Pin the three run-form contract changes the authoring pass makes.

Most of that pass is wording, which ``test_frontmatter_authoring`` covers as a
corpus rule. Three of its edits change what the form accepts and what PMM Extensions
dispatches, so each is pinned here against the real snippet rather than against
a synthetic one:

* The two ``pg_gather`` / ``query_tuning`` scripts declared ``placeholder:
  5432`` on an ``int`` parameter, which reached a string-typed field and made
  Pydantic discard the whole parameter, so neither form renders a **Port**
  field. Dropping the placeholder restores it.
* ``minutes`` on the log extractors and ``dbname`` on ``pg_gather`` gain the
  default a sibling script already ships (``postgresql_log_extractor.sh`` and
  ``postgresql_config_files.sh`` respectively), and stop being required. A
  submission omitting them was rejected before and now dispatches the default.
* The extractors' ``time`` becomes ``type: datetime``, so the value reaching
  the script is the ``T``-separated form ``serialize_cli_value`` emits rather
  than whatever was typed into a text box.
"""

import pytest
from pydantic import ValidationError

from app.extensions.apps.framework.schema import IntegerField
from app.extensions.snippets.models.meta import (
    SnippetMetaParameter,
    SnippetMetaParameterType,
)
from app.extensions.snippets.models.snippet import (
    BaseSnippet,
    EXECUTOR_HOSTS_INPUT_NAME,
)
from app.extensions.snippets.schema import build_snippet_schema
from tests.app.extensions.form_schema_utils import form_field_types

PORT_RESTORED_SCRIPTS = (
    "postgresql_pg_gather.sh",
    "postgresql_query_tuning.sh",
)

# ``postgresql_query_tuning.sh`` is deliberately absent: it runs the operator's
# own statement, so the database selects the schema that statement resolves
# against and no cluster-wide value is defensible as a default.
DBNAME_DEFAULT_SCRIPTS = ("postgresql_pg_gather.sh",)

LOG_EXTRACTORS = (
    "haproxy_logs_extractor.sh",
    "mha_logs_extractor.sh",
    "mongodb_log_extractor.sh",
    "mysql_log_extractor.sh",
    "postgresql_log_extractor.sh",
    "proxysql_log_extractor.sh",
)

MINUTES_DEFAULT = 30


def _parameters(snippet: BaseSnippet) -> dict[str, SnippetMetaParameter]:
    """Return a snippet's validated parameters, keyed by name.

    :param snippet: The snippet whose parameters to collect.
    :return: Each validated parameter keyed by its declared name.
    """
    return {param.name: param for param in snippet.validated_parameters.parameters}


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", PORT_RESTORED_SCRIPTS)
async def test_port_parameter_reaches_the_form(filename):
    """Verify ``port`` parses and reaches the rendered form."""
    snippet = await BaseSnippet.from_path(filename, update_meta=True)

    assert snippet.validated_parameters.errors == []
    port = _parameters(snippet)["port"]
    assert port.py_type is SnippetMetaParameterType.INT
    assert form_field_types(build_snippet_schema(snippet))["port"] is IntegerField


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", PORT_RESTORED_SCRIPTS)
async def test_blank_port_is_omitted_from_the_command_line(filename):
    """Verify a blank **Port** is omitted, leaving libpq's default in force."""
    snippet = await BaseSnippet.from_path(filename, update_meta=True)
    model = snippet.get_execution_model()

    args = model.model_validate(
        {EXECUTOR_HOSTS_INPUT_NAME: "node1", "dbname": "sales", "port": ""}
    ).to_args_string()

    assert "--dbname sales" in args
    assert "--port" not in args


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", DBNAME_DEFAULT_SCRIPTS)
async def test_omitted_dbname_dispatches_the_default(filename):
    """Verify omitting ``dbname`` dispatches the sibling-proven default."""
    snippet = await BaseSnippet.from_path(filename, update_meta=True)
    dbname = _parameters(snippet)["dbname"]
    assert not dbname.required
    assert dbname.default == "postgres"

    args = (
        snippet.get_execution_model()
        .model_validate({EXECUTOR_HOSTS_INPUT_NAME: "node1"})
        .to_args_string()
    )

    assert "--dbname postgres" in args


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", DBNAME_DEFAULT_SCRIPTS)
async def test_cleared_dbname_is_rejected_rather_than_omitted(filename):
    """Verify a cleared Database name cannot dispatch without ``--dbname``.

    Unlike ``postgresql_config_files.sh``, this script carries no internal
    fallback and exits on a missing ``--dbname``. Declaring a default is what
    keeps the field out of the blank-optional path that would otherwise drop it
    from argv entirely.
    """
    snippet = await BaseSnippet.from_path(filename, update_meta=True)
    model = snippet.get_execution_model()

    with pytest.raises(ValidationError):
        model.model_validate({EXECUTOR_HOSTS_INPUT_NAME: "node1", "dbname": ""})


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", LOG_EXTRACTORS)
async def test_omitted_minutes_dispatches_the_default(filename):
    """Verify omitting ``minutes`` dispatches the shared default."""
    snippet = await BaseSnippet.from_path(filename, update_meta=True)
    minutes = _parameters(snippet)["minutes"]
    assert not minutes.required
    assert minutes.default == MINUTES_DEFAULT

    args = (
        snippet.get_execution_model()
        .model_validate(
            {EXECUTOR_HOSTS_INPUT_NAME: "node1", "time": "2026-06-18T04:00"}
        )
        .to_args_string()
    )

    assert f"--minutes {MINUTES_DEFAULT}" in args


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", LOG_EXTRACTORS)
async def test_submitted_timestamp_reaches_the_script_t_separated(filename):
    """Verify a submitted timestamp reaches argv T-separated, wall clock intact."""
    snippet = await BaseSnippet.from_path(filename, update_meta=True)
    assert _parameters(snippet)["time"].py_type is SnippetMetaParameterType.DATETIME

    args = (
        snippet.get_execution_model()
        .model_validate(
            {EXECUTOR_HOSTS_INPUT_NAME: "node1", "time": "2026-06-18T04:00"}
        )
        .to_args_string()
    )

    assert "--time 2026-06-18T04:00:00" in args


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", LOG_EXTRACTORS)
async def test_offset_bearing_timestamp_normalises_to_utc_without_its_offset(filename):
    """Verify an offset-carrying value converts to UTC and loses the offset.

    The date-time picker cannot produce one, so this is reachable only through
    the JSON execute path, which accepts any ISO-8601 string.
    ``serialize_cli_value`` emits ``%Y-%m-%dT%H:%M:%S`` with no ``%z``, and the
    executor's own ``date -d`` then reads the result in the executor host's
    zone. Pinned because the front matter documents that zone, and a change to
    either half would move the extraction window with nothing failing.
    """
    snippet = await BaseSnippet.from_path(filename, update_meta=True)

    args = (
        snippet.get_execution_model()
        .model_validate(
            {EXECUTOR_HOSTS_INPUT_NAME: "node1", "time": "2026-06-18T04:00:00+03:00"}
        )
        .to_args_string()
    )

    assert "--time 2026-06-18T01:00:00" in args
