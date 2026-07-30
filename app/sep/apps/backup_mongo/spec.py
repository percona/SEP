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

"""Build the ``run-python`` PBM backup task envelope for the MongoDB Backups app.

:func:`build_backup_mongo_spec` is the pure ``(form, resolved) -> TaskWrite`` builder
shared by the JSON create route (via the impure, 404-tolerant
:func:`~app.sep.apps.backup_mongo.deps.build_backup_task_payload`) and the legacy
Jinja form path, so a backup task's Nomad payload is byte-identical regardless of the
call origin. PBM tasks run off ``form.hostname`` and the generated config; the
inventory service is resolved only to stamp ``_service_name`` for PMM, so this builder
takes the resolved name rather than reaching the inventory API itself. The envelope is
assembled through the framework's connectivity-optional ``build_run_python_task``
builder (not ``assemble_envelope``) because a PBM backup task carries no connectivity
meta, omits ``_service_name`` when the service was deleted, and keeps ``backup_type`` at
``data`` top level — the substitution token the cascade's ``DerivedTask`` payloads
rewrite.
"""

from dataclasses import dataclass
from typing import Any

import yaml

from app.core.utils.path import payload_uri
from app.sep.apps.backup_mongo.models import (
    BackupConfig,
    BackupConfigBackup,
    BackupConfigPITR,
    BackupConfigStorage,
    BackupCreate,
    CompressionAlgorithm,
    OWNER,
    parse_backup_priority,
)
from app.sep.apps.framework.spec import build_run_python_task
from app.tasks.models import TaskWrite

_BASE_REQUIREMENTS = "packaging\nPyYAML"


@dataclass(frozen=True, slots=True)
class BackupMongoResolved:
    """Carry the inventory facts resolved for a backup, all optional.

    :param service_name: The resolved service name, stamped into ``meta`` as
        ``_service_name`` when present. ``None`` when no service was specified or
        the stale ``service_id`` resolved to a deleted service.
    """

    service_name: str | None = None


def _build_pitr_config(form: BackupCreate) -> dict[str, Any]:
    """Build PITR configuration from form data."""
    return {
        "enabled": form.pitr_enabled,
        "oplogSpanMin": form.pitr_oplog_span_min,
        "compression": form.pitr_compression or CompressionAlgorithm.GZIP.value,
    }


def _build_storage_config(form: BackupCreate) -> dict[str, Any]:
    """Build storage configuration from form data."""
    storage_config = {}
    if form.storage_type == "s3":
        storage_config = {
            "region": form.storage_s3_region,
            "bucket": form.storage_s3_bucket,
            "prefix": form.storage_s3_prefix,
            "endpointUrl": form.storage_s3_endpoint_url,
        }
    elif form.storage_type == "filesystem":
        storage_config = {"path": form.storage_filesystem_path}

    return {"type": form.storage_type, form.storage_type: storage_config}


def _build_backup_config_dict(form: BackupCreate) -> dict[str, Any]:
    """Build backup configuration dictionary from form data.

    :param form: The form data containing backup configuration fields.
    :return: A dictionary containing backup configuration settings such as priority,
        compression, compression level, timeouts, oplog span, parallel collections,
        and selective namespace flags. Returns an empty dictionary if no backup
        configuration fields are provided.
    """
    has_backup_config = any(
        (
            form.backup_priority,
            form.backup_compression,
            form.backup_compression_level is not None,
            form.backup_timeouts_starting_status is not None,
            form.backup_oplog_span_min is not None,
            form.backup_num_parallel_collections is not None,
            form.backup_namespaces,
            form.backup_with_users_and_roles,
        )
    )

    if not has_backup_config:
        return {}

    backup_config_dict = {}

    if form.backup_priority:
        # Already validated at create time (BackupPriorityYaml), so this won't raise.
        backup_config_dict["priority"] = parse_backup_priority(form.backup_priority)

    if form.backup_compression:
        backup_config_dict["compression"] = form.backup_compression

    if form.backup_compression_level is not None:
        backup_config_dict["compressionLevel"] = form.backup_compression_level

    if form.backup_timeouts_starting_status is not None:
        backup_config_dict["timeouts"] = {
            "startingStatus": form.backup_timeouts_starting_status
        }

    if form.backup_oplog_span_min is not None:
        backup_config_dict["oplogSpanMin"] = form.backup_oplog_span_min

    if form.backup_num_parallel_collections is not None:
        backup_config_dict["numParallelCollections"] = (
            form.backup_num_parallel_collections
        )

    if form.backup_namespaces:
        backup_config_dict["namespaces"] = form.backup_namespaces

    if form.backup_with_users_and_roles:
        backup_config_dict["withUsersAndRoles"] = True

    return backup_config_dict


def build_backup_mongo_spec(
    form: BackupCreate, resolved: BackupMongoResolved
) -> TaskWrite:
    """Build the ``run-python`` PBM backup task envelope from the validated form.

    Compose the PITR, storage, and backup config sub-builders into the serialized
    ``BackupConfig`` YAML, select the ``file://`` payload by ``backup_type``, and
    stamp ``_service_name`` when a service resolved. ``backup_type`` is kept at the
    ``data`` top level — the substitution token the cascade ``DerivedTask`` payloads
    rewrite into the logical/physical/status/incremental siblings.

    :param form: The validated create form (a :class:`BackupCreate`).
    :param resolved: The inventory facts resolved for this backup.
    :return: The backup ``TaskWrite`` consumed by the Tasks API.
    """
    pitr = _build_pitr_config(form)
    storage = _build_storage_config(form)
    backup_config_dict = _build_backup_config_dict(form)

    backup_config = BackupConfig(
        storage=BackupConfigStorage.model_validate(storage),
        pitr=BackupConfigPITR.model_validate(pitr),
        backup=BackupConfigBackup.model_validate(backup_config_dict)
        if backup_config_dict
        else None,
        credentials_path=form.credentials_path or None,
    )

    requirements = _BASE_REQUIREMENTS

    return build_run_python_task(
        name=form.task_name,
        owner=OWNER,
        target=form.hostname,
        config=yaml.dump(
            backup_config.model_dump(by_alias=True, exclude_none=True, mode="json"),
            default_flow_style=False,
            allow_unicode=True,
        ),
        requirements=requirements,
        payload=payload_uri(__file__, f"{form.backup_type}_payload"),
        service_name=resolved.service_name,
        extra_data={"backup_type": form.backup_type},
        alert_on_fail=form.alert_on_fail,
    )
