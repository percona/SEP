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
from app.sep.apps.mysql_backups.forms import EncryptionFormat
from app.sep.apps.mysql_backups.models import BackupType
from app.sep.apps.mysql_backups.restore.app import app as restore_app
from app.sep.apps.mysql_backups.restore.models import (
    RestoreConfigAll,
    S3Tool,
    SourceTransport,
)
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


def _legacy_default(field_name: str) -> Any:
    """Return a gated field's pre-declaration default, read from the config model."""
    default = RestoreConfigAll.model_fields[field_name].default
    return getattr(default, "value", default)


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

    def _valid_update_body(self, *, task_name: str) -> dict[str, Any] | None:
        """Return the gated valid PUT body; the generic Polyfactory body 422s here.

        :param task_name: The task name stamped into the body.
        :return: A valid restore update body resolving against the kit mocks.
        """
        return _valid_restore_body(task_name=task_name)

    def test_schema_id_is_labelled_for_its_meaning(self, contract_client: Any) -> None:
        """Serve the schema field under the database it targets, not the restore verb.

        The field selects which database to restore *into*; the old label read as
        the action itself and left operators guessing what to enter.
        """
        base = app_base_url(self.app_def)

        response = contract_client.get(f"{base}/schema")

        fields = {
            field["name"]: field
            for form in response.json()["forms"]
            for field in form["fields"]
        }
        assert fields["schema_id"]["label"] == "Target database"

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

    def test_schema_pins_section_collapse_posture(self, contract_client: Any) -> None:
        """Pin every restore-form section's collapse posture and the visible fields.

        Under incident pressure the form must be completable from what is on
        screen: ``Task`` stays expanded and now carries the required
        ``backup_source`` together with the ``service_id`` it depends on, while
        every expert section is collapsible *and* collapsed. Section order is
        pinned too, since it derives from field first-appearance on the model.
        """
        base = app_base_url(self.app_def)

        response = contract_client.get(f"{base}/schema")

        assert response.status_code == status.HTTP_200_OK, response.text
        sections = response.json()["forms"]
        assert [
            (
                section["title"],
                section["collapsible"],
                section["collapsed_by_default"],
            )
            for section in sections
        ] == [
            ("Task", False, False),
            ("General", True, True),
            ("Mydumper", True, True),
            ("XtraBackup", True, True),
            ("Binlog", True, True),
        ]
        task_fields = [field["name"] for field in sections[0]["fields"]]
        assert "service_id" in task_fields
        assert "backup_source" in task_fields

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

    def test_create_local_restore_stamps_no_transport_values(
        self, contract_client: Any, mock_task_api: Any
    ) -> None:
        """Stamp a local restore without the SSH and object-store values it never uses.

        The three fields used to submit ``percona`` / ``22`` / ``s3cmd`` on every
        restore; declaring the source is what lets them stay out of the stamp.
        """
        base = app_base_url(self.app_def)
        body = _valid_restore_body()
        body["source_transport"] = SourceTransport.LOCAL.value

        response = contract_client.post(f"{base}/", json=body)

        assert response.status_code == status.HTTP_201_CREATED, response.text
        stamped = mock_task_api.last_create_payload["data"][RESERVED_FORM_KEY]
        assert stamped["ssh_user"] is None
        assert stamped["ssh_port"] is None
        assert stamped["s3_tool"] is None

    def test_create_accepts_ssh_credentials_under_an_ssh_source(
        self, contract_client: Any
    ) -> None:
        """Accept the SSH trio when the declared source is reached over SSH."""
        base = app_base_url(self.app_def)
        body = _valid_restore_body()
        body.update(
            source_transport=SourceTransport.SSH.value,
            ssh_user="deploy",
            ssh_port=2222,
            ssh_key="prod-key",
        )

        response = contract_client.post(f"{base}/", json=body)

        assert response.status_code == status.HTTP_201_CREATED, response.text

    def test_create_accepts_s3_tool_under_a_gcs_source(
        self, contract_client: Any
    ) -> None:
        """Accept ``s3_tool`` for a GCS source, which the payload still reads it for."""
        base = app_base_url(self.app_def)
        body = _valid_restore_body()
        body.update(
            backup_source="gs://bucket/backups/latest",
            source_transport=SourceTransport.GCS.value,
            s3_tool=S3Tool.AWSCLI.value,
        )

        response = contract_client.post(f"{base}/", json=body)

        assert response.status_code == status.HTTP_201_CREATED, response.text

    def test_create_accepts_a_cleared_s3_tool_select(
        self, contract_client: Any
    ) -> None:
        """Accept an emptied ``s3_tool`` select, which submits ``""`` rather than a value."""
        base = app_base_url(self.app_def)
        body = _valid_restore_body()
        body.update(
            backup_source="s3://bucket/backups/latest",
            source_transport=SourceTransport.S3.value,
            s3_tool="",
        )

        response = contract_client.post(f"{base}/", json=body)

        assert response.status_code == status.HTTP_201_CREATED, response.text

    def test_create_422_on_ssh_credentials_under_a_local_source(
        self, contract_client: Any, mock_task_api: Any
    ) -> None:
        """Reject SSH credentials a local source cannot consume, before any POST."""
        base = app_base_url(self.app_def)
        body = _valid_restore_body()
        body.update(source_transport=SourceTransport.LOCAL.value, ssh_user="deploy")

        response = contract_client.post(f"{base}/", json=body)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert mock_task_api.create_count == 0

    def test_create_422_on_gpg_password_file_without_gpg(
        self, contract_client: Any, mock_task_api: Any
    ) -> None:
        """Reject a GPG password file on a restore declaring no GPG pass."""
        base = app_base_url(self.app_def)
        body = _valid_restore_body()
        body.update(
            source_encryption=EncryptionFormat.NONE.value,
            gpg_password_file="/etc/gpg.pass",
        )

        response = contract_client.post(f"{base}/", json=body)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert mock_task_api.create_count == 0

    def test_update_round_trips_a_stamp_predating_the_source_controls(
        self, contract_client: Any, mock_task_api: Any
    ) -> None:
        """Accept an edit of a restore stamped before the source controls existed.

        A stored stamp is a full model dump, so every pre-existing one carries
        ``percona`` / ``22`` / ``s3cmd`` and the derived ``PUT`` re-submits it
        verbatim. Editing such a restore must not 422 while waiting for the
        manual backfill command to run.
        """
        base = app_base_url(self.app_def)
        task_name = "contract-legacy-restore"
        contract_client.post(f"{base}/", json=_valid_restore_body(task_name=task_name))
        legacy_form = {
            **mock_task_api.last_create_payload["data"][RESERVED_FORM_KEY],
            **{
                name: _legacy_default(name)
                for name in ("ssh_user", "ssh_port", "s3_tool")
            },
        }
        del legacy_form["source_transport"]
        del legacy_form["source_encryption"]

        response = contract_client.put(f"{base}/{task_name}", json=legacy_form)

        assert response.status_code == status.HTTP_200_OK, response.text
        restamped = mock_task_api.last_update_payload["data"][RESERVED_FORM_KEY]
        assert restamped["source_transport"] == SourceTransport.LOCAL.value
        assert restamped["ssh_user"] is None

    def test_schema_gates_transport_and_decryption_fields(
        self, contract_client: Any
    ) -> None:
        """Serve the source controls ungated and every field they govern gated.

        The gates use only ``equals`` / ``any`` / ``not``, which the renderer
        already evaluates, so no new predicate reaches a consumer.
        """
        base = app_base_url(self.app_def)

        response = contract_client.get(f"{base}/schema")

        assert response.status_code == status.HTTP_200_OK, response.text
        sections = response.json()["forms"]
        fields = {field["name"]: field for form in sections for field in form["fields"]}
        task_fields = [field["name"] for field in sections[0]["fields"]]
        assert "source_transport" in task_fields
        assert "source_encryption" in task_fields
        assert "forbidden" not in fields["source_transport"]
        assert "forbidden" not in fields["source_encryption"]
        for name in ("ssh_user", "ssh_port", "ssh_key"):
            assert fields[name]["forbidden"] == [
                {"when": {"not_equals": {"source_transport": "ssh"}}}
            ], name
        assert fields["s3_tool"]["forbidden"] == [
            {
                "when": {
                    "not": {
                        "any": [
                            {"equals": {"source_transport": "s3"}},
                            {"equals": {"source_transport": "gcs"}},
                        ]
                    }
                }
            }
        ]
        assert fields["gpg_password_file"]["forbidden"] == [
            {
                "when": {
                    "not": {
                        "any": [
                            {"equals": {"source_encryption": "gpg"}},
                            {"equals": {"source_encryption": "dual"}},
                        ]
                    }
                }
            }
        ]
