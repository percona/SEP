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
from app.sep.plugins.alters.spec import build_alters_spec
from app.tasks.models import TaskBackendEnum, TaskOwner, TaskWrite

REMOTE_SERVICE_PORT = 3306


def _service_at(service: CreatedService, address: str) -> CreatedService:
    """Return a copy of ``service`` whose node address is ``address``."""
    return service.model_copy(
        update={"node": service.node.model_copy(update={"address": address})}
    )


def _build_body(**overrides: object) -> AltersCreate:
    """Build a valid manual-target AltersCreate, applying ``overrides``."""
    fields: dict[str, object] = {
        "task_name": "my-alter",
        "hostname": "exec-host",
        "service_id": 1,
        "schema_name": "app",
        "table_name": "users",
        "alter": "ADD COLUMN x INT",
        "recursion_method": "processlist",
    }
    fields.update(overrides)
    return AltersCreate(**fields)


def test_build_alters_spec_builds_parent_execute_envelope(
    created_service: CreatedService,
):
    """Test build_alters_spec assembles the run-command pt-osc execute envelope."""
    task = build_alters_spec(created_service, "app", "users", _build_body())

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


def test_build_alters_spec_remote_service_embeds_host_and_port(
    created_service: CreatedService,
):
    """Test a remote service prefixes the target DSN with its host and port."""
    remote = _service_at(created_service, "10.0.0.5").model_copy(
        update={"port": REMOTE_SERVICE_PORT}
    )

    task = build_alters_spec(remote, "app", "users", _build_body())

    assert "h=10.0.0.5,P=3306,D=app,t=users" in task.data["meta"]["args"]


def test_build_alters_spec_localhost_service_omits_host(
    created_service: CreatedService,
):
    """Test a localhost service omits the ``h=`` host from the target DSN."""
    local = _service_at(created_service, "localhost").model_copy(
        update={"port": REMOTE_SERVICE_PORT}
    )

    args = build_alters_spec(local, "app", "users", _build_body()).data["meta"]["args"]

    assert "P=3306,D=app,t=users" in args
    assert "h=localhost" not in args


def test_build_alters_spec_dsn_recursion_embeds_dsn_table(
    created_service: CreatedService,
):
    """Test a dsn recursion method embeds the resolved dsn_table in the args."""
    body = _build_body(recursion_method="dsn", dsn_table="D=custom,t=dsns")

    task = build_alters_spec(created_service, "app", "users", body)

    assert "--recursion-method=dsn=" in task.data["meta"]["args"]
    assert "D=custom,t=dsns" in task.data["meta"]["args"]


def test_build_alters_spec_dsn_table_prefix_passes_through(
    created_service: CreatedService,
):
    """Test a dsn_table already carrying an ``h=`` prefix is left unmodified."""
    body = _build_body(recursion_method="dsn", dsn_table="h=custom-host,D=d,t=t")

    args = build_alters_spec(created_service, "app", "users", body).data["meta"]["args"]

    assert "--recursion-method=dsn=h=custom-host,D=d,t=t" in args
