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

"""Define tests for the app.sep.apps.alters.deps module."""

import shlex
from unittest.mock import AsyncMock, call

import pytest
from fastapi import HTTPException, status

from app.core.requests.remote_api import RemoteAPI
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.alters.deps import (
    alters_executor_matches_service_host,
    alters_satellite_task_names,
    build_alters_api_task_response,
    build_alters_task,
    build_pre_checks_task_payload,
    cascade_create_alters_group,
    cascade_update_alters_group,
    extract_service_info,
    get_alters_task,
    parse_alters_task_args,
    resolve_predecessor_specs,
)
from app.sep.apps.alters.models import AltersCreate
from app.sep.apps.alters.schema import alters_schema
from app.sep.apps.framework.schema import ChainedPredecessor
from app.tasks.anonymizer.entities import PIIEntity
from app.tasks.models import (
    Task,
    TaskBackendEnum,
    TaskWrite,
)
from tests.app.factories import GeneratedTaskFactory, TaskFactory
from tests.app.sep.apps.alters.factories import AltersCreateFactory


@pytest.fixture
def created_alters(created_service, created_schema, created_table) -> AltersCreate:
    """Return a fake created AltersCreate instance."""
    created_alters = AltersCreateFactory.build()
    created_alters.service_id = created_service.id
    created_alters.db_schema = created_schema.id
    created_alters.db_table = created_table.id
    created_alters.alter = "ADD COLUMN new_column INT"
    created_alters.recursion_method = "dsn"
    return created_alters


@pytest.fixture
def created_task() -> Task:
    """Return a fake created task."""
    created_task = TaskFactory.build(owner="ALTERS")
    mock_data = {
        "task": "run-command",
        "meta": {
            "command": "pt-online-schema-change",
            "args": "--alter=ADD COLUMN new_column INT --execute",
            "target": "localhost",
            "_schema_name": "public",
            "_table_name": "example_table",
        },
    }

    created_task.data = mock_data
    return created_task


@pytest.mark.asyncio
async def test_build_alters_task(
    created_alters, created_service, created_schema, created_table, mock_remote_api
):
    """Test for building the alter task payload from form."""
    mock_remote_api.get = AsyncMock(
        side_effect=[
            created_service.model_dump(),
            created_schema.model_dump(),
            created_table.model_dump(),
        ]
    )
    generated_task = await build_alters_task(created_alters, mock_remote_api)
    assert isinstance(generated_task, TaskWrite)
    assert generated_task.owner == "ALTERS"

    command = generated_task.data["meta"]["command"]
    assert command == "pt-online-schema-change"


@pytest.mark.asyncio
async def test_get_alters_task(created_task, mock_remote_api):
    """Test for fetching and validating a task for the Alters plugin."""
    mock_remote_api.get = AsyncMock(side_effect=[created_task.model_dump()])
    alters_task = await get_alters_task(created_task.name, mock_remote_api)
    assert isinstance(alters_task, Task)
    assert alters_task.name == created_task.name


def test_extract_service_info_from_meta():
    """Test extracting service info from meta fields."""
    meta = {
        "_service_host": "db.example.com",
        "_service_port": 3307,
        "_schema_name": "test_schema",
        "_table_name": "test_table",
    }

    result = extract_service_info(meta)

    assert result == {
        "service_host": "db.example.com",
        "service_port": 3307,
        "schema_name": "test_schema",
        "table_name": "test_table",
    }


def test_extract_service_info_from_args():
    """Test extracting service info from args when meta fields are missing."""
    meta = {
        "args": "'--alter=ADD COLUMN x INT' h=db.example.com,P=3307 --execute",
    }

    result = extract_service_info(meta)

    assert result == {
        "service_host": "db.example.com",
        "service_port": 3307,
        "schema_name": "",
        "table_name": "",
    }


def test_parse_alters_task_args():
    """Test parsing alters task arguments back into form field values."""
    meta = {
        "args": "'--alter=ADD INDEX c_1(chunk)' P=3306,D=percona,t=careers --recursion-method=processlist --pause-file=/tmp/pause_file.txt --tries=create_triggers:10000:1,drop_triggers:10000:1,copy_rows:10000:1 '--set-vars=transaction_isolation='\"'\"'READ-COMMITTED'\"'\"',lock_wait_timeout=5' --critical-load=Threads_running=99999,Connections=200 --max-load=Threads_running=30,Threads_connected=120 --chunk-time=0.5 --max-lag=150 --print --progress=time,10 --execute",
    }

    result = parse_alters_task_args(meta)

    assert result == {
        "alter": "ADD INDEX c_1(chunk)",
        "recursion_method": "processlist",
        "dsn_table": "",
        "pause_file": "/tmp/pause_file.txt",
        "new_table_name": "",
        "print_arg": True,
        "progress": "time,10",
        "no_swap_tables": False,
        "no_drop_old_table": False,
        "no_drop_new_table": False,
        "no_drop_triggers": False,
        "tries": "create_triggers:10000:1,drop_triggers:10000:1,copy_rows:10000:1",
        "set_vars": "transaction_isolation='READ-COMMITTED',lock_wait_timeout=5",
        "critical_load": "Threads_running=99999,Connections=200",
        "max_load": "Threads_running=30,Threads_connected=120",
        "chunk_time": "0.5",
        "max_lag": "150",
        "max_flow_ctl": "",
        "extra_args": "",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("nomad_hosts", "expect_skip_in_config"),
    [
        ({"db1": "10.0.0.5"}, False),
        ({"db1": "10.0.0.99"}, True),
    ],
)
async def test_build_pre_checks_task_filesystem_skip_flag(
    mock_remote_api, nomad_hosts, expect_skip_in_config
):
    """Pre-checks YAML skip_filesystem_checks follows executor vs DB host (Nomad /hosts/)."""
    task = GeneratedTaskFactory.build(
        name="prechk-alter",
        data={
            "task": "run-command",
            "meta": {
                "command": "pt-online-schema-change",
                "args": "--alter=x --execute",
                "_command_line": "pt-online-schema-change --alter=x --execute",
                "target": "db1",
                "_schema_name": "db",
                "_table_name": "t",
                "_service_host": "10.0.0.5",
                "_service_port": 3306,
            },
        },
        backend=TaskBackendEnum.PROXY,
    )
    mock_remote_api.get = AsyncMock(return_value=nomad_hosts)
    pre = await build_pre_checks_task_payload(task, task_api=mock_remote_api)
    mock_remote_api.get.assert_awaited_once_with("/hosts/")
    assert pre.name == "prechk-alter"
    assert "parent" not in pre.data
    assert pre.data["task"] == "run-python"
    assert "command" not in pre.data["meta"]
    assert "args" not in pre.data["meta"]
    assert "_command_line" not in pre.data["meta"]
    assert task.data["meta"]["command"] == "pt-online-schema-change"
    cfg = pre.data["meta"]["config"]
    if expect_skip_in_config:
        assert "skip_filesystem_checks: true" in cfg
    else:
        assert "skip_filesystem_checks" not in cfg
    assert "schema: db" in cfg
    assert "table: t" in cfg
    assert "host: 10.0.0.5" in cfg
    assert "port: 3306" in cfg


@pytest.mark.asyncio
async def test_build_pre_checks_task_mysql_config_file_in_yaml(mock_remote_api):
    """Generated config quotes mysql_config_file for YAML safety."""
    task = GeneratedTaskFactory.build(
        name="cnf-alter",
        data={
            "task": "run-command",
            "meta": {
                "command": "pt-online-schema-change",
                "args": "--execute",
                "target": "db1",
                "_schema_name": "s",
                "_table_name": "tbl",
                "_service_host": "10.0.0.5",
                "_service_port": 3306,
                "_pre_checks_mysql_config_file": "/path/with space/my.cnf",
            },
        },
        backend=TaskBackendEnum.PROXY,
    )
    mock_remote_api.get = AsyncMock(return_value={"db1": "10.0.0.5"})
    pre = await build_pre_checks_task_payload(task, task_api=mock_remote_api)
    assert 'mysql_config_file: "/path/with space/my.cnf"' in pre.data["meta"]["config"]


def test_alters_executor_matches_service_host():
    """Nomad node → address vs inventory host; used for pre-checks filesystem skip."""
    meta = {
        "target": "db-node",
        "_service_host": "10.30.50.130",
        "_service_port": 3306,
    }
    assert (
        alters_executor_matches_service_host(meta, {"db-node": "10.30.50.130"}) is True
    )
    assert (
        alters_executor_matches_service_host(meta, {"db-node": "10.30.50.131"}) is False
    )
    assert (
        alters_executor_matches_service_host(meta, {"db-node": "10.30.50.130:4648"})
        is False
    )
    meta_ip = {
        "target": "10.30.50.130",
        "_service_host": "10.30.50.130",
        "_service_port": 3306,
    }
    assert alters_executor_matches_service_host(meta_ip, {}) is True
    assert alters_executor_matches_service_host(meta_ip, None) is True


@pytest.mark.asyncio
async def test_build_alters_task_free_typed_schema_and_table(
    created_alters, created_service, mock_remote_api
):
    """Build payload from free-typed schema/table names (no inventory fetch)."""
    created_alters.db_schema = "manual_schema"
    created_alters.db_table = "manual_table"
    mock_remote_api.get = AsyncMock(return_value=created_service.model_dump())
    task = await build_alters_task(created_alters, mock_remote_api)
    assert task.data["meta"]["_schema_name"] == "manual_schema"
    assert task.data["meta"]["_table_name"] == "manual_table"
    assert "D=manual_schema,t=manual_table" in task.data["meta"]["args"]


@pytest.mark.asyncio
async def test_build_alters_task_id_and_free_typed_emit_identical_meta(
    created_alters, created_service, created_schema, created_table, mock_remote_api
):
    """Guard AC4: an inventory id and the free-typed name it resolves to are byte-stable.

    Building from ``db_schema``/``db_table`` inventory ids (resolved to the entity
    names) must emit the same parent ``meta`` as building from those same names typed
    free-hand — the pt-osc invocation cannot depend on how the target was selected.
    """
    created_schema.name = "app"
    created_table.name = "users"

    mock_remote_api.get = AsyncMock(
        side_effect=[
            created_service.model_dump(),
            created_schema.model_dump(),
            created_table.model_dump(),
        ]
    )
    id_task = await build_alters_task(created_alters, mock_remote_api)

    free_typed = created_alters.model_copy(
        update={"db_schema": created_schema.name, "db_table": created_table.name}
    )
    mock_remote_api.get = AsyncMock(return_value=created_service.model_dump())
    free_typed_task = await build_alters_task(free_typed, mock_remote_api)

    assert id_task.data["meta"] == free_typed_task.data["meta"]


@pytest.mark.asyncio
async def test_build_alters_task_strips_free_typed_target_whitespace(
    created_alters, created_service, mock_remote_api
):
    """A free-typed name with surrounding whitespace is trimmed before the DSN."""
    body = AltersCreate.model_validate(
        {**created_alters.model_dump(), "db_schema": " app ", "db_table": " users "}
    )
    mock_remote_api.get = AsyncMock(return_value=created_service.model_dump())
    task = await build_alters_task(body, mock_remote_api)
    assert task.data["meta"]["_schema_name"] == "app"
    assert task.data["meta"]["_table_name"] == "users"
    assert "D=app,t=users" in task.data["meta"]["args"]


@pytest.mark.asyncio
async def test_build_alters_task_numeric_free_typed_name_not_resolved_as_id(
    created_alters, created_service, mock_remote_api
):
    """Use a purely-numeric free-typed name verbatim, never fetch it as an id."""
    body = AltersCreate.model_validate(
        {**created_alters.model_dump(), "db_schema": "123", "db_table": "42"}
    )
    mock_remote_api.get = AsyncMock(return_value=created_service.model_dump())
    task = await build_alters_task(body, mock_remote_api)
    assert mock_remote_api.get.await_count == 1
    assert task.data["meta"]["_schema_name"] == "123"
    assert task.data["meta"]["_table_name"] == "42"
    assert "D=123,t=42" in task.data["meta"]["args"]


@pytest.mark.asyncio
async def test_build_alters_task_id_schema_with_free_typed_table(
    created_alters, created_service, created_schema, mock_remote_api
):
    """Resolve a schema inventory id while the table is a free-typed new name."""
    created_schema.name = "app"
    mock_remote_api.get = AsyncMock(
        side_effect=[created_service.model_dump(), created_schema.model_dump()]
    )
    body = created_alters.model_copy(
        update={"db_schema": created_schema.id, "db_table": "new_table"}
    )
    task = await build_alters_task(body, mock_remote_api)
    assert task.data["meta"]["_schema_name"] == "app"
    assert task.data["meta"]["_table_name"] == "new_table"
    assert "D=app,t=new_table" in task.data["meta"]["args"]


@pytest.mark.asyncio
async def test_build_alters_task_free_typed_schema_with_id_table(
    created_alters, created_service, created_table, mock_remote_api
):
    """Resolve a table inventory id while the schema is a free-typed new name."""
    created_table.name = "orders"
    mock_remote_api.get = AsyncMock(
        side_effect=[created_service.model_dump(), created_table.model_dump()]
    )
    body = created_alters.model_copy(
        update={"db_schema": "new_schema", "db_table": created_table.id}
    )
    task = await build_alters_task(body, mock_remote_api)
    assert task.data["meta"]["_schema_name"] == "new_schema"
    assert task.data["meta"]["_table_name"] == "orders"
    assert "D=new_schema,t=orders" in task.data["meta"]["args"]


@pytest.mark.asyncio
async def test_build_alters_task_dsn_recursion_defaults_empty_dsn_table(
    created_alters, created_service, created_schema, created_table, mock_remote_api
):
    """DSN recursion with blank dsn_table applies default D=percona,t=dsns in command."""
    created_alters.recursion_method = "dsn"
    created_alters.dsn_table = ""
    mock_remote_api.get = AsyncMock(
        side_effect=[
            created_service.model_dump(),
            created_schema.model_dump(),
            created_table.model_dump(),
        ]
    )
    task = await build_alters_task(created_alters, mock_remote_api)
    args = task.data["meta"]["args"]
    assert "D=percona,t=dsns" in args
    rec_arg = next(a for a in shlex.split(args) if a.startswith("--recursion-method="))
    assert rec_arg.startswith("--recursion-method=dsn=")
    assert "D=percona,t=dsns" in rec_arg


@pytest.mark.asyncio
async def test_build_alters_task_adds_progress_independent_of_print(
    created_alters, created_service, created_schema, created_table, mock_remote_api
):
    """Append --progress whenever progress is set, with or without --print."""
    created_alters.print_arg = False
    created_alters.progress = "time,5"
    mock_remote_api.get = AsyncMock(
        side_effect=[
            created_service.model_dump(),
            created_schema.model_dump(),
            created_table.model_dump(),
        ]
    )
    task = await build_alters_task(created_alters, mock_remote_api)
    args = task.data["meta"]["args"]
    assert "--progress=time,5" in args
    assert "--print" not in args


def test_parse_alters_task_args_missing_or_empty_args():
    """Default form values when args are missing or empty."""
    defaults = parse_alters_task_args({})
    assert defaults["recursion_method"] == "processlist"
    assert parse_alters_task_args({"args": ""}) == defaults


def test_parse_alters_task_args_recursion_dsn_strips_h_p():
    """dsn= recursion strips h=/P= from embedded DSN for the dsn_table field."""
    meta = {
        "args": (
            "--recursion-method=dsn=h=127.0.0.1,P=3306,D=dbx,t=tbl "
            "--alter=ADD COLUMN x INT --execute"
        ),
    }
    out = parse_alters_task_args(meta)
    assert out["recursion_method"] == "dsn"
    assert out["dsn_table"] == "D=dbx,t=tbl"


def test_parse_alters_task_args_recursion_dsn_only_host_port():
    """Keep the whole dsn= value as dsn_table when it has only h=/P= parts."""
    out = parse_alters_task_args({"args": "--recursion-method=dsn=h=1,P=2 --execute"})
    assert out["recursion_method"] == "dsn"
    assert out["dsn_table"] == "h=1,P=2"


EXPECTED_CASCADE_CREATE_POSTS = 3


def _cascade_parent_task(name: str = "t1") -> TaskWrite:
    """Return a minimal parent execute TaskWrite for cascade tests."""
    return TaskWrite(
        name=name,
        owner="ALTERS",
        backend=TaskBackendEnum.PROXY,
        target="host1",
        data={
            "task": "run-command",
            "meta": {
                "command": "pt-online-schema-change",
                "args": "--execute",
                "target": "host1",
            },
        },
    )


def _cascade_pre_checks_template() -> TaskWrite:
    """Return a minimal pre-checks TaskWrite template for cascade tests."""
    return TaskWrite(
        name="ignored",
        owner="ALTERS",
        backend=TaskBackendEnum.PROXY,
        target="host1",
        data={
            "task": "run-python",
            "meta": {"config": "schema: s\ntable: t"},
            "payload": "file:///tmp/pre_checks.py",
        },
    )


def test_alters_satellite_task_names():
    """Test alters_satellite_task_names includes dry-run and pre-checks suffixes."""
    assert alters_satellite_task_names("my-alter") == [
        "my-alter-dry-run",
        "my-alter-pre-checks",
    ]


def test_resolve_predecessor_specs_first_halts_by_default():
    """Test first resolved predecessor defaults to on_failure halt."""
    body = AltersCreate(
        task_name="t1",
        hostname="host1",
        service_id=1,
        db_schema="app",
        db_table="users",
        alter="ADD COLUMN x INT",
    )
    spec = resolve_predecessor_specs(body)[0]
    assert spec.on_failure == "halt"
    assert spec.name_suffix == "-pre-checks"


def test_resolve_predecessor_specs_first_continues_when_user_overrides():
    """Test continue_on_pre_check_failure maps first predecessor to continue."""
    body = AltersCreate(
        task_name="t1",
        hostname="host1",
        service_id=1,
        db_schema="app",
        db_table="users",
        alter="ADD COLUMN x INT",
        continue_on_pre_check_failure=True,
    )
    spec = resolve_predecessor_specs(body)[0]
    assert spec.on_failure == "continue"


@pytest.mark.asyncio
async def test_cascade_create_alters_group_posts_three_tasks():
    """Test cascade_create_alters_group POSTs parent, dry-run, and pre-checks only."""
    tasks_api = AsyncMock(spec=RemoteAPI)
    body = AltersCreate(
        task_name="t1",
        hostname="host1",
        service_id=1,
        db_schema="app",
        db_table="users",
        alter="ADD COLUMN x INT",
    )

    await cascade_create_alters_group(
        tasks_api,
        _cascade_parent_task(),
        _cascade_pre_checks_template(),
        body,
    )

    assert len(tasks_api.post.await_args_list) == EXPECTED_CASCADE_CREATE_POSTS
    tasks_api.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_cascade_create_alters_group_rolls_back_on_task_post_failure():
    """Test cascade_create_alters_group rolls back when a task POST fails."""
    tasks_api = AsyncMock(spec=RemoteAPI)
    exc = HTTPException(status_code=status.HTTP_502_BAD_GATEWAY)
    tasks_api.post.side_effect = [None, None, exc]
    body = AltersCreate(
        task_name="t1",
        hostname="host1",
        service_id=1,
        db_schema="app",
        db_table="users",
        alter="ADD COLUMN x INT",
    )

    with pytest.raises(HTTPException):
        await cascade_create_alters_group(
            tasks_api,
            _cascade_parent_task(),
            _cascade_pre_checks_template(),
            body,
        )

    assert tasks_api.delete.await_args_list == [
        call("/t1-dry-run"),
        call("/t1"),
    ]


@pytest.mark.asyncio
async def test_cascade_update_alters_group_halt_by_default(mocker):
    """Test cascade_update uses first resolved predecessor halt by default."""
    tasks_api = AsyncMock(spec=RemoteAPI)
    body = AltersCreate(
        task_name="t1",
        hostname="host1",
        service_id=1,
        db_schema="app",
        db_table="users",
        alter="ADD COLUMN x INT",
    )
    captured_specs: list = []
    original_build = __import__(
        "app.sep.apps.framework.cascade", fromlist=["build_predecessor_payload"]
    ).build_predecessor_payload

    def _capture_build(parent_payload, pred_payload, spec):
        captured_specs.append(spec)
        return original_build(parent_payload, pred_payload, spec)

    mocker.patch(
        "app.sep.apps.alters.deps.build_predecessor_payload",
        side_effect=_capture_build,
    )

    await cascade_update_alters_group(
        tasks_api,
        "t1",
        _cascade_parent_task(),
        _cascade_pre_checks_template(),
        body,
    )

    assert captured_specs == [resolve_predecessor_specs(body)[0]]
    assert captured_specs[0].on_failure == "halt"


@pytest.mark.asyncio
async def test_cascade_update_alters_group_continue_on_pre_check_failure(mocker):
    """Test cascade_update honors continue_on_pre_check_failure like create."""
    tasks_api = AsyncMock(spec=RemoteAPI)
    body = AltersCreate(
        task_name="t1",
        hostname="host1",
        service_id=1,
        db_schema="app",
        db_table="users",
        alter="ADD COLUMN x INT",
        continue_on_pre_check_failure=True,
    )
    captured_specs: list = []
    original_build = __import__(
        "app.sep.apps.framework.cascade", fromlist=["build_predecessor_payload"]
    ).build_predecessor_payload

    def _capture_build(parent_payload, pred_payload, spec):
        captured_specs.append(spec)
        return original_build(parent_payload, pred_payload, spec)

    mocker.patch(
        "app.sep.apps.alters.deps.build_predecessor_payload",
        side_effect=_capture_build,
    )

    await cascade_update_alters_group(
        tasks_api,
        "t1",
        _cascade_parent_task(),
        _cascade_pre_checks_template(),
        body,
    )

    assert captured_specs == [resolve_predecessor_specs(body)[0]]
    assert captured_specs[0].on_failure == "continue"


@pytest.mark.asyncio
async def test_cascade_update_pairs_predecessor_names_with_specs(mocker):
    """Each predecessor PUT uses the matching schema spec, not a shared one."""
    primary = (alters_schema.predecessors or [None])[0]
    assert primary is not None
    secondary = ChainedPredecessor(
        name_suffix="-secondary",
        on_failure="continue",
        parent_link=True,
    )
    original_predecessors = alters_schema.predecessors
    alters_schema.predecessors = [primary, secondary]
    try:
        tasks_api = AsyncMock(spec=RemoteAPI)
        body = AltersCreate(
            task_name="t1",
            hostname="host1",
            service_id=1,
            db_schema="app",
            db_table="users",
            alter="ADD COLUMN x INT",
        )
        captured_specs: list[ChainedPredecessor] = []
        original_build = __import__(
            "app.sep.apps.framework.cascade", fromlist=["build_predecessor_payload"]
        ).build_predecessor_payload

        def _capture_build(parent_payload, pred_payload, spec):
            captured_specs.append(spec)
            return original_build(parent_payload, pred_payload, spec)

        mocker.patch(
            "app.sep.apps.alters.deps.build_predecessor_payload",
            side_effect=_capture_build,
        )
        mocker.patch(
            "app.sep.apps.alters.deps.cascade_update_tasks",
            new=AsyncMock(
                return_value=__import__(
                    "app.sep.apps.framework.cascade", fromlist=["CascadeResult"]
                ).CascadeResult()
            ),
        )

        await cascade_update_alters_group(
            tasks_api,
            "t1",
            _cascade_parent_task(),
            _cascade_pre_checks_template(),
            body,
        )

        assert captured_specs == resolve_predecessor_specs(body)
        assert captured_specs[0].name_suffix == primary.name_suffix
        assert captured_specs[1] is secondary
        assert tasks_api.put.await_count == len(captured_specs)
    finally:
        alters_schema.predecessors = original_predecessors


def _make_alters_task(
    created_by: str | None = None, last_updated_by: str | None = None
) -> Task:
    return TaskFactory.build(
        name="test-alter",
        owner="ALTERS",
        backend=TaskBackendEnum.PROXY,
        is_template=False,
        protected=False,
        alert_on_fail=False,
        data={
            "task": "run-command",
            "meta": {
                "command": "pt-online-schema-change",
                "args": "--alter=ADD COLUMN x INT --execute",
                "target": "host1",
                "_schema_name": "test_schema",
                "_table_name": "test_table",
            },
        },
        created_by=created_by,
        last_updated_by=last_updated_by,
    )


class TestBuildAltersApiTaskResponse:
    """Tests for build_alters_api_task_response username mapping."""

    def test_created_by_resolved_to_display_name_when_mapping_provided(self):
        """Assert created_by is resolved when mapping contains the ID."""
        task = _make_alters_task(created_by="uid-abc", last_updated_by=None)

        result = build_alters_api_task_response(
            task, username_mapping={"uid-abc": "Alice"}
        )

        assert result.created_by == "Alice"

    def test_created_by_falls_back_to_raw_id_when_not_in_mapping(self):
        """Assert created_by is preserved when the ID is not in the mapping."""
        task = _make_alters_task(created_by="uid-unknown", last_updated_by=None)

        result = build_alters_api_task_response(
            task, username_mapping={"uid-other": "Bob"}
        )

        assert result.created_by == "uid-unknown"

    def test_last_updated_by_resolved_to_display_name(self):
        """Assert last_updated_by is also resolved via the mapping."""
        task = _make_alters_task(created_by=None, last_updated_by="uid-xyz")

        result = build_alters_api_task_response(
            task, username_mapping={"uid-xyz": "Carol"}
        )

        assert result.last_updated_by == "Carol"

    def test_username_mapping_none_preserves_raw_ids(self):
        """Assert created_by and last_updated_by are unchanged when mapping is None."""
        task = _make_alters_task(created_by="uid-123", last_updated_by="uid-456")

        result = build_alters_api_task_response(task, username_mapping=None)

        assert result.created_by == "uid-123"
        assert result.last_updated_by == "uid-456"

    def test_service_type_and_anonymization_surface_populated(self):
        """Assert the rebased response carries service_type and anonymization fields."""
        mask = PIIEntity.CREDIT_CARD | PIIEntity.EMAIL_ADDRESS
        task = _make_alters_task(created_by=None, last_updated_by=None)
        task.anonymize_mask = mask

        result = build_alters_api_task_response(task)

        assert result.service_type == ServiceTypeEnum.MYSQL
        assert result.anonymize_mask == mask
        assert result.anonymized_entities == sorted(
            entity.name for entity in PIIEntity.decode_selection(mask)
        )


_LEGACY_SCHEMA_ID = 10
_LEGACY_TABLE_ID = 20


def _legacy_form_base() -> dict[str, object]:
    """Return the minimal valid legacy Jinja form body (no target selected yet)."""
    return {
        "task_name": "alt-1",
        "hostname": "exec-host",
        "service_id": 1,
        "alter": "ADD COLUMN x INT",
        "recursion_method": "processlist",
    }
