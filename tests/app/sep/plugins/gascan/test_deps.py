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

"""Define tests for the app.sep.plugins.gascan.deps module."""

import shlex

import pytest

from app.sep.plugins.gascan.deps import (
    _assemble_gascan_payload,
    build_gascan_task,
    parse_gascan_task_args,
)
from app.sep.plugins.gascan.models import GascanCreate, GascanTaskWrite
from app.tasks.models import TaskOwner, TaskWrite


class TestGascanPayloadAssembly:
    """Tests for gascan task payload assembly."""

    def test_assemble_gascan_payload_full_args(self):
        """Assert all gascan CLI flags are included when values are provided."""
        payload = _assemble_gascan_payload(
            task_name="gascan-test",
            hostname="executor1",
            playbook="backup.yml",
            limit="web",
            override="env=prod",
            alert_on_fail=True,
        )

        assert payload.owner == TaskOwner.GASCAN
        assert payload.name == "gascan-test"
        assert payload.target == "executor1"
        assert payload.alert_on_fail is True
        meta = payload.data["meta"]
        assert meta["command"] == "gascan"
        assert meta["target"] == "executor1"
        args = shlex.split(meta["args"])
        assert "--playbook=backup.yml" in args
        assert "--limit=web" in args
        assert "--override=env=prod" in args

    def test_assemble_gascan_payload_omits_empty_optional_args(self):
        """Assert empty limit and override are not passed to the command."""
        payload = _assemble_gascan_payload(
            task_name="minimal",
            hostname="host1",
            playbook="run.yml",
        )
        args = shlex.split(payload.data["meta"]["args"])
        assert args == ["--playbook=run.yml"]

    @pytest.mark.asyncio
    async def test_form_and_json_paths_produce_identical_task_write(self):
        """Assert HTML form and JSON builders produce the same TaskWrite."""
        common_fields = {
            "task_name": "parity-check",
            "hostname": "host1",
            "playbook": "deploy.yml",
            "limit": "db",
            "override": "dry_run=false",
            "alert_on_fail": True,
        }
        form_input = GascanCreate(**common_fields)
        json_input = GascanTaskWrite(**common_fields)

        from app.sep.plugins.gascan.deps import build_gascan_task_payload

        form_result = await build_gascan_task_payload(form_input)
        json_result = build_gascan_task(json_input)

        assert isinstance(form_result, TaskWrite)
        assert form_result.model_dump() == json_result.model_dump()

    def test_parse_gascan_task_args_round_trip(self):
        """Assert parse_gascan_task_args recovers form values from meta args."""
        meta = {
            "args": "--playbook=backup.yml --limit=web --override=env=prod",
        }
        parsed = parse_gascan_task_args(meta)
        assert parsed["playbook"] == "backup.yml"
        assert parsed["limit"] == "web"
        assert parsed["override"] == "env=prod"
