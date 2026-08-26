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

"""Define fixtures for plugins tests.

The framework contract-suite fixtures (``contract_client``,
``unauthenticated_contract_client``, ``mock_task_api``, ``mock_inventory_api``)
live here, at the plugins-tests root, so any plugin test module that subclasses
:class:`~tests.app.sep.apps.framework.contract_suite.DerivedRouterContractTests`
inherits them by supplying only its definition — not only tests under
``framework/``. Each reads the definition under test from ``request.cls.app_def``
and mounts onto a fresh ``FastAPI`` per test, so dependency overrides never leak.
"""

from typing import get_args

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.auth.exceptions import HTTPUnauthorizedException
from app.core.auth.providers.casdoor.models import CasdoorUser
from app.core.exceptions import HTTPConflictException
from app.sep.apps.framework.apps import TaskExecutionApp
from app.sep.deps import check_for_conflicted_running_tasks, get_current_user
from app.sep.main import sep_app
from app.tasks.models import TaskBackendEnum, TaskWrite
from tests.app.factories import GeneratedTaskFactory
from tests.app.sep.apps.framework.contract_suite import (
    build_contract_client,
    mount_app,
)
from tests.app.sep.apps.framework.kit import (
    MockInventoryAPI,
    MockTaskAPI,
    SEEDED_TASK_NAME,
)


def literal_members(model: type[BaseModel], field: str) -> tuple[str, ...]:
    """Return the string ``Literal`` members a model field accepts.

    Reaches through the optional wrapper (``Literal[...] | EmptyStrToNone``) so a
    test can parametrize over the vocabulary a form declares instead of restating
    it and drifting from the model.

    :param model: The model owning the field.
    :param field: The field name whose annotation carries the ``Literal``.
    :return: The declared members, in declaration order.
    """
    return tuple(
        arg
        for member in get_args(model.model_fields[field].annotation)
        for arg in get_args(member)
        if isinstance(arg, str)
    )


@pytest.fixture
def generated_task() -> TaskWrite:
    """Return a fake generated task while creating alters."""
    mock_data = {
        "task": "run-command",
        "meta": {
            "command": "pt-online-schema-change",
            "args": "--alter=ADD COLUMN new_column INT --execute",
            "target": "localhost",
            "_schema_name": "public",
            "_table_name": "example_table",
        },
    }
    return GeneratedTaskFactory.build(data=mock_data, backend=TaskBackendEnum.PROXY)


@pytest.fixture
def _mock_check_for_conflicted_running_tasks() -> None:
    """Mock check_for_conflicted_running_tasks."""
    previous = sep_app.dependency_overrides.copy()
    sep_app.dependency_overrides[check_for_conflicted_running_tasks] = lambda: None
    yield
    sep_app.dependency_overrides = previous


@pytest.fixture
def _mock_check_for_conflicted_running_tasks_raises() -> None:
    """Mock check_for_conflicted_running_tasks to raise HTTPConflictException."""

    def raise_conflict() -> None:
        raise HTTPConflictException("Task is already running or pending.")

    previous = sep_app.dependency_overrides.copy()
    sep_app.dependency_overrides[check_for_conflicted_running_tasks] = raise_conflict
    yield
    sep_app.dependency_overrides = previous


def _raise_unauthorized() -> None:
    raise HTTPUnauthorizedException


def _bound_app_def(request: pytest.FixtureRequest) -> TaskExecutionApp:
    """Return the ``app_def`` bound on the requesting test class.

    The contract-suite fixtures are class-scoped: a
    :class:`~tests.app.sep.apps.framework.contract_suite.DerivedRouterContractTests`
    subclass binds the definition under test to ``app_def``. From a
    function-style test ``request.cls`` is ``None``, so surface the misuse
    as a clear error instead of an opaque ``AttributeError``.

    :param request: The active fixture request.
    :return: The :class:`TaskExecutionApp` definition bound on the test class.
    :raises RuntimeError: If used outside a ``DerivedRouterContractTests`` subclass.
    """
    cls = request.cls
    if cls is None or not hasattr(cls, "app_def"):
        raise RuntimeError(
            "contract-suite fixtures require a class-based test subclassing "
            "DerivedRouterContractTests with `app_def` set; they cannot be "
            "used from a function-style test."
        )
    return cls.app_def


@pytest.fixture
def mock_task_api(request: pytest.FixtureRequest) -> MockTaskAPI:
    """Return a Tasks-API mock seeded with one task owned by the bound definition.

    The seeded task carries the definition's ``list_filter.extra_params`` as
    ``data`` fields (and no ``parent``), so it satisfies the app's own derived
    list filter — a ``roots_only`` / ``extra_params`` app still lists it.
    """
    app_def = _bound_app_def(request)
    api = MockTaskAPI()
    api.seed_task(
        SEEDED_TASK_NAME,
        owner=app_def.owner,
        data_extra=app_def.list_filter.extra_params or None,
    )
    return api


@pytest.fixture
def mock_inventory_api() -> MockInventoryAPI:
    """Return an Inventory-API mock seeded at the mock-id constants."""
    return MockInventoryAPI()


@pytest.fixture
def contract_client(
    request: pytest.FixtureRequest,
    regular_user: CasdoorUser,
    mock_task_api: MockTaskAPI,
    mock_inventory_api: MockInventoryAPI,
) -> TestClient:
    """Return an authenticated contract client for the bound definition."""
    return build_contract_client(
        _bound_app_def(request),
        user=regular_user,
        tasks_api=mock_task_api,
        inventory_api=mock_inventory_api,
    )


@pytest.fixture
def unauthenticated_contract_client(
    request: pytest.FixtureRequest,
) -> TestClient:
    """Return a contract client whose auth dep raises, to exercise the 401 path."""

    def _raise_unauthorized() -> None:
        raise HTTPUnauthorizedException

    app = mount_app(_bound_app_def(request))
    app.dependency_overrides[get_current_user] = _raise_unauthorized
    return TestClient(app, raise_server_exceptions=False)
