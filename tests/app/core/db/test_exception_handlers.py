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

"""Define tests for the app.core.db.exception_handlers module."""

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, status
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from starlette.testclient import TestClient

from app.api.deps import get_current_user
from app.core.auth.providers.casdoor.models import CasdoorUser
from app.core.config import create_app
from app.core.db.exception_handlers import register_db_capacity_handlers
from app.inventory.deps import get_session
from app.inventory.main import inventory_app
from app.sep.main import sep_app
from app.tasks.main import tasks_app

try:
    from asyncpg.exceptions import (
        InsufficientResourcesError,
        OutOfMemoryError,
        TooManyConnectionsError,
        UndefinedTableError,
    )
    from sqlalchemy.dialects.postgresql.asyncpg import (
        AsyncAdapt_asyncpg_dbapi as AsyncpgDBAPI,
    )
except ImportError:
    InsufficientResourcesError = TooManyConnectionsError = UndefinedTableError = None
    OutOfMemoryError = AsyncpgDBAPI = None

#: Skips the cases that name an asyncpg class. The ``postgresql`` Poetry group
#: is optional, so the SQLite-only install this module's subprocess test exists
#: to cover is also an install where the module itself must stay collectable.
requires_asyncpg = pytest.mark.skipif(
    TooManyConnectionsError is None, reason="asyncpg is not installed"
)


def _dialect_wrapped(driver_error: BaseException) -> DBAPIError:
    """Wrap ``driver_error`` the way the asyncpg dialect actually does.

    ``AsyncAdapt_asyncpg_connection._handle_exception`` raises its own DBAPI
    error *from* the driver's, so SQLAlchemy's ``orig`` is the translated shim
    and the asyncpg exception is one link down ``__cause__``. Constructing
    ``DBAPIError(orig=<asyncpg error>)`` directly would be a shape that never
    occurs, and a handler that only checked ``orig`` would pass against it while
    failing in production.
    """
    shim = AsyncpgDBAPI.Error(f"{type(driver_error)}: {driver_error}")
    shim.__cause__ = driver_error
    return DBAPIError.instance("SELECT 1", {}, shim, AsyncpgDBAPI.Error)


#: The shapes a database capacity refusal arrives in, as factories so that the
#: asyncpg case is not constructed at collection time where asyncpg is absent.
#: The connect-time asyncpg one is what the reported outage produced; the
#: wrapped one is what an execution-time capacity failure becomes once the
#: dialect has translated it; the SQLAlchemy one is a saturated local pool.
_CAPACITY_ERRORS = [
    pytest.param(
        lambda: TooManyConnectionsError("sorry, too many clients already"),
        id="asyncpg-too-many-connections",
        marks=requires_asyncpg,
    ),
    pytest.param(
        lambda: _dialect_wrapped(OutOfMemoryError("out of memory")),
        id="sqlalchemy-wrapped-capacity",
        marks=requires_asyncpg,
    ),
    pytest.param(
        lambda: SQLAlchemyTimeoutError("QueuePool limit of size 3 overflow 2 reached"),
        id="sqlalchemy-pool-timeout",
    ),
]

#: The directory the subprocess below runs from, so that ``app`` is importable:
#: this file sits four levels under it (``tests/app/core/db``).
_REPO_ROOT = Path(__file__).resolve().parents[4]

#: Run in a subprocess by the asyncpg-absent test. Blocks asyncpg at the import
#: finder, then imports the handler module and registers it, which is what a
#: SQLite-only install does at startup.
_IMPORT_WITHOUT_ASYNCPG = """
import sys


class _BlockAsyncpg:
    def find_spec(self, name, path=None, target=None):
        if name == "asyncpg" or name.startswith("asyncpg."):
            raise ImportError("No module named 'asyncpg'")
        return None


sys.meta_path.insert(0, _BlockAsyncpg())
for loaded in [n for n in sys.modules if n == "asyncpg" or n.startswith("asyncpg.")]:
    del sys.modules[loaded]

from fastapi import FastAPI
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from app.core.db.exception_handlers import register_db_capacity_handlers

app = FastAPI()
register_db_capacity_handlers(app)

assert SQLAlchemyTimeoutError in app.exception_handlers, "pool timeout unregistered"
registered = [getattr(cls, "__module__", "") for cls in app.exception_handlers]
assert not any(name.startswith("asyncpg") for name in registered), registered
assert "asyncpg" not in sys.modules, "asyncpg was imported after all"

from sqlalchemy.exc import DBAPIError

assert DBAPIError not in app.exception_handlers, "wrapper needs asyncpg to narrow on"
print("OK")
"""


def _app_raising_in_route(exc: Exception) -> FastAPI:
    """Build an app whose route body raises ``exc``."""
    app = create_app()

    @app.get("/boom")
    async def boom() -> None:
        raise exc

    return app


def _app_raising_in_dependency(exc: Exception) -> FastAPI:
    """Build an app whose route dependency raises ``exc``.

    This is the reported failure's shape: the connection is acquired while
    resolving the session dependency, so the handler body never runs.
    """
    app = create_app()

    async def failing_dependency() -> None:
        raise exc

    @app.get("/boom", dependencies=[Depends(failing_dependency)])
    async def boom() -> None:
        return None

    return app


@pytest.mark.parametrize(
    "build_app",
    [_app_raising_in_route, _app_raising_in_dependency],
    ids=["route-body", "route-dependency"],
)
@pytest.mark.parametrize("make_exc", _CAPACITY_ERRORS)
def test_capacity_failure_returns_json_503(build_app, make_exc):
    """Answer 503 with a JSON body for each capacity shape, from either site."""
    client = TestClient(build_app(make_exc()), raise_server_exceptions=False)

    response = client.get("/boom")

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "detail": "The database is temporarily unavailable. Please retry."
    }


@requires_asyncpg
def test_unrelated_database_error_still_returns_500():
    """Leave a non-capacity database error on the 500 path it takes today."""
    client = TestClient(
        _app_raising_in_route(UndefinedTableError('relation "node" does not exist')),
        raise_server_exceptions=False,
    )

    response = client.get("/boom")

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


@requires_asyncpg
def test_unrelated_wrapped_database_error_still_returns_500():
    """Re-raise a DBAPIError that wraps something other than a capacity failure.

    The wrapper registration sees every ``DBAPIError``, so this pins that it
    narrows on ``orig`` rather than turning all of them into 503s.
    """
    wrapped = DBAPIError(
        "SELECT 1", {}, orig=UndefinedTableError('relation "node" does not exist')
    )
    client = TestClient(_app_raising_in_route(wrapped), raise_server_exceptions=False)

    response = client.get("/boom")

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


@requires_asyncpg
def test_registration_covers_every_class_when_asyncpg_is_installed():
    """Register a handler for each capacity route the environment can produce."""
    app = FastAPI()

    register_db_capacity_handlers(app)

    assert SQLAlchemyTimeoutError in app.exception_handlers
    assert InsufficientResourcesError in app.exception_handlers
    assert DBAPIError in app.exception_handlers


@pytest.mark.parametrize(
    "sub_app",
    [
        pytest.param(sep_app, id="sep"),
        pytest.param(inventory_app, id="inventory"),
        pytest.param(tasks_app, id="tasks"),
    ],
)
@requires_asyncpg
def test_every_sub_application_carries_the_capacity_handlers(sub_app: FastAPI):
    """Carry the mapping on all three sub-applications, which share ``create_app``.

    The outage this fix answers hit sixteen endpoints across all three, so the
    mapping has to be inherited rather than registered per app.
    """
    assert SQLAlchemyTimeoutError in sub_app.exception_handlers
    assert InsufficientResourcesError in sub_app.exception_handlers
    assert DBAPIError in sub_app.exception_handlers


def test_registration_succeeds_without_asyncpg():
    """Import and register with asyncpg absent, as a SQLite-only install does.

    The ``postgresql`` Poetry group is optional, so the failure this guards
    against is at *import* time: an unconditional ``import asyncpg`` would take
    down every such deployment as the application loads. That cannot be
    reproduced in-process, where asyncpg is already imported, so the check runs
    in a subprocess with the package blocked at the finder.
    """
    completed = subprocess.run(
        [sys.executable, "-c", _IMPORT_WITHOUT_ASYNCPG],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().endswith("OK")


@pytest.fixture
def inventory_client_with_failing_session(
    regular_user: CasdoorUser,
) -> Iterator[TestClient]:
    """Yield an inventory client whose session dependency refuses to connect."""

    def _raise() -> None:
        raise TooManyConnectionsError("sorry, too many clients already")

    inventory_app.dependency_overrides[get_current_user] = lambda: regular_user
    inventory_app.dependency_overrides[get_session] = _raise
    yield TestClient(inventory_app, raise_server_exceptions=False)
    inventory_app.dependency_overrides = {}


@requires_asyncpg
def test_capacity_handler_wins_over_the_inventory_500_handler(
    inventory_client_with_failing_session: TestClient,
):
    """Answer 503 on the real inventory app, which has its own 500 handler.

    ``app.inventory.main`` registers a status-``500`` handler that logs and
    re-raises, which Starlette lifts out into the outer ``ServerErrorMiddleware``
    and which produced the ``text/plain`` 500 the reported outage returned. A
    class handler resolves in the inner ``ExceptionMiddleware``, so it must see
    the exception first. An app built by ``create_app`` alone has no competing
    handler and would pass even if that precedence were wrong.
    """
    response = inventory_client_with_failing_session.get("/nodes/")

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.headers["content-type"].startswith("application/json")
