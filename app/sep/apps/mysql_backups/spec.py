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
    UploadProvider,
)
from app.sep.apps.mysql_backups.models import BackupType
from app.sep.apps.mysql_backups.payload_variants import variant_name

_BASE_REQUIREMENTS = "packaging\nPyYAML\nPyMySQL[rsa,ed25519]"


def _xtrabackup_payload_name(upload: list[UploadProvider]) -> str:
    """Return the xtrabackup payload variant carrying exactly the selected providers.

    The canonical payload ships all three upload-provider classes and sits within a
    few bytes of the 16 KiB Nomad dispatch limit, so every other selection gets a
    generated variant with the unreachable providers omitted. Keyed on the set of
    providers, so the form's ordering does not change the dispatched payload.

    :param upload: The upload providers the form selected (possibly empty).
    :return: The payload filename beside this module.
    """
    selected = set(upload)
    return variant_name(tuple(p.value for p in UploadProvider if p in selected))


def build_backup_spec(form: BackupCreate, resolved: ResolvedEntities) -> RunPythonSpec:
    """Build the ``run-python`` backup spec from the validated form.

    Select the per-``backup_type`` server-config host (XtraBackup → ``localhost``;
    Binlog → the alternative host or the service address; Mydumper → the service
    address), serialise the ``BackupConfig`` to the YAML ``config``, and select the
    ``file://`` payload and pip requirements by ``backup_type``. XtraBackup is keyed
    on ``form.upload`` as well: the dispatched payload is the variant carrying
    exactly the selected providers, and ``boto3`` is requested only when that
    variant can reach S3. The framework's ``assemble_envelope`` fills ``target``
    (the executor ``HostRef``), ``_service_name``, and the connectivity keys around
    this spec.

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

    # Keyed off the recipient (not the encrypt flags) so it survives whichever
    # mode is on — post-run with in-place off still needs it. Safe only because
    # BackupCreate's gates guarantee recipient <=> some encryption mode.
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
        requirements += "\nboto3\nfilelock"
    elif form.backup_type == BackupType.XTRABACKUP:
        payload_name = _xtrabackup_payload_name(form.upload)
        # Only the variants carrying the S3 provider import boto3; asking for it
        # anyway would make the task install a dependency it never loads.
        if UploadProvider.S3 in form.upload:
            requirements += "\nboto3"
        requirements += "\nfilelock"
    elif form.backup_type == BackupType.BINLOG:
        payload_name = "binlog_payload"
        requirements += "\nboto3"
    else:
        raise ValueError(f"Invalid Backup Type {form.backup_type}")
    return RunPythonSpec(
        config=yaml.dump(
            jsonable_encoder(backup_config, by_alias=True, exclude_none=True)
        ),
        requirements=requirements,
        payload=payload_uri(__file__, payload_name),
    )
