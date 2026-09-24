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

"""Run the derived-router contract suite against the migrated Checksums app.

The shared :class:`DerivedRouterContractTests` exercises every derived surface
(schema, list, detail, create, update, execute, delete, auth, 404, conflict,
connectivity warning, injected extras, and the running-conflict update guard)
against the real ``checksums`` definition. The checksums-specific
protected-task update guard, which the generic suite does not seed, is covered
by the standalone integration test below.
"""

from fastapi import status

from app.core.auth.providers.casdoor.models import CasdoorUser
from app.extensions.apps.checksums.app import app as checksums_app
from tests.app.extensions.apps.framework.contract_suite import (
    app_base_url,
    build_contract_client,
    build_valid_create_body,
    DerivedRouterContractTests,
)
from tests.app.extensions.apps.framework.kit import MockInventoryAPI, MockTaskAPI


class TestChecksumsContract(DerivedRouterContractTests):
    """Assert the checksums app's full derived HTTP surface, knob by knob."""

    app_def = checksums_app
    create_body_overrides = {"defaults_file": ""}


def test_update_protected_task_returns_409(regular_user: CasdoorUser) -> None:
    """Assert the derived PUT rejects a protected task with 409 via the update guard."""
    tasks_api = MockTaskAPI()
    tasks_api.seed_task("protected-checksum", owner=checksums_app.owner, protected=True)
    client = build_contract_client(
        checksums_app,
        user=regular_user,
        tasks_api=tasks_api,
        inventory_api=MockInventoryAPI(),
    )
    body = build_valid_create_body(
        checksums_app,
        task_name="protected-checksum",
        create_body_overrides={"defaults_file": ""},
    )

    response = client.put(
        f"{app_base_url(checksums_app)}/protected-checksum", json=body
    )

    assert response.status_code == status.HTTP_409_CONFLICT
