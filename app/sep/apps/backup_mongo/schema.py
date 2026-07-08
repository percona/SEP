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

"""Derive the AppSchema for the backup_mongo plugin model-first.

The schema is derived from the model-first
:class:`~app.sep.apps.backup_mongo.models.BackupForm` plus the
:data:`~app.sep.apps.backup_mongo.views.backup_mongo_views` presentation
bundle. :data:`BACKUP_MONGO_DERIVED` carries the three ``DerivedTask`` specs (with
their two-step ``payload_substitutions``) into the ``derived`` block of
``GET /schema``; the cascade create route reuses the same specs to POST the
logical, physical, and status siblings.
"""

from app.sep.apps.backup_mongo.models import BackupForm, BackupType
from app.sep.apps.backup_mongo.views import backup_mongo_views
from app.sep.apps.framework.form_dsl import derive_app_schema
from app.sep.apps.framework.schema import DerivedTask, RelatedApp

BACKUP_MONGO_DERIVED = [
    DerivedTask(
        name_suffix="-logical",
        payload_substitutions={
            BackupType.PBM_CONFIG.value: BackupType.PBM_LOGICAL.value,
        },
        data_overrides={"backup_type": BackupType.PBM_LOGICAL.value},
    ),
    DerivedTask(
        name_suffix="-physical",
        payload_substitutions={
            BackupType.PBM_CONFIG.value: BackupType.PBM_LOGICAL.value,
            BackupType.PBM_LOGICAL.value: BackupType.PBM_PHYSICAL.value,
        },
        data_overrides={"backup_type": BackupType.PBM_PHYSICAL.value},
    ),
    DerivedTask(
        name_suffix="-status",
        payload_substitutions={
            BackupType.PBM_CONFIG.value: BackupType.PBM_LOGICAL.value,
            BackupType.PBM_LOGICAL.value: BackupType.PBM_STATUS.value,
        },
        data_overrides={"backup_type": BackupType.PBM_STATUS.value},
    ),
]

backup_mongo_schema = derive_app_schema(
    BackupForm,
    backup_mongo_views.layout,
    name="backup_mongo",
    display_name="MongoDB Backups",
    description=(
        "Configure Percona Backup for MongoDB (PBM) and manage logical, "
        "physical, and status backup tasks."
    ),
    capabilities=backup_mongo_views.capabilities,
    list_view=backup_mongo_views.list_view,
    detail_view=backup_mongo_views.detail_view,
    derived=BACKUP_MONGO_DERIVED,
    related_apps=[
        RelatedApp(
            app_key="backup_mongo/restore",
            label="Restore",
            route_segment="restores",
        ),
    ],
)
