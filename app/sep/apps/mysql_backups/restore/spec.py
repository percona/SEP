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

"""Build the restore task envelope from a validated form and resolved entities.

:func:`build_restore_spec` is the pure ``(form, resolved) -> TaskWrite`` builder
shared by the JSON create route and the legacy Jinja form path, so a restore
task's payload is byte-identical regardless of the call origin. The impure,
404-tolerant inventory resolution that feeds it lives in
:func:`~app.sep.apps.mysql_backups.restore.deps.resolve_restore_entities`.
"""

from dataclasses import dataclass

import yaml
from fastapi.encoders import jsonable_encoder

from app.core.utils.path import payload_uri
from app.core.utils.pydantic import extract_model_from_instance
from app.sep.apps.framework.spec import build_run_python_task
from app.sep.apps.mysql_backups.models import BackupType
from app.sep.apps.mysql_backups.restore.models import (
    BaseRestoreConfigServer,
    OWNER,
    RestoreConfig,
    RestoreConfigAll,
    RestoreConfigServer,
    RestoreCreate,
)
from app.tasks.models import TaskWrite

_BACKUP_TYPE_TO_PAYLOAD = {
    BackupType.MYDUMPER: "mydumper_payload",
    BackupType.XTRABACKUP: "xtrabackup_payload",
    BackupType.BINLOG: "binlog_payload",
}
_BASE_REQUIREMENTS = "packaging\nPyYAML\nPyMySQL[rsa,ed25519]\nboto3"


@dataclass(frozen=True, slots=True)
class RestoreResolved:
    """Carry the inventory facts resolved for a restore, all optional.

    Only MyDumper restores resolve a destination and database; every backup type
    may resolve a service name when ``service_id`` is set. Each field is ``None``
    when its lookup did not run or was tolerated away on a 404.

    :param service_name: The resolved service name, stamped into ``meta`` as
        ``_service_name`` when present.
    :param dest_host: The destination host split from the service address.
    :param dest_port: The destination port split from the service address.
    :param database: The resolved schema name written as the restore ``database``.
    """

    service_name: str | None = None
    dest_host: str | None = None
    dest_port: int | None = None
    database: str | None = None


def build_restore_spec(form: RestoreCreate, resolved: RestoreResolved) -> TaskWrite:
    """Build the ``run-python`` restore task envelope from the validated form.

    Slice the global and server config out of ``form`` via the YAML-serialization
    config models, apply the resolved destination host/port and database, select
    the ``file://`` payload directory and pip requirements by ``backup_type``, and
    stamp ``_service_name`` when a service resolved.

    :param form: The validated create form.
    :param resolved: The inventory facts resolved for this restore.
    :return: The restore ``TaskWrite`` consumed by the Tasks API.
    :raises ValueError: When ``form.backup_type`` is outside the known backup types.
    """
    all_config = extract_model_from_instance(form, RestoreConfigAll)
    base_config = extract_model_from_instance(form, BaseRestoreConfigServer)

    server_config = {**base_config.model_dump(), "alias": form.task_name}
    if resolved.dest_host is not None:
        server_config["dest_host"] = resolved.dest_host
        server_config["dest_port"] = resolved.dest_port
    if resolved.database is not None:
        server_config["database"] = resolved.database

    restore_config = RestoreConfig(
        all_servers=all_config,
        server_list=[RestoreConfigServer.model_validate(server_config)],
    )

    payload_name = _BACKUP_TYPE_TO_PAYLOAD.get(form.backup_type)
    if not payload_name:
        raise ValueError(f"Invalid Backup Type {form.backup_type}")

    requirements = _BASE_REQUIREMENTS
    if form.backup_type == BackupType.XTRABACKUP:
        requirements += "\nfilelock"

    return build_run_python_task(
        name=form.task_name,
        owner=OWNER,
        target=form.hostname,
        config=yaml.dump(
            jsonable_encoder(restore_config, by_alias=True, exclude_none=True)
        ),
        requirements=requirements,
        payload=payload_uri(__file__, payload_name),
        service_name=resolved.service_name,
    )
