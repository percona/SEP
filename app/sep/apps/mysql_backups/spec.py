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

"""Build the ``run-python`` backup spec for the MySQL Backups app.

:func:`build_backup_spec` is the pure ``(form, resolved) -> RunPythonSpec`` builder
fed to the framework's three-phase create path (and reused by the legacy Jinja
form path via ``deps.build_backup_task_payload``), so a backup task's Nomad
payload is byte-identical regardless of the call origin. The framework's
``assemble_envelope`` supplies the executor ``target``, ``_service_name``, and the
connectivity meta keys around this spec.
"""

import yaml
from fastapi.encoders import jsonable_encoder

from app.core.utils.path import payload_uri
from app.sep.apps.framework.spec import ResolvedEntities, RunPythonSpec
from app.sep.apps.mysql_backups.forms import (
    BackupConfig,
    BackupConfigAll,
    BackupConfigServer,
    BackupCreate,
)
from app.sep.apps.mysql_backups.models import BackupType

_BASE_REQUIREMENTS = "packaging\nPyYAML\nPyMySQL[rsa,ed25519]\nboto3"


def build_backup_spec(form: BackupCreate, resolved: ResolvedEntities) -> RunPythonSpec:
    """Build the ``run-python`` backup spec from the validated form.

    Select the per-``backup_type`` server-config host (XtraBackup → ``localhost``;
    Binlog → the alternative host or the service address; Mydumper → the service
    address), serialise the ``BackupConfig`` to the YAML ``config``, and select the
    ``file://`` payload and pip requirements by ``backup_type``. The framework's
    ``assemble_envelope`` fills ``target`` (the executor ``HostRef``),
    ``_service_name``, and the connectivity keys around this spec.

    :param form: The validated create form (a ``BackupCreate``).
    :param resolved: The entities resolved from the form's reference fields; its
        ``service`` is the ``ServiceRef`` selection (always present — the field is
        required).
    :return: The run-python spec consumed by ``assemble_envelope``.
    :raises ValueError: When ``form.backup_type`` is outside the known backup types.
    """
    service = resolved.service

    all_config = form.model_dump(
        exclude={
            "task_name",
            "hostname",
            "service_id",
            "backup_type",
            "encryption_recipient",
            "alias",
        },
    )

    server_config = {
        "alias": form.alias or service.node.address,
        "backup_type": form.backup_type,
        # XtraBackup must run on the database host itself
        "host": (
            "localhost"
            if form.backup_type == BackupType.XTRABACKUP
            else form.binlog_alternative_host
            if form.backup_type == BackupType.BINLOG and form.binlog_alternative_host
            else service.node.address
        ),
        "port": service.port,
        "upload": list(form.upload),
    }

    if form.encryption_recipient:
        server_config["dir_encrypt_config"] = {
            "encryption_recipient": form.encryption_recipient
        }

    backup_config = BackupConfig(
        all_servers=BackupConfigAll.model_validate(all_config),
        server_list=[BackupConfigServer.model_validate(server_config)],
    )

    requirements = _BASE_REQUIREMENTS
    if form.backup_type == BackupType.MYDUMPER:
        payload_name = "mydumper_payload"
        requirements += "\nfilelock"
    elif form.backup_type == BackupType.XTRABACKUP:
        payload_name = "xtrabackup_payload"
        requirements += "\nfilelock"
    elif form.backup_type == BackupType.BINLOG:
        payload_name = "binlog_payload"
    else:
        raise ValueError(f"Invalid Backup Type {form.backup_type}")
    return RunPythonSpec(
        config=yaml.dump(
            jsonable_encoder(backup_config, by_alias=True, exclude_none=True)
        ),
        requirements=requirements,
        payload=payload_uri(__file__, payload_name),
    )
