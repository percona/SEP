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

"""Define tests for the app.sep.plugins.checksums.deps module."""

import shlex
from collections import defaultdict
from unittest.mock import AsyncMock, patch

import pytest

from app.sep.plugins.checksums.deps import (
    _assemble_checksum_payload,
    build_checksum_task,
    build_checksums_api_task_response,
    build_checksums_task_payload,
    DEFAULT_RECURSION_DSN_TABLE,
)
from app.sep.plugins.checksums.models import (
    ChecksumsCreate,
    ChecksumTaskResponse,
    ChecksumTaskWrite,
)
from app.tasks.anonymizer.entities import PIIEntity
from app.tasks.models import Task, TaskBackendEnum, TaskOwner, TaskWrite
from tests.app.factories import TaskFactory


def _make_checksums_task(
    created_by: str | None = None, last_updated_by: str | None = None
) -> Task:
    return TaskFactory.build(
        name="test-checksums",
        owner=TaskOwner.CHECKSUMS,
        backend=TaskBackendEnum.PROXY,
        is_template=False,
        protected=False,
        alert_on_fail=False,
        data={
            "task": "run-command",
            "meta": {
                "command": "pt-table-checksum",
                "args": "--recursion-method=processlist",
                "target": "host1",
                "_service_name": "test-svc",
                "_service_host": "127.0.0.1",
                "_service_port": 3306,
            },
        },
        created_by=created_by,
        last_updated_by=last_updated_by,
    )


class TestChecksumsJinjaFormDeps:
    """Tests for the Jinja2 / HTML-form path (build_checksums_task_payload)."""

    @pytest.mark.asyncio
    async def test_build_checksums_task_payload_dsn_recursion_defaults_empty_dsn_table(
        self,
        created_service,
        mock_remote_api,
    ):
        """Assert blank dsn_table defaults to D=percona,t=dsns in the checksums command."""
        mock_remote_api.get = AsyncMock(return_value=created_service.model_dump())
        created_checksums = ChecksumsCreate(
            task_name="checksums-test",
            hostname="localhost",
            service_id=created_service.id,
            recursion_method="dsn",
            dsn_table="",
        )

        generated_task = await build_checksums_task_payload(
            created_checksums,
            mock_remote_api,
        )

        assert isinstance(generated_task, TaskWrite)
        assert generated_task.owner == TaskOwner.CHECKSUMS
        args = shlex.split(generated_task.data["meta"]["args"])
        recursion_arg = next(
            (arg for arg in args if arg.startswith("--recursion-method=")),
            "",
        )
        assert recursion_arg
        assert DEFAULT_RECURSION_DSN_TABLE in recursion_arg


class TestChecksumsJsonApiDeps:
    """Tests for the JSON API path (build_checksum_task) and form/API parity."""

    @pytest.mark.asyncio
    async def test_form_and_json_paths_produce_identical_task_write(
        self,
        created_service,
        mock_remote_api,
    ):
        """Assert build_checksums_task_payload and build_checksum_task produce identical TaskWrite."""
        service_dump = created_service.model_dump()
        mock_remote_api.get = AsyncMock(return_value=service_dump)

        common_fields = {
            "task_name": "parity-check",
            "hostname": "host1",
            "service_id": created_service.id,
            "databases": "mydb",
            "tables": "mydb.mytable",
            "recursion_method": "processlist",
            "dsn_table": "",
            "pause_file": "",
            "binary_index": False,
            "explain_arg": False,
            "fail_on_stopped_replication": False,
            "truncate_replicate_table": False,
            "progress": "time,10",
            "set_vars": "",
            "max_load": "Threads_running=50",
            "chunk_time": "0.5",
            "max_lag": "150",
            "alert_on_fail": False,
        }

        form_input = ChecksumsCreate(**common_fields, extra_args="")
        json_input = ChecksumTaskWrite(**common_fields)

        form_result = await build_checksums_task_payload(form_input, mock_remote_api)
        mock_remote_api.get = AsyncMock(return_value=service_dump)
        json_result = await build_checksum_task(json_input, mock_remote_api)

        assert form_result.model_dump() == json_result.model_dump()


class TestChecksumsPayloadAssembly:
    """Tests for the shared private helper _assemble_checksum_payload."""

    def test_dsn_expansion_does_not_mutate_input(self, created_service):
        """Assert _assemble_checksum_payload does not mutate the recursion_method argument."""
        original_recursion_method = "dsn"

        _assemble_checksum_payload(
            created_service,
            task_name="test",
            hostname="host1",
            recursion_method=original_recursion_method,
            dsn_table="",
            databases="",
            tables="",
            pause_file="",
            binary_index=False,
            explain_arg=False,
            fail_on_stopped_replication=False,
            truncate_replicate_table=False,
            progress="",
            set_vars="",
            max_load="",
            chunk_time="",
            max_lag="",
            alert_on_fail=False,
        )

        assert original_recursion_method == "dsn"

    def test_dsn_expansion_uses_default_dsn_table_when_empty(self, created_service):
        """Assert empty dsn_table falls back to D=percona,t=dsns in the expanded arg."""
        result = _assemble_checksum_payload(
            created_service,
            task_name="test",
            hostname="host1",
            recursion_method="dsn",
            dsn_table="",
            databases="",
            tables="",
            pause_file="",
            binary_index=False,
            explain_arg=False,
            fail_on_stopped_replication=False,
            truncate_replicate_table=False,
            progress="",
            set_vars="",
            max_load="",
            chunk_time="",
            max_lag="",
            alert_on_fail=False,
        )

        args = shlex.split(result.data["meta"]["args"])
        recursion_arg = next(
            (a for a in args if a.startswith("--recursion-method=")), ""
        )
        assert DEFAULT_RECURSION_DSN_TABLE in recursion_arg

    def test_dsn_expansion_uses_provided_dsn_table(self, created_service):
        """Assert a custom dsn_table is used verbatim in the expanded recursion arg."""
        custom_dsn_table = "D=mydb,t=custom_dsns"

        result = _assemble_checksum_payload(
            created_service,
            task_name="test",
            hostname="host1",
            recursion_method="dsn",
            dsn_table=custom_dsn_table,
            databases="",
            tables="",
            pause_file="",
            binary_index=False,
            explain_arg=False,
            fail_on_stopped_replication=False,
            truncate_replicate_table=False,
            progress="",
            set_vars="",
            max_load="",
            chunk_time="",
            max_lag="",
            alert_on_fail=False,
        )

        args = shlex.split(result.data["meta"]["args"])
        recursion_arg = next(
            (a for a in args if a.startswith("--recursion-method=")), ""
        )
        assert custom_dsn_table in recursion_arg

    @pytest.mark.parametrize(
        "recursion_method", ["processlist", "hosts", "none", "default"]
    )
    def test_non_dsn_recursion_methods_are_not_expanded(
        self, recursion_method, created_service
    ):
        """Assert non-DSN recursion methods are forwarded as-is without dsn= expansion."""
        result = _assemble_checksum_payload(
            created_service,
            task_name="test",
            hostname="host1",
            recursion_method=recursion_method,
            dsn_table="D=percona,t=dsns",
            databases="",
            tables="",
            pause_file="",
            binary_index=False,
            explain_arg=False,
            fail_on_stopped_replication=False,
            truncate_replicate_table=False,
            progress="",
            set_vars="",
            max_load="",
            chunk_time="",
            max_lag="",
            alert_on_fail=False,
        )

        args_str = result.data["meta"]["args"]
        assert "dsn=" not in args_str

    def test_optional_string_fields_are_omitted_when_empty(self, created_service):
        """Assert that empty optional string fields do not appear in the assembled args."""
        result = _assemble_checksum_payload(
            created_service,
            task_name="test",
            hostname="host1",
            recursion_method="processlist",
            dsn_table="",
            databases="",
            tables="",
            pause_file="",
            binary_index=False,
            explain_arg=False,
            fail_on_stopped_replication=False,
            truncate_replicate_table=False,
            progress="",
            set_vars="",
            max_load="",
            chunk_time="",
            max_lag="",
            alert_on_fail=False,
        )

        args = shlex.split(result.data["meta"]["args"])
        optional_flags = [
            "--databases",
            "--tables",
            "--pause-file",
            "--progress",
            "--set-vars",
        ]
        for flag in optional_flags:
            assert not any(a.startswith(flag) for a in args), (
                f"{flag} should not appear when empty"
            )

    def test_flag_fields_are_omitted_when_false(self, created_service):
        """Assert that boolean flag fields do not appear in args when False."""
        result = _assemble_checksum_payload(
            created_service,
            task_name="test",
            hostname="host1",
            recursion_method="processlist",
            dsn_table="",
            databases="",
            tables="",
            pause_file="",
            binary_index=False,
            explain_arg=False,
            fail_on_stopped_replication=False,
            truncate_replicate_table=False,
            progress="",
            set_vars="",
            max_load="",
            chunk_time="",
            max_lag="",
            alert_on_fail=False,
        )

        args = shlex.split(result.data["meta"]["args"])
        bool_flags = [
            "--binary-index",
            "--explain",
            "--fail-on-stopped-replication",
            "--truncate-replicate-table",
        ]
        for flag in bool_flags:
            assert flag not in args, f"{flag} should not appear when False"

    def test_flag_fields_appear_when_true(self, created_service):
        """Assert that boolean flag fields appear in args when True."""
        result = _assemble_checksum_payload(
            created_service,
            task_name="test",
            hostname="host1",
            recursion_method="processlist",
            dsn_table="",
            databases="",
            tables="",
            pause_file="",
            binary_index=True,
            explain_arg=True,
            fail_on_stopped_replication=True,
            truncate_replicate_table=True,
            progress="",
            set_vars="",
            max_load="",
            chunk_time="",
            max_lag="",
            alert_on_fail=False,
        )

        args = shlex.split(result.data["meta"]["args"])
        bool_flags = [
            "--binary-index",
            "--explain",
            "--fail-on-stopped-replication",
            "--truncate-replicate-table",
        ]
        for flag in bool_flags:
            assert flag in args, f"{flag} should appear when True"


class TestBuildChecksumsApiTaskResponse:
    """Tests for build_checksums_api_task_response username mapping."""

    def test_created_by_resolved_to_display_name_when_mapping_provided(self):
        """Assert created_by is resolved to display name when mapping contains the ID."""
        task = _make_checksums_task(created_by="uid-abc", last_updated_by=None)

        result = build_checksums_api_task_response(
            task, username_mapping={"uid-abc": "Alice"}
        )

        assert result.created_by == "Alice"

    def test_created_by_falls_back_to_raw_id_when_not_in_mapping(self):
        """Assert created_by is preserved as-is when the ID is not in the mapping."""
        task = _make_checksums_task(created_by="uid-unknown", last_updated_by=None)

        result = build_checksums_api_task_response(
            task, username_mapping={"uid-other": "Bob"}
        )

        assert result.created_by == "uid-unknown"

    def test_last_updated_by_resolved_to_display_name(self):
        """Assert last_updated_by is also resolved via the mapping."""
        task = _make_checksums_task(created_by=None, last_updated_by="uid-xyz")

        result = build_checksums_api_task_response(
            task, username_mapping={"uid-xyz": "Carol"}
        )

        assert result.last_updated_by == "Carol"

    def test_username_mapping_none_preserves_raw_ids(self):
        """Assert created_by and last_updated_by are unchanged when mapping is None."""
        task = _make_checksums_task(created_by="uid-123", last_updated_by="uid-456")

        result = build_checksums_api_task_response(task, username_mapping=None)

        assert result.created_by == "uid-123"
        assert result.last_updated_by == "uid-456"


class TestChecksumTaskResponseAnonymizedEntities:
    """Test the anonymized_entities computed field on ChecksumTaskResponse."""

    BASE_FIELDS: dict = {
        "name": "test-checksum",
        "owner": TaskOwner.CHECKSUMS,
        "backend": "nomad",
        "data": {},
        "protected": False,
        "alert_on_fail": False,
    }

    def test_explicit_mask_returns_sorted_entity_names(self) -> None:
        """Explicit anonymize_mask decodes to a sorted list of PIIEntity name strings."""
        mask = int(PIIEntity.IP_ADDRESS | PIIEntity.PERSON)
        response = ChecksumTaskResponse.model_validate(
            {**self.BASE_FIELDS, "anonymize_mask": mask}
        )
        assert response.anonymized_entities == ["IP_ADDRESS", "PERSON"]

    def test_zero_mask_returns_empty_list(self) -> None:
        """anonymize_mask=0 decodes to an empty list (no entities set)."""
        response = ChecksumTaskResponse.model_validate(
            {**self.BASE_FIELDS, "anonymize_mask": 0}
        )
        assert response.anonymized_entities == []

    def test_none_mask_falls_back_to_owner_defaults(self) -> None:
        """anonymize_mask=None falls back to anonymizer_settings.DEFAULT_ENTITIES[owner]."""
        default_entities = {PIIEntity.EMAIL_ADDRESS}
        mock_defaults = defaultdict(lambda: default_entities)
        fields = {**self.BASE_FIELDS, "anonymize_mask": None}
        with patch(
            "app.sep.plugins.checksums.models.anonymizer_settings"
        ) as mock_settings:
            mock_settings.DEFAULT_ENTITIES = mock_defaults
            response = ChecksumTaskResponse.model_validate(fields)
            result = response.anonymized_entities
        assert result == ["EMAIL_ADDRESS"]
