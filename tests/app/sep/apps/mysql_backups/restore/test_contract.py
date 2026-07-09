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

"""Run the derived-router contract suite against the migrated MySQL Restores app.

The shared :class:`DerivedRouterContractTests` exercises the body-independent
derived surface (schema, list, detail, 404, delete, execute, conflict,
status-filter, route presence/absence, auth) against the real
``mysql_backups.restore`` definition. The create/update methods are overridden
here with a hand-built body because the generic Polyfactory pass over the create
model trips the ``backup_source`` shell-safe validator. Restore declares no
``connectivity_check`` / ``detail_response_builder`` / ``response_context_provider``,
so the connectivity, detail-model, and injected-extras suite methods skip.
"""

from typing import Any

from fastapi import status

from app.sep.apps.framework.spec import RESERVED_FORM_KEY
from app.sep.apps.mysql_backups.models import BackupType
from app.sep.apps.mysql_backups.restore.app import app as restore_app
from tests.app.factories import MOCK_CREATED_SERVICE_ID
from tests.app.sep.apps.framework.contract_suite import (
    app_base_url,
    DerivedRouterContractTests,
)
from tests.app.sep.apps.framework.kit import (
    SEEDED_TASK_NAME,
    SYNTH_EXECUTOR_HOST,
    SYNTH_SERVICE_HOST,
    SYNTH_SERVICE_PORT,
)

_NEW_TASK_NAME = "contract-new-restore"
_UNKNOWN_TASK_NAME = "contract-unknown-restore"


def _valid_restore_body(
    *, task_name: str = _NEW_TASK_NAME, backup_type: BackupType = BackupType.MYDUMPER
) -> dict[str, Any]:
    """Return a valid restore create/update body resolving against the kit mocks.

    Pairs the seeded MySQL service / executor host with a shell-safe
    ``backup_source`` so the field validator passes; restore declares no per-mode
    field gates, so the same body is valid for every ``backup_type``.
    """
    return {
        "task_name": task_name,
        "hostname": SYNTH_EXECUTOR_HOST,
        "service_id": str(MOCK_CREATED_SERVICE_ID),
        "backup_type": backup_type.value,
        "backup_source": "/var/backups/latest",
        "datadir": "/var/lib/mysql",
    }


class TestRestoreContract(DerivedRouterContractTests):
    """Assert the restore app's derived HTTP surface, knob by knob.

    ``remapped_username`` is ``None``: the app wires no response context provider
    (its ``response_builder`` stamps ``backup_type`` / ``hostname`` and leaves
    ``created_by`` as the raw id), so the injected-extras tests do not apply.
    """

    app_def = restore_app
    remapped_username = None

    def test_create_201(self, contract_client: Any, mock_task_api: Any) -> None:
        """Create a task via a real JSON POST with a valid body, returning 201.

        Restore declares no ``connectivity_check``, so the create response renders
        through the framework default builder; ``backup_type`` / ``hostname`` are
        stamped on the list/detail responses (see ``test_detail_stamps_extras``),
        not here.
        """
        base = app_base_url(self.app_def)

        response = contract_client.post(f"{base}/", json=_valid_restore_body())

        assert response.status_code == status.HTTP_201_CREATED, response.text
        assert mock_task_api.create_count == 1

    def test_detail_stamps_extras(self, contract_client: Any) -> None:
        """Assert the detail builder stamps ``backup_type`` / ``hostname`` / ``host`` / ``port``."""
        base = app_base_url(self.app_def)
        contract_client.post(f"{base}/", json=_valid_restore_body())

        response = contract_client.get(f"{base}/{_NEW_TASK_NAME}")

        assert response.status_code == status.HTTP_200_OK, response.text
        body = response.json()
        assert body["backup_type"] == BackupType.MYDUMPER.value
        assert body["hostname"] == SYNTH_EXECUTOR_HOST
        assert body["host"] == SYNTH_SERVICE_HOST
        assert body["port"] == SYNTH_SERVICE_PORT

    def test_create_422(self, contract_client: Any, mock_task_api: Any) -> None:
        """Reject a body missing the required ``backup_type`` with 422, before any POST."""
        body = _valid_restore_body()
        del body["backup_type"]
        base = app_base_url(self.app_def)

        response = contract_client.post(f"{base}/", json=body)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert mock_task_api.create_count == 0

    def test_create_threads_executor_host_to_meta_target(
        self, contract_client: Any, mock_task_api: Any
    ) -> None:
        """Assert the submitted ``HostRef`` host threads through to ``meta.target``."""
        base = app_base_url(self.app_def)

        response = contract_client.post(f"{base}/", json=_valid_restore_body())

        assert response.status_code == status.HTTP_201_CREATED, response.text
        meta = mock_task_api.last_create_payload["data"]["meta"]
        assert meta["target"] == SYNTH_EXECUTOR_HOST

    def test_update_200(self, contract_client: Any) -> None:
        """Update a task via a real ``PUT /{task_name}``, rebuilding the spec, returning 200."""
        base = app_base_url(self.app_def)

        response = contract_client.put(
            f"{base}/{SEEDED_TASK_NAME}",
            json=_valid_restore_body(task_name=SEEDED_TASK_NAME),
        )

        assert response.status_code == status.HTTP_200_OK, response.text

    def test_update_404(self, contract_client: Any) -> None:
        """``PUT /{task_name}`` 404s for an unknown task name."""
        base = app_base_url(self.app_def)

        response = contract_client.put(
            f"{base}/{_UNKNOWN_TASK_NAME}",
            json=_valid_restore_body(task_name=_UNKNOWN_TASK_NAME),
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_create_stamps_form_input(
        self, contract_client: Any, mock_task_api: Any
    ) -> None:
        """Persist the validated restore create body under ``data['_form']``.

        Overrides the generic suite method: the str-typed ``service_id`` /
        ``schema_id`` reject the kit's int reference ids, so a hand-built body is
        used in place of the Polyfactory pass.
        """
        base = app_base_url(self.app_def)
        body = _valid_restore_body()

        response = contract_client.post(f"{base}/", json=body)

        assert response.status_code == status.HTTP_201_CREATED, response.text
        expected = self.app_def.create_model.model_validate(body).model_dump(
            mode="json"
        )
        assert mock_task_api.last_create_payload["data"][RESERVED_FORM_KEY] == expected

    def test_update_round_trips_stored_form(
        self, contract_client: Any, mock_task_api: Any
    ) -> None:
        """Assert the stored restore ``_form`` re-validates and re-stamps on PUT."""
        base = app_base_url(self.app_def)
        task_name = "contract-roundtrip-restore"
        create = contract_client.post(
            f"{base}/", json=_valid_restore_body(task_name=task_name)
        )
        assert create.status_code == status.HTTP_201_CREATED, create.text
        stored_form = mock_task_api.last_create_payload["data"][RESERVED_FORM_KEY]

        response = contract_client.put(f"{base}/{task_name}", json=stored_form)

        assert response.status_code == status.HTTP_200_OK, response.text
        assert (
            mock_task_api.last_update_payload["data"][RESERVED_FORM_KEY] == stored_form
        )
