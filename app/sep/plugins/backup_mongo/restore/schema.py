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

"""Define the PluginSchema for the backup_mongo restores plugin."""

from app.inventory.models import ServiceTypeEnum
from app.sep.plugins.backup_mongo.models import BackupType
from app.sep.plugins.framework.schema import (
    Capabilities,
    Choice,
    ChoiceField,
    Column,
    ColumnFormat,
    FloatField,
    FormSection,
    HostField,
    IntegerField,
    ListView,
    PluginSchema,
    ServiceField,
    StringField,
    TextAreaField,
)

_RESTORE_TYPE_CHOICES = [
    Choice(label="Logical", value=BackupType.PBM_LOGICAL.value),
    Choice(label="Physical", value=BackupType.PBM_PHYSICAL.value),
]

restore_mongo_schema = PluginSchema(
    name="backup_mongo_restores",
    display_name="MongoDB Restores",
    description=(
        "Configure and run Percona Backup for MongoDB (PBM) logical or "
        "physical restore operations."
    ),
    forms=[
        FormSection(
            title="Task",
            fields=[
                StringField(
                    name="task_name",
                    label="Task Name",
                    required=True,
                ),
                HostField(
                    name="hostname",
                    label="Executor Host",
                    required=True,
                ),
                ServiceField(
                    name="service_id",
                    label="Database Service",
                    required=False,
                    service_types=[ServiceTypeEnum.MONGODB],
                ),
                ChoiceField(
                    name="backup_type",
                    label="Backup Type",
                    required=True,
                    choices=_RESTORE_TYPE_CHOICES,
                ),
                StringField(
                    name="backup_source",
                    label="Backup Source",
                    description="Backup name or timestamp (e.g. 2025-12-15T19:04:05Z)",
                    required=True,
                ),
                StringField(
                    name="credentials_path",
                    label="Credentials Path",
                    description=(
                        "Optional path to MongoDB URI credentials on the Nomad node"
                    ),
                ),
            ],
        ),
        FormSection(
            title="Restore Options",
            fields=[
                IntegerField(
                    name="restore_batch_size",
                    label="Batch Size",
                ),
                IntegerField(
                    name="restore_num_insertion_workers",
                    label="Insertion Workers",
                ),
                IntegerField(
                    name="restore_num_parallel_collections",
                    label="Parallel Collections",
                ),
                IntegerField(
                    name="restore_num_download_workers",
                    label="Download Workers",
                ),
                IntegerField(
                    name="restore_max_download_buffer_mb",
                    label="Max Download Buffer (MB)",
                ),
                FloatField(
                    name="restore_download_chunk_mb",
                    label="Download Chunk Size (MB)",
                ),
                StringField(
                    name="restore_mongod_location",
                    label="Mongod Location",
                ),
                TextAreaField(
                    name="restore_mongod_location_map",
                    label="Mongod Location Map (YAML)",
                ),
            ],
        ),
    ],
    capabilities=Capabilities(chaining=True, scheduling=True),
    list_view=ListView(
        columns=[
            Column(key="name", label="Name", sortable=True),
            Column(key="status", label="Status", format=ColumnFormat.STATUS),
            Column(key="hostname", label="Executor Host"),
            Column(key="backup_type", label="Type", format=ColumnFormat.CHIP),
            Column(key="backup_source", label="Backup Source"),
            Column(key="created_at", label="Created", format=ColumnFormat.RELATIVE),
            Column(key="created_by", label="Created By"),
        ],
        default_sort="name",
    ),
)
