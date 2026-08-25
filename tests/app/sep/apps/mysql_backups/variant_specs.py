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

"""Build the xtrabackup backup spec for an upload selection, for tests and smoke runs.

Both the variant-selection tests and ``scripts/smoke_xtrabackup_variants.py`` need
to ask ``build_backup_spec`` what a task would dispatch for a given upload
selection. Sharing one builder keeps the smoke harness measuring the real
dispatcher rather than a hand-rolled stand-in that can drift from it: a field
``build_backup_spec`` starts reading is supplied here once, for both callers.
"""

from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework.spec import ResolvedEntities, RunPythonSpec
from app.sep.apps.mysql_backups.forms import BackupCreate
from app.sep.apps.mysql_backups.spec import build_backup_spec
from app.sep.inventory import CreatedService
from tests.app.factories import CreatedNodeFactory, CreatedServiceFactory

#: The executor host the built forms target.
HOSTNAME = "executor-host"

#: The aux field each provider's form gate requires once that provider is selected,
#: keyed by ``UploadProvider`` member name as the form's ``Contains`` gates spell it.
PROVIDER_FIELDS: dict[str, dict[str, str]] = {
    "RSYNC": {"rsync_path": "/data/rsync"},
    "S3": {"s3_bucket": "my-s3-bucket"},
    "GSUTIL": {"gs_bucket": "my-gcs-bucket"},
}


def service() -> CreatedService:
    """Return the inventory service the forms resolve against.

    :return: The built ``CreatedService``.
    """
    node = CreatedNodeFactory.build(address="db.internal", node_name="db-node")
    return CreatedServiceFactory.build(
        node=node, type=ServiceTypeEnum.MYSQL, name="svc-backups", port=3306
    )


def spec_for(upload: list[str], backup_type: str = "X") -> RunPythonSpec:
    """Build the run-python spec for an upload selection.

    :param upload: The upload providers the form selects, by enum member name.
    :param backup_type: The backup type under test.
    :return: The built ``RunPythonSpec``.
    """
    resolved_service = service()
    fields: dict[str, str] = {}
    for provider in upload:
        fields.update(PROVIDER_FIELDS[provider])
    form = BackupCreate(
        task_name="backups-variant",
        hostname=HOSTNAME,
        service_id=resolved_service.id,
        backup_type=backup_type,
        upload=upload,
        **fields,
    )
    resolved = ResolvedEntities(
        service=resolved_service,
        entities={"service_id": resolved_service},
        executor_host=HOSTNAME,
    )
    return build_backup_spec(form, resolved)
