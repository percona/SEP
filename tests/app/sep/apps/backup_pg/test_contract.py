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

"""Run the derived-router contract suite against the migrated backup_pg app.

The shared :class:`DerivedRouterContractTests` exercises every derived surface
(schema, list, detail, create, update, execute, delete, auth, 404, the
body-reading create conflict guard, the running-conflict update guard, and the
connectivity warning) against the real ``backup_pg`` definition. Two detail-model
checks are overridden because backup_pg's detail field is ``host`` (the kit's
synthetic app uses ``detail_only``); the protected-task update guard, which the
generic suite does not seed, is covered by the standalone test below.
"""

from fastapi import status

from app.core.auth.providers.casdoor.models import CasdoorUser
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.backup_pg.app import app as backup_pg_app
from tests.app.factories import MOCK_CREATED_SERVICE_ID
from tests.app.sep.apps.framework.contract_suite import (
    app_base_url,
    build_contract_client,
    build_valid_create_body,
    DerivedRouterContractTests,
    post_create_body,
)
from tests.app.sep.apps.framework.kit import (
    MockInventoryAPI,
    MockTaskAPI,
    SEEDED_TASK_NAME,
)


def _postgres_inventory() -> MockInventoryAPI:
    """Return an Inventory mock whose seeded service is PostgreSQL-typed."""
    api = MockInventoryAPI()
    api.seed_service(MOCK_CREATED_SERVICE_ID, service_type=ServiceTypeEnum.POSTGRESQL)
    return api


class TestBackupPgContract(DerivedRouterContractTests):
    """Assert the backup_pg app's full derived HTTP surface, knob by knob.

    ``remapped_username`` is ``None``: backup_pg wires no response context
    provider, so the username-remap and injected-``service_type`` assertions are
    skipped (its responses carry neither).
    """

    app_def = backup_pg_app
    remapped_username = None

    def test_detail_returns_detail_model(self, contract_client) -> None:
        """Assert ``GET /{name}`` carries the detail-only ``host`` field."""
        response = contract_client.get(
            f"{app_base_url(self.app_def)}/{SEEDED_TASK_NAME}"
        )

        assert response.status_code == status.HTTP_200_OK
        assert "host" in response.json()

    def test_create_returns_detail_model(self, contract_client) -> None:
        """Assert create renders like detail (carries the ``host`` field)."""
        body = build_valid_create_body(self.app_def)
        base = app_base_url(self.app_def)

        response = post_create_body(contract_client, f"{base}/", self.app_def, body)

        assert response.status_code == status.HTTP_201_CREATED
        detail = response.json()
        assert "host" in detail
        assert "service_type" not in detail
        assert "owner" not in detail
        assert "anonymize_mask" in detail
        assert "anonymized_entities" in detail
        assert "connectivity_warning" in detail

    def test_list_omits_internal_fields_and_carries_anonymization(
        self, contract_client
    ) -> None:
        """Assert list rows omit owner/service_type and carry anonymization surface.

        The generic inject-extras test skips for backup_pg (no response context
        provider), so cover the inherited anonymization fields explicitly.
        """
        response = contract_client.get(f"{app_base_url(self.app_def)}/")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        rows = body["items"] if isinstance(body, dict) else body
        row = next(r for r in rows if r["name"] == SEEDED_TASK_NAME)
        assert "service_type" not in row
        assert "owner" not in row
        assert "anonymize_mask" in row
        assert "anonymized_entities" in row

    def test_detail_omits_internal_fields_and_carries_anonymization(
        self, contract_client
    ) -> None:
        """Assert the detail body omits owner/service_type and carries anonymization."""
        response = contract_client.get(
            f"{app_base_url(self.app_def)}/{SEEDED_TASK_NAME}"
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert "service_type" not in body
        assert "owner" not in body
        assert "anonymize_mask" in body
        assert "anonymized_entities" in body

    def test_update_omits_internal_fields_and_carries_anonymization(
        self, contract_client
    ) -> None:
        """Assert the update response omits owner/service_type and carries anonymization."""
        body = build_valid_create_body(self.app_def, task_name=SEEDED_TASK_NAME)
        base = app_base_url(self.app_def)

        response = contract_client.put(f"{base}/{SEEDED_TASK_NAME}", json=body)

        assert response.status_code == status.HTTP_200_OK
        updated = response.json()
        assert "service_type" not in updated
        assert "owner" not in updated
        assert "anonymize_mask" in updated
        assert "anonymized_entities" in updated

    def test_create_extra_dep_enforced(self, contract_client, mock_task_api) -> None:
        """Assert the body-reading create guard rejects a duplicate in-flight name.

        backup_pg's guard keys on the *request body* task name (not owner-wide),
        so the conflicting task must be seeded under the create body's own name.
        """
        body = build_valid_create_body(self.app_def)
        mock_task_api.seed_running(body["task_name"], owner=self.app_def.owner)
        base = app_base_url(self.app_def)

        response = post_create_body(contract_client, f"{base}/", self.app_def, body)

        assert response.status_code == status.HTTP_409_CONFLICT

    def test_create_missing_required_field_reports_single_error(
        self, contract_client
    ) -> None:
        """Assert a missing required create field yields one validation entry."""
        body = build_valid_create_body(self.app_def)
        body.pop("stanza")
        base = app_base_url(self.app_def)

        response = post_create_body(contract_client, f"{base}/", self.app_def, body)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        stanza_errors = [
            error
            for error in response.json()["detail"]
            if error.get("loc") == ["body", "stanza"]
        ]
        assert len(stanza_errors) == 1

    def test_create_rejects_out_of_vocabulary_incremental_cycle(
        self, contract_client
    ) -> None:
        """Reject ``monday`` at create with 422 before a task exists."""
        body = build_valid_create_body(self.app_def)
        assert body is not None
        body["pgbackrest_incremental_cycle"] = "monday"
        base = app_base_url(self.app_def)

        response = post_create_body(contract_client, f"{base}/", self.app_def, body)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_update_rejects_out_of_vocabulary_incremental_cycle(
        self, contract_client
    ) -> None:
        """Reject ``monday`` at update with 422 so a bad save cannot persist."""
        body = build_valid_create_body(self.app_def, task_name=SEEDED_TASK_NAME)
        assert body is not None
        body["pgbackrest_incremental_cycle"] = "monday"
        base = app_base_url(self.app_def)

        response = contract_client.put(f"{base}/{SEEDED_TASK_NAME}", json=body)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_update_protected_task_returns_409(regular_user: CasdoorUser) -> None:
    """Assert the derived PUT rejects a protected task with 409 via the update guard."""
    tasks_api = MockTaskAPI()
    tasks_api.seed_task("protected-backup", owner=backup_pg_app.owner, protected=True)
    client = build_contract_client(
        backup_pg_app,
        user=regular_user,
        tasks_api=tasks_api,
        inventory_api=_postgres_inventory(),
    )
    body = build_valid_create_body(backup_pg_app, task_name="protected-backup")

    response = client.put(f"{app_base_url(backup_pg_app)}/protected-backup", json=body)

    assert response.status_code == status.HTTP_409_CONFLICT
