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
from unittest.mock import AsyncMock

import pytest

from app.sep.plugins.checksums.deps import (
    _assemble_checksum_payload,
    build_checksums_task_payload,
)
from app.sep.plugins.checksums.models import ChecksumsCreate, ChecksumsForm
from app.sep.plugins.checksums.spec import (
    build_checksums_spec,
    DEFAULT_RECURSION_DSN_TABLE,
)
from app.sep.plugins.framework.spec import assemble_envelope, ResolvedEntities
from app.tasks.models import TaskOwner, TaskWrite


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


class TestChecksumsNomadPayloadParity:
    """Assert the Jinja form path and the model-first spec path are byte-identical."""

    @pytest.mark.asyncio
    async def test_form_and_spec_paths_produce_identical_task_write(
        self,
        created_service,
        mock_remote_api,
    ):
        """Assert the form payload and the spec-built envelope produce identical TaskWrite.

        The model-first JSON create path runs the ``ChecksumsForm`` through
        ``build_checksums_spec`` + the framework's ``assemble_envelope``; the
        Jinja path runs ``ChecksumsCreate`` through ``build_checksums_task_payload``.
        Both must produce the same Nomad payload for the same inputs.
        """
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

        form_result = await build_checksums_task_payload(
            ChecksumsCreate(**common_fields, extra_args=""), mock_remote_api
        )

        resolved = ResolvedEntities(
            service=created_service,
            entities={"service_id": created_service},
            executor_host=common_fields["hostname"],
        )
        spec_result = assemble_envelope(
            build_checksums_spec(ChecksumsForm(**common_fields), resolved),
            resolved,
            name=common_fields["task_name"],
            owner=TaskOwner.CHECKSUMS,
            alert_on_fail=common_fields["alert_on_fail"],
        )

        assert form_result.model_dump() == spec_result.model_dump()


class TestChecksumsPayloadAssembly:
    """Tests for the shared private helper _assemble_checksum_payload."""

    @staticmethod
    def _assemble(created_service, **overrides):
        """Call ``_assemble_checksum_payload`` with default kwargs, applying overrides.

        :param created_service: the service fixture forwarded as the first positional arg.
        :type created_service: Service
        :param overrides: keyword arguments overriding the assembled defaults.
        :type overrides: typing.Any
        """
        kwargs = {
            "task_name": "test",
            "hostname": "host1",
            "recursion_method": "processlist",
            "dsn_table": "",
            "databases": "",
            "tables": "",
            "pause_file": "",
            "binary_index": False,
            "explain_arg": False,
            "fail_on_stopped_replication": False,
            "truncate_replicate_table": False,
            "progress": "",
            "set_vars": "",
            "max_load": "",
            "chunk_time": "",
            "max_lag": "",
            "alert_on_fail": False,
        }
        kwargs.update(overrides)
        return _assemble_checksum_payload(created_service, **kwargs)

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

    @pytest.mark.parametrize(
        ("dsn_table_input", "expected_substring"),
        [
            ("", DEFAULT_RECURSION_DSN_TABLE),
            ("D=mydb,t=custom_dsns", "D=mydb,t=custom_dsns"),
        ],
        ids=["default_when_empty", "provided_verbatim"],
    )
    def test_dsn_expansion_recursion_arg(
        self, dsn_table_input, expected_substring, created_service
    ):
        """Assert dsn expansion uses the default dsn_table when empty, else the provided value verbatim."""
        result = self._assemble(
            created_service, recursion_method="dsn", dsn_table=dsn_table_input
        )

        args = shlex.split(result.data["meta"]["args"])
        recursion_arg = next(
            (a for a in args if a.startswith("--recursion-method=")), ""
        )
        assert expected_substring in recursion_arg

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

    @pytest.mark.parametrize(
        ("overrides", "flags", "should_appear"),
        [
            (
                {},
                ["--databases", "--tables", "--pause-file", "--progress", "--set-vars"],
                False,
            ),
            (
                {
                    "binary_index": False,
                    "explain_arg": False,
                    "fail_on_stopped_replication": False,
                    "truncate_replicate_table": False,
                },
                [
                    "--binary-index",
                    "--explain",
                    "--fail-on-stopped-replication",
                    "--truncate-replicate-table",
                ],
                False,
            ),
            (
                {
                    "binary_index": True,
                    "explain_arg": True,
                    "fail_on_stopped_replication": True,
                    "truncate_replicate_table": True,
                },
                [
                    "--binary-index",
                    "--explain",
                    "--fail-on-stopped-replication",
                    "--truncate-replicate-table",
                ],
                True,
            ),
        ],
        ids=[
            "optional_strings_omitted",
            "bool_flags_omitted_when_false",
            "bool_flags_present_when_true",
        ],
    )
    def test_optional_and_flag_fields_presence_follows_value(
        self, overrides, flags, should_appear, created_service
    ):
        """Assert optional string and boolean flags appear in args only when set.

        Empty optional string fields and ``False`` boolean flags are omitted;
        ``True`` boolean flags are emitted. The ``_assemble`` defaults supply
        empty strings and ``False`` flags, so each case only overrides what it
        exercises.
        """
        result = self._assemble(created_service, **overrides)

        args = shlex.split(result.data["meta"]["args"])
        for flag in flags:
            present = any(a.startswith(flag) for a in args)
            assert present is should_appear, (
                f"{flag} present={present}, expected {should_appear}"
            )
