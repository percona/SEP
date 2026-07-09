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

"""Define tests for the app.sep.apps.alters.spec pure task builder."""

from app.inventory.constants import DEFAULT_MYSQL_PORT
from app.sep.apps.alters.models import AltersCreate
from app.sep.apps.alters.spec import build_alters_spec
from app.sep.connectivity import (
    CONNECTIVITY_META_HOST_KEY,
    CONNECTIVITY_META_PORT_KEY,
    CONNECTIVITY_META_SERVICE_TYPE_KEY,
)
from app.sep.inventory import CreatedService
from app.tasks.models import TaskBackendEnum, TaskWrite

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
        "db_schema": "app",
        "db_table": "users",
        "alter": "ADD COLUMN x INT",
        "recursion_method": "processlist",
    }
    fields.update(overrides)
    return AltersCreate(**fields)


def test_build_alters_spec_builds_parent_execute_envelope(
    created_service: CreatedService,
):
    """Assemble the run-command pt-osc execute envelope from resolved inputs."""
    task = build_alters_spec(created_service, "app", "users", _build_body())

    assert isinstance(task, TaskWrite)
    assert task.owner == "ALTERS"
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


def test_build_alters_spec_defaults_connectivity_port_when_service_port_unset(
    created_service: CreatedService,
):
    """Apply the standard MySQL port to the connectivity meta when the service port is unset."""
    portless = created_service.model_copy(update={"port": None})

    meta = build_alters_spec(portless, "app", "users", _build_body()).data["meta"]

    assert meta[CONNECTIVITY_META_PORT_KEY] == DEFAULT_MYSQL_PORT


def test_build_alters_spec_remote_service_embeds_host_and_port(
    created_service: CreatedService,
):
    """Build the target DSN with the service host and port for a remote service."""
    remote = _service_at(created_service, "10.0.0.5").model_copy(
        update={"port": REMOTE_SERVICE_PORT}
    )

    task = build_alters_spec(remote, "app", "users", _build_body())

    assert "h=10.0.0.5,P=3306,D=app,t=users" in task.data["meta"]["args"]


def test_build_alters_spec_localhost_service_omits_host(
    created_service: CreatedService,
):
    """Omit the ``h=`` host from the target DSN for a localhost service."""
    local = _service_at(created_service, "localhost").model_copy(
        update={"port": REMOTE_SERVICE_PORT}
    )

    args = build_alters_spec(local, "app", "users", _build_body()).data["meta"]["args"]

    assert "P=3306,D=app,t=users" in args
    assert "h=localhost" not in args


def test_build_alters_spec_emits_progress_without_print(
    created_service: CreatedService,
):
    """Emit --progress whenever progress is set, independent of the print flag."""
    body = _build_body(progress="time,10", print_arg=False)

    args = build_alters_spec(created_service, "app", "users", body).data["meta"]["args"]

    assert "--progress=time,10" in args
    assert "--print" not in args


def test_build_alters_spec_omits_progress_when_unset(
    created_service: CreatedService,
):
    """Omit --progress when progress is empty, even with the print flag enabled."""
    body = _build_body(progress="", print_arg=True)

    args = build_alters_spec(created_service, "app", "users", body).data["meta"]["args"]

    assert "--progress" not in args
    assert "--print" in args


def test_build_alters_spec_dsn_recursion_embeds_dsn_table(
    created_service: CreatedService,
):
    """Embed the resolved dsn_table in the args for a dsn recursion method."""
    body = _build_body(recursion_method="dsn", dsn_table="D=custom,t=dsns")

    task = build_alters_spec(created_service, "app", "users", body)

    assert "--recursion-method=dsn=" in task.data["meta"]["args"]
    assert "D=custom,t=dsns" in task.data["meta"]["args"]


def test_build_alters_spec_dsn_table_prefix_passes_through(
    created_service: CreatedService,
):
    """Keep an ``h=``-prefixed dsn_table unmodified in the args."""
    body = _build_body(recursion_method="dsn", dsn_table="h=custom-host,D=d,t=t")

    args = build_alters_spec(created_service, "app", "users", body).data["meta"]["args"]

    assert "--recursion-method=dsn=h=custom-host,D=d,t=t" in args
