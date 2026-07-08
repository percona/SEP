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

"""Tests for the dipper plugin Jinja2 routes."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import status

from app.sep.apps.dipper.deps import (
    get_dipper_execution_meta,
    get_dipper_script_with_meta,
)
from app.sep.apps.dipper.routes import router as dipper_jinja_router
from app.sep.apps.framework.deprecation import DeprecatedJinja2Route
from app.sep.main import sep_app
from app.sep.snippets.models.snippet import SnippetExecutionMeta


class TestDipperRouterDeprecation:
    """The dipper Jinja2 router uses the deprecation route class."""

    def test_router_uses_deprecated_route_class(self):
        """Confirm the router is constructed with ``DeprecatedJinja2Route``."""
        assert dipper_jinja_router.route_class is DeprecatedJinja2Route

    def test_legacy_route_sets_deprecation_header_and_logs(
        self,
        test_client,
        mock_inventory_api_dep,
        mock_task_api_dep,
        mock_get_username_mapping,
        caplog,
    ):
        """A real Dipper Jinja2 route emits the deprecation contract."""
        mock_inventory_api_dep.get = AsyncMock(return_value={"items": []})
        mock_task_api_dep.get = AsyncMock(return_value={})

        with (
            caplog.at_level(
                logging.WARNING, logger="app.sep.apps.framework.deprecation"
            ),
            patch("app.sep.apps.framework.deprecation.logger.warning") as warning,
        ):
            response = test_client.get("/dipper/")

        assert response.status_code == status.HTTP_200_OK
        assert response.headers["Deprecation"] == "true"
        warning.assert_called_once()
        assert "/dipper/" in warning.call_args.args[0]


@pytest.fixture
def _mock_dipper_execute_deps():
    """Replace the computed dipper-execute deps so the route resolves without the real chain."""
    sep_app.dependency_overrides[get_dipper_execution_meta] = (
        lambda: SnippetExecutionMeta(
            target="node-1",
            interpreter="bash",
            snippet_source="https://example.com/collect.sh",
            snippet_filename="collect.sh",
            md5_checksum="d" * 32,
        )
    )
    sep_app.dependency_overrides[get_dipper_script_with_meta] = lambda: SimpleNamespace(
        execution_task_name="dipper-collect-task"
    )
    yield
    sep_app.dependency_overrides = {}


@pytest.mark.usefixtures("_mock_dipper_execute_deps")
def test_dipper_execute_dispatches_via_relocated_execution_meta_dep(
    test_client, mock_task_api_dep
):
    """Resolve execution_meta through the relocated ExecutionMetaDep alias on POST /dipper/execute."""
    mock_task_api_dep.post = AsyncMock()

    response = test_client.post(
        "/dipper/execute",
        params={"service_id": 1},
        follow_redirects=False,
    )

    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_task_api_dep.post.assert_awaited_once()
    assert mock_task_api_dep.post.await_args.args[0] == "/execute/dipper-collect-task"
