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

"""Frontmatter regression tests for the HAProxy snippets.

The HAProxy config-discovery and log-extractor snippets carry hand-edited
YAML-in-comments frontmatter; a typo silently drops a parameter or raises when
the execution form loads. This module loads each real snippet through the
production parsing path and asserts the metadata parses cleanly, the parameters
have the expected types/constraints, and the generated execution command is the
one SEP would dispatch.
"""

import pytest
from pydantic import ValidationError

from app.sep.snippets.models.meta import SnippetMetaParameterType
from app.sep.snippets.models.snippet import BaseSnippet, EXECUTOR_HOSTS_INPUT_NAME

HAPROXY_SNIPPETS = (
    "haproxy_config_files.sh",
    "haproxy_logs_extractor.sh",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", HAPROXY_SNIPPETS)
async def test_haproxy_snippet_metadata_parses(filename):
    """Verify each HAProxy snippet parses with a bash interpreter and no errors."""
    snippet = await BaseSnippet.from_path(filename, update_meta=True)

    assert snippet.execution_interpreter == "bash"
    assert snippet.validated_parameters.errors == []


@pytest.mark.asyncio
async def test_haproxy_config_snippet_has_no_parameters():
    """The config-discovery snippet declares no parameters (``parameters: []``)."""
    snippet = await BaseSnippet.from_path("haproxy_config_files.sh", update_meta=True)

    assert snippet.validated_parameters.parameters == []


@pytest.mark.asyncio
async def test_haproxy_logs_snippet_parameters():
    """The log-extractor declares the expected, well-typed parameters."""
    snippet = await BaseSnippet.from_path("haproxy_logs_extractor.sh", update_meta=True)

    params = {param.name: param for param in snippet.validated_parameters.parameters}
    assert set(params) == {"time", "minutes", "log-file", "output"}

    assert params["time"].required
    assert params["time"].py_type is SnippetMetaParameterType.STR

    assert params["minutes"].required
    assert params["minutes"].py_type is SnippetMetaParameterType.INT
    assert params["minutes"].ge == 1

    assert not params["log-file"].required

    assert params["output"].default == "stdout"
    assert {choice["value"] for choice in params["output"].choices} == {
        "stdout",
        "file",
    }


@pytest.mark.asyncio
async def test_haproxy_logs_snippet_builds_expected_command():
    """A valid submission produces the CLI args SEP would dispatch."""
    snippet = await BaseSnippet.from_path("haproxy_logs_extractor.sh", update_meta=True)
    model = snippet.get_execution_model()

    args = model.model_validate(
        {
            EXECUTOR_HOSTS_INPUT_NAME: "node1",
            "time": "2026-06-18 04:00:00",
            "minutes": "3",
            "log-file": "/var/log/haproxy.log",
            "output": "stdout",
        }
    ).to_args_string()

    assert "--time '2026-06-18 04:00:00'" in args
    assert "--minutes 3" in args
    assert "--log-file /var/log/haproxy.log" in args
    assert "--output stdout" in args


@pytest.mark.asyncio
async def test_haproxy_logs_snippet_rejects_non_positive_minutes():
    """``minutes`` honours the ``ge: 1`` constraint declared in the frontmatter."""
    snippet = await BaseSnippet.from_path("haproxy_logs_extractor.sh", update_meta=True)
    model = snippet.get_execution_model()

    with pytest.raises(ValidationError):
        model.model_validate(
            {
                EXECUTOR_HOSTS_INPUT_NAME: "node1",
                "time": "2026-06-18 04:00:00",
                "minutes": "0",
            }
        )
