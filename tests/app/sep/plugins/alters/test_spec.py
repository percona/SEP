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

"""Define tests for the app.sep.plugins.alters.spec pure task builder."""

from app.sep.connectivity import (
    CONNECTIVITY_META_HOST_KEY,
    CONNECTIVITY_META_PORT_KEY,
    CONNECTIVITY_META_SERVICE_TYPE_KEY,
)
from app.sep.inventory import CreatedService
from app.sep.plugins.alters.models import AltersCreate
from app.sep.plugins.alters.spec import _build_dsn_with_service, build_alters_spec
from app.tasks.models import TaskBackendEnum, TaskOwner, TaskWrite


def test_build_dsn_with_service_branches():
    """DSN prefix passthrough, remote h+P, localhost P-only, and unchanged DSN."""
    assert _build_dsn_with_service("h=x,D=y", "10.0.0.1", 3306) == "h=x,D=y"
    assert _build_dsn_with_service("P=3307,D=y", "10.0.0.1", 3306) == "P=3307,D=y"
    assert (
        _build_dsn_with_service("D=a,t=b", "10.0.0.5", 3306)
        == "h=10.0.0.5,P=3306,D=a,t=b"
    )
    assert _build_dsn_with_service("D=a,t=b", "localhost", 3306) == "P=3306,D=a,t=b"
    assert _build_dsn_with_service("D=a,t=b", "localhost", None) == "D=a,t=b"


def test_build_alters_spec_builds_parent_execute_envelope(
    created_service: CreatedService,
):
    """Test build_alters_spec assembles the run-command pt-osc execute envelope."""
    body = AltersCreate(
        task_name="my-alter",
        hostname="exec-host",
        service_id=1,
        schema_name="app",
        table_name="users",
        alter="ADD COLUMN x INT",
        recursion_method="processlist",
    )

    task = build_alters_spec(created_service, "app", "users", body)

    assert isinstance(task, TaskWrite)
    assert task.owner == TaskOwner.ALTERS
    assert task.backend == TaskBackendEnum.PROXY
    assert task.name == "my-alter"

    meta = task.data["meta"]
    assert task.data["task"] == "run-command"
    assert meta["target"] == "exec-host"
    assert meta["command"] == "pt-online-schema-change"
    assert "--recursion-method=processlist" in meta["args"]
    assert "--execute" in meta["args"]
    assert meta["_schema_name"] == "app"
    assert meta["_table_name"] == "users"
    assert meta["_service_name"] == created_service.name
    assert meta[CONNECTIVITY_META_HOST_KEY] == created_service.node.address
    assert meta[CONNECTIVITY_META_PORT_KEY]
    assert meta[CONNECTIVITY_META_SERVICE_TYPE_KEY] == created_service.type.value


def test_build_alters_spec_dsn_recursion_embeds_dsn_table(
    created_service: CreatedService,
):
    """Test a dsn recursion method embeds the resolved dsn_table in the args."""
    body = AltersCreate(
        task_name="my-alter",
        hostname="exec-host",
        service_id=1,
        schema_name="app",
        table_name="users",
        alter="ADD COLUMN x INT",
        recursion_method="dsn",
        dsn_table="D=custom,t=dsns",
    )

    task = build_alters_spec(created_service, "app", "users", body)

    assert "--recursion-method=dsn=" in task.data["meta"]["args"]
    assert "D=custom,t=dsns" in task.data["meta"]["args"]
