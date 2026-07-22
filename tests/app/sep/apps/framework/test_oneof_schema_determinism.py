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

"""Guard the framework's derived one-of request-body schema construction.

The ``TaskExecutionApp`` derives a create (``POST /``) and an update
(``PUT /{...}``) route from one shared ``create_model``. For a Pydantic v2
discriminated-union ("one-of") body, FastAPI builds the request-body schema per
route; that construction reads global model/definition orderings that vary with
``PYTHONHASHSEED``, so before the fix the two routes could derive divergent core
schemas — the derived update route intermittently rejecting a body the create
route accepts.

The framework now materializes the create model's validation schema once at
router-build time and resolves the shared create/update response model once, so
both routes build a single, deterministic one-of schema. These tests drive the
real HTTP stack to assert the resulting invariants: every one-of branch accepted
by create is accepted by update, an invalid discriminator is rejected by both,
and both routes render one shared response-model class. A best-effort multi-seed
subprocess sweep exercises the materialization under varying hash seeds — the
full-suite heisenbug it traces back to is not reproducible in isolation, so this
is a guard, not a trigger.
"""

import contextlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import status
from fastapi.routing import APIRoute

from app.core.auth.providers.casdoor.models import CasdoorUser
from app.sep.apps.archives import app as archives_app
from app.sep.apps.framework.apps import AppCapabilities, TaskExecutionApp
from app.sep.apps.framework.registry import get_app_registry
from tests.app.factories import CasdoorUserFactory, MOCK_DESTINATION_TABLE_ID
from tests.app.sep.apps.framework.contract_suite import (
    app_base_url,
    build_contract_client,
)
from tests.app.sep.apps.framework.kit import (
    MockInventoryAPI,
    MockTaskAPI,
    synth_app,
    synth_oneof_app,
    SYNTH_OWNER,
)

REPO_ROOT = Path(__file__).resolve().parents[5]

_SEEDED = "seeded-task"

# Shared by the in-process archives test and the subprocess probe so a new
# required field on archives' create model updates one place, not two.
_ARCHIVES_VALID_BODY: dict[str, Any] = {
    "task_name": "new-archive",
    "hostname": "exec-host",
    "service_id": 1,
    "swap_drop": 0,
    "source": {"mode": "table", "source_db": 1, "source_table": 1},
    "destination": {"mode": "table", "dest_table": MOCK_DESTINATION_TABLE_ID},
    "where": "id < 100",
}

_VALID_SYNTH_BODIES: list[dict[str, Any]] = [
    {"source": {"mode": "alpha", "alpha_value": "v"}},
    {"source": {"mode": "beta", "beta_count": 3}},
    {
        "source": {"mode": "beta", "beta_count": 3},
        "sink": {"mode": "file", "file_path": "/tmp/out"},
    },
    {
        "source": {"mode": "alpha", "alpha_value": "v"},
        "sink": {"mode": "table", "table_name": "dest"},
    },
]

# Malformed one-of bodies that must 422 identically on both routes: unknown and
# missing discriminators on the required ``source`` union, and unknown and missing
# discriminators on the *optional* ``sink`` union (the archives destination/host
# analog the materialization fix touches — a naive fix could loosen it unnoticed).
_INVALID_ONEOF_BODIES: list[dict[str, Any]] = [
    {"source": {"mode": "gamma", "alpha_value": "v"}},
    {"source": {"alpha_value": "v"}},
    {
        "source": {"mode": "alpha", "alpha_value": "v"},
        "sink": {"mode": "nope", "file_path": "/tmp/out"},
    },
    {
        "source": {"mode": "alpha", "alpha_value": "v"},
        "sink": {"file_path": "/tmp/out"},
    },
]


def _synth_body(**overrides: Any) -> dict[str, Any]:
    """Return a valid synthetic one-of create body with ``overrides`` merged in."""
    body: dict[str, Any] = {
        "task_name": "new-task",
        "service_id": 1,
        "host": "exec-host",
        "mode": "x",
        "source": {"mode": "alpha", "alpha_value": "v"},
    }
    body.update(overrides)
    return body


def _synth_client(regular_user: CasdoorUser) -> Any:
    """Return an authenticated contract client for the synthetic one-of app."""
    tasks_api = MockTaskAPI()
    tasks_api.seed_task(_SEEDED, owner=SYNTH_OWNER)
    return build_contract_client(
        synth_oneof_app(),
        user=regular_user,
        tasks_api=tasks_api,
        inventory_api=MockInventoryAPI(),
    )


def _create_and_update_routes(
    app_def: TaskExecutionApp,
) -> tuple[APIRoute, APIRoute]:
    """Return the derived ``POST /`` create and ``PUT /{...}`` update routes.

    Selects by (method, path) rather than method alone, so the collection-root
    create route is not shadowed by the ``POST /{task_name}/execute`` route.
    """
    create = update = None
    for route in app_def.build_router().routes:
        if not isinstance(route, APIRoute):
            continue
        if "POST" in route.methods and route.path == "/":
            create = route
        elif "PUT" in route.methods:
            update = route
    assert create is not None
    assert update is not None
    return create, update


class TestDerivedOneOfBody:
    """Drive the derived create/update routes over the real body-parsing graph."""

    _BASE = app_base_url(synth_oneof_app())

    @pytest.mark.parametrize("branch", _VALID_SYNTH_BODIES)
    def test_create_accepted_body_is_update_accepted(
        self, regular_user: CasdoorUser, branch: dict[str, Any]
    ) -> None:
        """Assert every branch create accepts, the update route accepts too."""
        client = _synth_client(regular_user)
        body = _synth_body(**branch)
        assert (
            client.post(f"{self._BASE}/", json=body).status_code
            == status.HTTP_201_CREATED
        )
        assert (
            client.put(f"{self._BASE}/{_SEEDED}", json=body).status_code
            == status.HTTP_200_OK
        )

    @pytest.mark.parametrize("branch", _INVALID_ONEOF_BODIES)
    def test_invalid_oneof_body_rejected_by_both_routes(
        self, regular_user: CasdoorUser, branch: dict[str, Any]
    ) -> None:
        """Assert a malformed one-of body is a clean 422 on create and update.

        Guards against "fixing" the flake by loosening a union — a body with a
        bogus or missing discriminator must never validate on either route.
        """
        client = _synth_client(regular_user)
        body = _synth_body(**branch)
        assert (
            client.post(f"{self._BASE}/", json=body).status_code
            == status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        assert (
            client.put(f"{self._BASE}/{_SEEDED}", json=body).status_code
            == status.HTTP_422_UNPROCESSABLE_ENTITY
        )


class TestSharedCreateResponseModel:
    """Assert create and update render one shared response-model class."""

    def test_non_connectivity_app_shares_response_model(self) -> None:
        """Assert create and update reference the same response model object.

        This is the pass-through case: ``synth_oneof_app`` sets no
        ``create_response_builder`` and leaves connectivity off, so
        ``_resolve_create_response_model`` returns the same ``detail_model``
        whether resolved once or twice — it passes identically against the
        unfixed code. It pins that case; the class's shared-class promise is
        actually discriminated by
        ``test_connectivity_app_shares_one_derived_response_model``.
        """
        create, update = _create_and_update_routes(synth_oneof_app())
        assert create.response_model is update.response_model

    def test_connectivity_app_shares_one_derived_response_model(self) -> None:
        """Assert the auto-derived ``<App>CreateResponse`` is built once and shared.

        Resolving it per route would mint two distinct classes carrying the same
        name, whose colliding schema refs are what perturbed the derived body
        schema under hash randomization. One shared instance removes the collision.
        """
        app_def = synth_app(
            connectivity_check=True,
            capabilities=AppCapabilities(update=True),
        )
        create, update = _create_and_update_routes(app_def)
        assert create.response_model is update.response_model


def archives_oneof_probe() -> tuple[int, int]:
    """Build the archives router with the full registry loaded and PUT/POST a body.

    Loads the whole app registry — importing every app and building each router,
    the production-equivalent model namespace the derived one-of schema is
    constructed against — then mounts a fresh archives contract client and drives
    the derived create and update routes with a known-valid one-of body.

    :return: The ``(POST, PUT)`` HTTP status codes for the valid body.
    """
    registry = list(get_app_registry())
    built = 0
    for entry in registry:
        # A broken sibling app must not abort the probe, but the probe's whole
        # point is the size of the loaded namespace — a thinned one would still
        # go green, so require nearly all siblings to build.
        with contextlib.suppress(Exception):
            _ = entry.api_router
            built += 1
    assert built >= len(registry) - 1, (
        f"only {built}/{len(registry)} sibling routers built; the loaded one-of "
        "namespace is thinner than the production-equivalent set the probe claims"
    )

    inventory = MockInventoryAPI()
    inventory.seed_table(MOCK_DESTINATION_TABLE_ID)
    tasks_api = MockTaskAPI()
    tasks_api.seed_task(_SEEDED, owner=archives_app.owner)
    client = build_contract_client(
        archives_app,
        user=CasdoorUserFactory.build(),
        tasks_api=tasks_api,
        inventory_api=inventory,
    )
    base = app_base_url(archives_app)
    body = _ARCHIVES_VALID_BODY
    return (
        client.post(f"{base}/", json=body).status_code,
        client.put(f"{base}/{_SEEDED}", json=body).status_code,
    )


class TestMultiSeedBodySchema:
    """Sweep the full-registry archives one-of path across several hash seeds.

    Each seed runs in its own interpreter (``PYTHONHASHSEED`` is fixed at start),
    loads the full app registry — the production-equivalent model namespace — and
    drives the real archives create and update routes over the HTTP stack. The
    divergence this traces to is a full-suite global-state phenomenon that is not
    reproducible in a bounded harness (confirmed: 50 seeds against ``main`` never
    reproduce it), so a green sweep is a regression guard, not a trigger.
    """

    _SUBPROCESS = (
        "from tests.app.sep.apps.framework.test_oneof_schema_determinism import"
        " archives_oneof_probe;"
        "import sys; sys.exit(0 if archives_oneof_probe() == (201, 200) else 1)"
    )

    @pytest.mark.parametrize("seed", range(3))
    def test_archives_valid_body_accepted_under_seed(self, seed: int) -> None:
        """Assert the archives routes accept a valid body under ``seed``."""
        result = subprocess.run(
            [sys.executable, "-c", self._SUBPROCESS],
            env={**os.environ, "PYTHONHASHSEED": str(seed)},
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"seed={seed} rejected a valid archives one-of body\n{result.stderr}"
        )
