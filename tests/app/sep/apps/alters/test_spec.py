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

"""Define tests for the app.sep.apps.alters.spec pure run-command spec builder."""

import shlex

from app.sep.apps.alters.models import AltersCreate
from app.sep.apps.alters.spec import build_alters_spec
from app.sep.apps.framework.spec import ResolvedEntities, RunCommandSpec
from app.sep.inventory import CreatedService

REMOTE_SERVICE_PORT = 3306


def _service_at(service: CreatedService, address: str) -> CreatedService:
    """Return a copy of ``service`` whose node address is ``address``."""
    return service.model_copy(
        update={"node": service.node.model_copy(update={"address": address})}
    )


def _build_body(**overrides: object) -> AltersCreate:
    """Build a valid manual-target AltersCreate, applying ``overrides``."""
    return AltersCreate(
        **{
            "task_name": "my-alter",
            "hostname": "exec-host",
            "service_id": 1,
            "db_schema": "app",
            "db_table": "users",
            "alter": "ADD COLUMN x INT",
            "recursion_method": "processlist",
            **overrides,
        }
    )


def _resolved(service: CreatedService) -> ResolvedEntities:
    """Return resolved entities with free-typed (unresolved) schema/table targets."""
    return ResolvedEntities(
        service=service,
        entities={"db_schema": None, "db_table": None},
        executor_host="exec-host",
    )


def test_build_alters_spec_builds_run_command_spec(created_service: CreatedService):
    """Assemble the pt-osc run-command spec with its alters-only meta from the form."""
    spec = build_alters_spec(_build_body(), _resolved(created_service))

    assert isinstance(spec, RunCommandSpec)
    assert spec.command == "pt-online-schema-change"
    assert "--recursion-method=processlist" in spec.args
    assert "--execute" in spec.args
    assert "--alter=" in spec.args
    assert spec.extra_meta["_schema_name"] == "app"
    assert spec.extra_meta["_table_name"] == "users"
    assert spec.extra_meta["_service_host"] == created_service.node.address
    assert spec.extra_meta["_service_port"] == created_service.port
    assert spec.extra_meta["_pre_checks_mysql_config_file"] == "~/.my.cnf"
    assert spec.extra_meta["_command_line"] == f"pt-online-schema-change {spec.args}"


def test_build_alters_spec_remote_service_embeds_host_and_port(
    created_service: CreatedService,
):
    """Build the target DSN with the service host and port for a remote service."""
    remote = _service_at(created_service, "10.0.0.5").model_copy(
        update={"port": REMOTE_SERVICE_PORT}
    )

    spec = build_alters_spec(_build_body(), _resolved(remote))

    assert "h=10.0.0.5,P=3306,D=app,t=users" in spec.args


def test_build_alters_spec_localhost_service_omits_host(
    created_service: CreatedService,
):
    """Omit the ``h=`` host from the target DSN for a localhost service."""
    local = _service_at(created_service, "localhost").model_copy(
        update={"port": REMOTE_SERVICE_PORT}
    )

    spec = build_alters_spec(_build_body(), _resolved(local))

    assert "P=3306,D=app,t=users" in spec.args
    assert "h=localhost" not in spec.args


def test_build_alters_spec_portless_localhost_elides_dsn_host_and_port(
    created_service: CreatedService,
):
    """Build the DSN without ``h=`` or ``P=`` for a portless localhost service."""
    portless = _service_at(created_service, "localhost").model_copy(
        update={"port": None}
    )

    spec = build_alters_spec(_build_body(), _resolved(portless))

    assert "D=app,t=users" in spec.args
    assert "h=" not in spec.args
    assert "P=" not in spec.args
    assert spec.extra_meta["_service_port"] is None


def test_build_alters_spec_emits_progress_after_flags(
    created_service: CreatedService,
):
    """Emit --progress after the flag args and before --execute in the arg order."""
    body = _build_body(progress="time,10", no_swap_tables=True)

    tokens = shlex.split(build_alters_spec(body, _resolved(created_service)).args)

    assert tokens.index("--no-swap-tables") < tokens.index("--progress=time,10")
    assert tokens.index("--progress=time,10") < tokens.index("--execute")


def test_build_alters_spec_omits_progress_when_unset(
    created_service: CreatedService,
):
    """Omit --progress when progress is empty, even with the print flag enabled."""
    body = _build_body(progress="", print_arg=True)

    args = build_alters_spec(body, _resolved(created_service)).args

    assert "--progress" not in args
    assert "--print" in args


def test_build_alters_spec_dsn_recursion_embeds_dsn_table(
    created_service: CreatedService,
):
    """Embed the resolved dsn_table in the args for a dsn recursion method."""
    body = _build_body(recursion_method="dsn", dsn_table="D=custom,t=dsns")

    args = build_alters_spec(body, _resolved(created_service)).args

    assert "--recursion-method=dsn=" in args
    assert "D=custom,t=dsns" in args


def test_build_alters_spec_custom_defaults_file_emitted(
    created_service: CreatedService,
):
    """Emit --defaults-file and stamp the meta for a non-default MySQL config path."""
    body = _build_body(pre_checks_mysql_config_file="/etc/my.cnf")

    spec = build_alters_spec(body, _resolved(created_service))

    assert "--defaults-file=/etc/my.cnf" in spec.args
    assert spec.extra_meta["_pre_checks_mysql_config_file"] == "/etc/my.cnf"


def test_build_alters_spec_default_defaults_file_suppressed(
    created_service: CreatedService,
):
    """Suppress --defaults-file for the default ~/.my.cnf sentinel path."""
    spec = build_alters_spec(_build_body(), _resolved(created_service))

    assert "--defaults-file" not in spec.args
    assert spec.extra_meta["_pre_checks_mysql_config_file"] == "~/.my.cnf"


def test_build_alters_spec_quotes_value_with_spaces(
    created_service: CreatedService,
):
    """Keep a whitespace-bearing value arg a single shell token through the round-trip."""
    body = _build_body(set_vars="sql_mode='ONLY FULL'")

    tokens = shlex.split(build_alters_spec(body, _resolved(created_service)).args)

    assert "--set-vars=sql_mode='ONLY FULL'" in tokens


def test_build_alters_spec_uses_resolved_entity_names(
    created_service: CreatedService, created_schema, created_table
):
    """Derive schema/table names from the resolved inventory entities when present."""
    created_schema.name = "shop"
    created_table.name = "orders"
    resolved = ResolvedEntities(
        service=created_service,
        entities={"db_schema": created_schema, "db_table": created_table},
        executor_host="exec-host",
    )
    body = _build_body(db_schema=created_schema.id, db_table=created_table.id)

    spec = build_alters_spec(body, resolved)

    assert spec.extra_meta["_schema_name"] == "shop"
    assert spec.extra_meta["_table_name"] == "orders"
    assert "D=shop,t=orders" in spec.args
