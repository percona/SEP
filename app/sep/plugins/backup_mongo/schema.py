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

"""Define the PluginSchema for the backup_mongo plugin."""

from app.inventory.models import ServiceTypeEnum
from app.sep.plugins.backup_mongo.models import CompressionAlgorithm, StorageType
from app.sep.plugins.framework.rules import F, FieldGate
from app.sep.plugins.framework.schema import (
    BoolField,
    Capabilities,
    Choice,
    ChoiceField,
    Column,
    ColumnFormat,
    DerivedTask,
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

_S3_STORAGE = F("storage_type") == StorageType.S3.value
_FILESYSTEM_STORAGE = F("storage_type") == StorageType.FILESYSTEM.value

BACKUP_MONGO_DERIVED = [
    DerivedTask(
        name_suffix="-logical",
        payload_substitutions={"pbm_config": "pbm_logical"},
        backup_type="pbm_logical",
    ),
    DerivedTask(
        name_suffix="-physical",
        payload_substitutions={
            "pbm_config": "pbm_logical",
            "pbm_logical": "pbm_physical",
        },
        backup_type="pbm_physical",
    ),
    DerivedTask(
        name_suffix="-status",
        payload_substitutions={
            "pbm_config": "pbm_logical",
            "pbm_physical": "pbm_status",
        },
        backup_type="pbm_status",
    ),
]

_COMPRESSION_CHOICES = [
    Choice(label=algorithm.value, value=algorithm.value)
    for algorithm in CompressionAlgorithm
]

backup_mongo_schema = PluginSchema(
    name="backup_mongo",
    display_name="MongoDB Backups",
    description=(
        "Configure Percona Backup for MongoDB (PBM) and manage logical, "
        "physical, and status backup tasks."
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
                    required=True,
                    service_types=[ServiceTypeEnum.MONGODB],
                ),
                StringField(
                    name="credentials_path",
                    label="Credentials Path",
                    description=(
                        "Optional path to MongoDB URI credentials on the Nomad node"
                    ),
                ),
                BoolField(
                    name="alert_on_fail",
                    label="Alert on Failure",
                    default=False,
                ),
            ],
        ),
        FormSection(
            title="Storage",
            fields=[
                ChoiceField(
                    name="storage_type",
                    label="Storage Type",
                    choices=[
                        Choice(label="S3-compatible", value=StorageType.S3.value),
                        Choice(
                            label="Filesystem",
                            value=StorageType.FILESYSTEM.value,
                        ),
                    ],
                ),
                StringField(
                    name="storage_s3_region",
                    label="S3 Region",
                    requires=[FieldGate(when=_S3_STORAGE)],
                ),
                StringField(
                    name="storage_s3_bucket",
                    label="S3 Bucket",
                    requires=[FieldGate(when=_S3_STORAGE)],
                ),
                StringField(
                    name="storage_s3_prefix",
                    label="S3 Prefix",
                    requires=[FieldGate(when=_S3_STORAGE)],
                ),
                StringField(
                    name="storage_s3_endpoint_url",
                    label="S3 Endpoint URL",
                    requires=[FieldGate(when=_S3_STORAGE)],
                ),
                StringField(
                    name="storage_filesystem_path",
                    label="Filesystem Path",
                    requires=[FieldGate(when=_FILESYSTEM_STORAGE)],
                ),
            ],
        ),
        FormSection(
            title="Point-in-Time Recovery",
            fields=[
                BoolField(
                    name="pitr_enabled",
                    label="Enable PITR",
                    default=False,
                ),
                IntegerField(
                    name="pitr_oplog_span_min",
                    label="Oplog Span (minutes)",
                ),
                ChoiceField(
                    name="pitr_compression",
                    label="PITR Compression",
                    choices=_COMPRESSION_CHOICES,
                ),
            ],
        ),
        FormSection(
            title="Backup Options",
            fields=[
                TextAreaField(
                    name="backup_priority",
                    label="Node Priority (YAML)",
                    description="YAML mapping of mongod addresses to backup priority",
                ),
                ChoiceField(
                    name="backup_compression",
                    label="Backup Compression",
                    choices=_COMPRESSION_CHOICES,
                ),
                IntegerField(
                    name="backup_compression_level",
                    label="Compression Level",
                ),
                IntegerField(
                    name="backup_timeouts_starting_status",
                    label="Starting Status Timeout (seconds)",
                ),
                FloatField(
                    name="backup_oplog_span_min",
                    label="Backup Oplog Span (minutes)",
                ),
                IntegerField(
                    name="backup_num_parallel_collections",
                    label="Parallel Collections",
                ),
            ],
        ),
    ],
    derived=BACKUP_MONGO_DERIVED,
    capabilities=Capabilities(chaining=True, alert_on_fail=True, scheduling=True),
    list_view=ListView(
        columns=[
            Column(key="name", label="Name", sortable=True),
            Column(key="status", label="Status", format=ColumnFormat.STATUS),
            Column(key="hostname", label="Executor Host"),
            Column(key="backup_type", label="Type", format=ColumnFormat.CHIP),
            Column(key="created_at", label="Created", format=ColumnFormat.RELATIVE),
            Column(key="created_by", label="Created By"),
        ],
        default_sort="name",
    ),
)
