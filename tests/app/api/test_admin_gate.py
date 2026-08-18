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

"""Define tests for which routes the unsafe-method admin gate reaches."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.api.deps import _NON_ADMIN_MUTATIONS, require_admin_for_unsafe_methods
from app.inventory.main import inventory_app
from app.sep.main import sep_app
from app.tasks.main import tasks_app
from app.tasks.routes import latest_task_history

UNGATED_SEP_API_PREFIXES = ("/api/oauth/", "/api/users/", "/api/config/")


def _gate_callables(route: APIRoute) -> set[Callable[..., Any]]:
    """Return the callables the route's top-level dependencies resolve to.

    :param route: The route whose resolved dependency chain to inspect.
    :return: One entry per dependency declared on the route or inherited from a
        router or app above it.
    """
    return {dependency.call for dependency in route.dependant.dependencies}


def _api_routes(app: FastAPI) -> list[APIRoute]:
    """Return every ``APIRoute`` mounted on ``app``.

    :param app: The application whose route table to read.
    :return: The mounted API routes, excluding static mounts and websockets.
    """
    return [route for route in app.routes if isinstance(route, APIRoute)]


@pytest.mark.parametrize("app", [inventory_app, tasks_app], ids=["inventory", "tasks"])
def test_every_service_route_inherits_the_admin_gate(app: FastAPI) -> None:
    """Assert the app-level gate reaches every route the service mounts.

    Membership follows from the app carrying the dependency, so a router added
    to either service later inherits the gate rather than having to remember it.
    """
    routes = _api_routes(app)
    assert routes
    for route in routes:
        assert require_admin_for_unsafe_methods in _gate_callables(route), route.path


def test_sep_api_routes_inherit_the_gate_and_the_identity_tree_does_not() -> None:
    """Assert ``/api`` inherits the gate while the identity tree stays outside it.

    The prefixes are an assertion about the current mount layout, not a runtime
    decision — ``api_router`` carries the dependency and the identity routers are
    included beside it rather than through it.
    """
    gated = set()
    ungated = set()
    for route in _api_routes(sep_app):
        if not route.path.startswith("/api/"):
            continue
        bucket = (
            gated
            if require_admin_for_unsafe_methods in _gate_callables(route)
            else ungated
        )
        bucket.add(route.path)

    assert gated
    assert ungated
    assert all(path.startswith(UNGATED_SEP_API_PREFIXES) for path in ungated), ungated
    assert not any(path.startswith(UNGATED_SEP_API_PREFIXES) for path in gated), gated


def test_the_exemption_allowlist_names_exactly_one_route() -> None:
    """Assert the gate exempts only the batch-read route.

    Each exemption is a hole in the gate, so adding one has to mean editing a
    test that names the route it opens.
    """
    assert {latest_task_history} == _NON_ADMIN_MUTATIONS
