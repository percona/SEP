"""Migrate legacy GeneratedTasks

Revision ID: d39d37d3dcdc
Revises: 8f61364b2c2c
Create Date: 2025-08-22 21:53:11.356954

"""
import logging
import re
import shlex
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "d39d37d3dcdc"
down_revision: Union[str, None] = "8f61364b2c2c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

dsn_pattern = re.compile(
    r"^(?:h=(?P<host>.+?),)?(?:P=(?P<port>.+?),)?(?:D=(?P<schema>.+),)?(?:t=(?P<table>.+))?$"
)


def _task_table() -> sa.Table:
    return sa.Table(
        "task",
        sa.MetaData(),
        sa.Column("id", sa.Integer()),
        sa.Column("data", sa.JSON()),
        sa.Column(
            "backend",
            sa.Enum("NOMAD", "PROXY", name="taskbackendenum", native_enum=False),
        ),
        sa.Column("owner", sqlmodel.sql.sqltypes.AutoString()),
    )


def _get_target(data: dict) -> str:
    for constraint in data["Constraints"]:
        if constraint["LTarget"] == "${node.unique.name}":
            return constraint["RTarget"]
    raise ValueError


def _get_cmd_and_args(data: dict) -> tuple[str, list[str]]:
    task_config = data["TaskGroups"][0]["Tasks"][0]["Config"]
    return task_config["command"], task_config["args"]


def _find_meta(data: dict) -> dict:
    try:
        return data["TaskGroups"][0]["Tasks"][0].get("Meta", {}) or {}
    except:
        return {}


def _parse_dsn(dsn: str) -> dict[str, str]:
    match = dsn_pattern.match(dsn)
    if match:
        return match.groupdict()
    return {}


def _upgrade_alters_data(data: dict) -> dict:
    cmd, args = _get_cmd_and_args(data)
    target = _get_target(data)
    meta = _find_meta(data)
    host = port = None
    schema = meta.get("schema_name")
    table = meta.get("table_name")
    for arg in args:
        if not arg.startswith("--"):
            parsed_dsn = _parse_dsn(arg)
            host = parsed_dsn.get("host") or "localhost"
            port = parsed_dsn.get("port")
            schema = parsed_dsn.get("schema") or schema
            table = parsed_dsn.get("table") or table
            break
    upgraded_data = {
        "task": "run-command",
        "meta": {
            "command": cmd,
            "args": shlex.join(args),
            "target": target,
            "_schema_name": schema,
            "_table_name": table,
            "_service_host": host,
            "_service_port": int(port) if port and port.isdigit() else port,
        },
    }
    if parent := meta.get("parent"):
        upgraded_data["parent"] = parent
    return upgraded_data


def _upgrade_checksums_data(data: dict) -> dict:
    cmd, args = _get_cmd_and_args(data)
    target = _get_target(data)
    meta = _find_meta(data)
    host = port = None
    service_name = meta.get("service_name")
    for arg in args:
        if arg and not arg.startswith("--"):
            parsed_dsn = _parse_dsn(arg)
            host = parsed_dsn.get("host") or "localhost"
            port = parsed_dsn.get("port")
            break
    return {
        "task": "run-command",
        "meta": {
            "command": cmd,
            "args": shlex.join(args),
            "target": target,
            "_service_name": service_name,
            "_service_host": host,
            "_service_port": int(port) if port and port.isdigit() else port,
        },
    }


def upgrade() -> None:
    task_table = _task_table()
    conn = op.get_bind()
    rows = conn.execute(
        sa.select(
            task_table.c.id,
            task_table.c.data,
            task_table.c.owner,
        ).where(
            task_table.c.owner.in_(["ALTERS", "CHECKSUMS"]),
            task_table.c.backend == "NOMAD",
        )
    ).fetchall()
    for id_, data, owner in rows:
        if data and isinstance(data, dict):
            try:
                if owner == "ALTERS":
                    new_data = _upgrade_alters_data(data)
                elif owner == "CHECKSUMS":
                    new_data = _upgrade_checksums_data(data)
                else:
                    continue
            except:
                logging.exception("Failed to upgrade task id=%s", id_)
                continue
            conn.execute(
                task_table.update()
                .where(task_table.c.id == id_)
                .values(
                    data=new_data,
                    backend="PROXY",
                )
            )


def _nomad_job(meta: dict, nomad_meta: dict) -> dict:
    return {
        "ID": "generic-nomad-batch",
        "Name": "generic-nomad-batch",
        "Type": "batch",
        "Datacenters": ["*"],
        "Constraints": [
            {
                "LTarget": "${node.unique.name}",
                "RTarget": meta["target"],
                "Operand": "=",
            }
        ],
        "TaskGroups": [
            {
                "Name": "execution",
                "RestartPolicy": {"Attempts": 0},
                "ReschedulePolicy": {"Attempts": 0},
                "Tasks": [
                    {
                        "Name": "step1",
                        "Driver": "raw_exec",
                        "User": "",
                        "Config": {
                            "args": shlex.split(meta["args"]),
                            "command": meta["command"],
                        },
                        "Meta": nomad_meta,
                        "Restart": {"attempts": 0, "mode": "fail"},
                        "Templates": [],
                    }
                ],
            }
        ],
    }


def _downgrade_alters_data(data: dict) -> dict:
    meta = data["meta"]
    nomad_meta = {
        "schema_name": meta.get("_schema_name"),
        "table_name": meta.get("_table_name"),
    }
    if parent := data.get("parent"):
        nomad_meta["parent"] = parent
    return _nomad_job(meta, nomad_meta)


def _downgrade_checksums_data(data: dict) -> dict:
    meta = data["meta"]
    nomad_meta = {"service_name": meta.get("_service_name")}
    return _nomad_job(meta, nomad_meta)


def downgrade() -> None:
    task_table = _task_table()
    conn = op.get_bind()
    rows = conn.execute(
        sa.select(
            task_table.c.id,
            task_table.c.data,
            task_table.c.owner,
        ).where(
            task_table.c.owner.in_(["ALTERS", "CHECKSUMS"]),
            task_table.c.backend == "PROXY",
        )
    ).fetchall()
    for id_, data, owner in rows:
        if data and isinstance(data, dict) and data.get("task") == "run-command":
            try:
                if owner == "ALTERS":
                    new_data = _downgrade_alters_data(data)
                elif owner == "CHECKSUMS":
                    new_data = _downgrade_checksums_data(data)
                else:
                    continue
            except:
                logging.exception("Failed to downgrade task id=%s", id_)
                continue
            conn.execute(
                task_table.update()
                .where(task_table.c.id == id_)
                .values(
                    data=new_data,
                    backend="NOMAD",
                )
            )
