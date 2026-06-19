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

"""Define the PluginSchema for the Archives plugin."""

from app.inventory.models import ServiceTypeEnum
from app.sep.plugins.archives.constants import SwapDropEnum
from app.sep.plugins.framework.rules import (
    absent,
    all_,
    all_present,
    any_,
    CardinalityRule,
    F,
    FailRule,
    falsy,
    FieldGate,
    not_,
    present,
    truthy,
)
from app.sep.plugins.framework.schema import (
    BoolField,
    Capabilities,
    Choice,
    ChoiceField,
    Column,
    ColumnFormat,
    DateTimeField,
    DetailField,
    DetailSection,
    DetailView,
    FormSection,
    HostField,
    IntegerField,
    ListView,
    PluginSchema,
    SchemaField,
    ServiceField,
    StringField,
    TableField,
)

# Shared copy for the disabled-choice tooltip and the server-side FailRule so the
# UI hint and the validation error stay in sync.
_SWAP_DROP_UNSUPPORTED = "Not available yet. Only Purge Only is currently supported."

archives_schema = PluginSchema(
    name="archives",
    display_name="Archives",
    description="Run pt-archiver to purge or archive rows from a MySQL table.",
    forms=[
        FormSection(
            title="Task",
            fields=[
                StringField(
                    name="alias",
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
                    label="Source Service",
                    required=True,
                    service_types=[ServiceTypeEnum.MYSQL],
                ),
            ],
        ),
        FormSection(
            title="Archive Type",
            fields=[
                ChoiceField(
                    name="swap_drop",
                    label="Archive Type",
                    required=True,
                    default="0",
                    choices=[
                        Choice(label="Purge Only", value="0"),
                        Choice(
                            label="Swap & Drop",
                            value="1",
                            disabled=True,
                            disabled_reason=_SWAP_DROP_UNSUPPORTED,
                        ),
                        Choice(
                            label="Swap Archive & Drop",
                            value="2",
                            disabled=True,
                            disabled_reason=_SWAP_DROP_UNSUPPORTED,
                        ),
                    ],
                ),
            ],
            fail_when=[
                # Only Purge Only is supported. The disabled choices above gate the
                # UI; this rule rejects any crafted payload that bypasses them. It
                # also blocks edits that resubmit a pre-existing SWAP_DROP /
                # SWAP_ARCHIVE_DROP task (which loads fine read-only) until the
                # archive type is switched to Purge Only.
                FailRule(
                    fail_when=F("swap_drop") != SwapDropEnum.PURGE_ONLY,
                    error_fields=["swap_drop"],
                    message=_SWAP_DROP_UNSUPPORTED,
                ),
            ],
        ),
        FormSection(
            title="Source",
            fields=[
                SchemaField(
                    name="source_db_id",
                    label="Source Schema",
                    depends_on="service_id",
                    forbidden=[
                        FieldGate(when=truthy("source_query")),
                    ],
                ),
                StringField(
                    name="source_db_name",
                    label="Source Schema Name",
                    description="Manual entry — used when Source Schema is not in inventory.",
                    forbidden=[
                        FieldGate(when=truthy("source_query")),
                    ],
                ),
                TableField(
                    name="source_table_id",
                    label="Source Table",
                    depends_on="source_db_id",
                    forbidden=[
                        FieldGate(when=truthy("source_query")),
                    ],
                ),
                StringField(
                    name="source_table_name",
                    label="Source Table Name",
                    description="Manual entry — used when Source Table is not in inventory.",
                    forbidden=[
                        FieldGate(when=truthy("source_query")),
                    ],
                ),
                StringField(
                    name="source_query",
                    label="Source Query",
                    description="Custom query defining source rows; mutually exclusive with Source Schema/Table.",
                ),
            ],
            fail_when=[
                # Validator 5a: source_query absent and no IDs or names provided.
                FailRule(
                    fail_when=all_(
                        absent("source_query"),
                        not_(all_present("source_db_id", "source_table_id")),
                        not_(
                            all_(truthy("source_db_name"), truthy("source_table_name"))
                        ),
                    ),
                    error_fields=[
                        "source_db_id",
                        "source_table_id",
                        "source_db_name",
                        "source_table_name",
                    ],
                    message=(
                        "When source_query is not set, either both source_db_id and source_table_id "
                        "or both source_db_name and source_table_name must be provided."
                    ),
                ),
                # Validator 5b: conflict — both IDs and names set simultaneously.
                FailRule(
                    fail_when=all_(
                        present("source_db_id"),
                        present("source_table_id"),
                        truthy("source_db_name"),
                        truthy("source_table_name"),
                    ),
                    error_fields=[
                        "source_db_id",
                        "source_table_id",
                        "source_db_name",
                        "source_table_name",
                    ],
                    message=(
                        "Cannot use both source_db_id/source_table_id and "
                        "source_db_name/source_table_name at the same time."
                    ),
                ),
            ],
        ),
        FormSection(
            title="Destination",
            fields=[
                IntegerField(
                    name="dest_table_id",
                    label="Destination Table ID",
                    description="Inventory ID of the destination table.",
                    forbidden=[
                        # Validator 2: dest forbidden when SWAP_DROP or delete_data.
                        FieldGate(
                            when=any_(
                                F("swap_drop") == SwapDropEnum.SWAP_DROP,
                                truthy("delete_data"),
                            )
                        ),
                    ],
                ),
                StringField(
                    name="dest_table_name",
                    label="Destination Table Name",
                    description="Manual entry — used when destination table is not in inventory.",
                    forbidden=[
                        FieldGate(
                            when=any_(
                                F("swap_drop") == SwapDropEnum.SWAP_DROP,
                                truthy("delete_data"),
                            )
                        ),
                    ],
                ),
                StringField(
                    name="dest_file",
                    label="Destination File",
                    description="File path for archiving rows instead of a table.",
                    forbidden=[
                        FieldGate(
                            when=any_(
                                F("swap_drop") == SwapDropEnum.SWAP_DROP,
                                truthy("delete_data"),
                            )
                        ),
                    ],
                ),
            ],
            cardinality_rules=[
                # Validator 2: at most one destination: dest_file XOR dest_table.
                CardinalityRule(
                    fields=["dest_file", "dest_table_id", "dest_table_name"],
                    max=1,
                    message="Cannot set more than one destination (dest_file, dest_table_id, dest_table_name).",
                ),
            ],
            fail_when=[
                # Validator 2: destination required when not SWAP_DROP and not delete_data.
                FailRule(
                    fail_when=all_(
                        F("swap_drop") != SwapDropEnum.SWAP_DROP,
                        falsy("delete_data"),
                        absent("dest_file"),
                        absent("dest_table_id"),
                        falsy("dest_table_name"),
                    ),
                    error_fields=["dest_file", "dest_table_id", "dest_table_name"],
                    message="At least one of dest_file or dest_table_id/dest_table_name must be set.",
                ),
            ],
        ),
        FormSection(
            title="Destination Host",
            fields=[
                ServiceField(
                    name="dest_service_id",
                    label="Destination Service",
                    service_types=[ServiceTypeEnum.MYSQL],
                    description="Inventory lookup for the destination host; mutually exclusive with Destination Host.",
                ),
                StringField(
                    name="dest_host",
                    label="Destination Host",
                    description="Manual host address; mutually exclusive with Destination Service.",
                ),
                IntegerField(
                    name="dest_port",
                    label="Destination Port",
                    ge=1,
                    le=65535,
                    description="Port of the destination database (1-65535).",
                ),
                SchemaField(
                    name="dest_db_id",
                    label="Destination Schema",
                    depends_on="dest_service_id",
                    description="Inventory lookup for the destination schema.",
                ),
                StringField(
                    name="dest_db_name",
                    label="Destination Schema Name",
                    description="Manual schema name; mutually exclusive with Destination Schema.",
                ),
            ],
            fail_when=[
                # Validator 3a: dest_service_id and dest_host mutually exclusive.
                FailRule(
                    fail_when=all_(present("dest_service_id"), truthy("dest_host")),
                    error_fields=["dest_service_id", "dest_host"],
                    message=(
                        "Cannot use both dest_service_id (inventory) and dest_host "
                        "(manual input) at the same time."
                    ),
                ),
                # Validator 3b: dest_db_id and dest_db_name mutually exclusive.
                FailRule(
                    fail_when=all_(present("dest_db_id"), truthy("dest_db_name")),
                    error_fields=["dest_db_id", "dest_db_name"],
                    message=(
                        "Cannot use both dest_db_id (inventory) and dest_db_name "
                        "(manual input) at the same time."
                    ),
                ),
                # Validator 3c: dest_db_id requires dest_service_id.
                FailRule(
                    fail_when=all_(present("dest_db_id"), absent("dest_service_id")),
                    error_fields=["dest_db_id"],
                    message=(
                        "dest_db_id requires dest_service_id to be set "
                        "(cannot pick inventory schema with manual host)."
                    ),
                ),
                # Validator 3d: SWAP_ARCHIVE_DROP cannot have a destination host.
                # Unreachable while only Purge Only is selectable (the Archive Type
                # FailRule rejects swap_drop != PURGE_ONLY first).
                FailRule(
                    fail_when=all_(
                        F("swap_drop") == SwapDropEnum.SWAP_ARCHIVE_DROP,
                        any_(present("dest_service_id"), truthy("dest_host")),
                    ),
                    error_fields=["dest_service_id", "dest_host"],
                    message=(
                        "Cannot set destination host when swap_drop is SWAP_ARCHIVE_DROP (2) "
                        "(cross-host table swapping is not supported)."
                    ),
                ),
            ],
        ),
        FormSection(
            title="Options",
            fields=[
                DateTimeField(
                    name="swp_table_suffix",
                    label="Swap Table Suffix (Date)",
                    description="Date suffix appended to the swap table name (required for SWAP_ARCHIVE_DROP).",
                    # Validator 4: required when swap_drop == SWAP_ARCHIVE_DROP.
                    requires=[
                        FieldGate(
                            when=F("swap_drop") == SwapDropEnum.SWAP_ARCHIVE_DROP
                        ),
                    ],
                    # Hidden now because only Purge Only is selectable in scope.
                    forbidden=[
                        FieldGate(
                            when=F("swap_drop") != SwapDropEnum.SWAP_ARCHIVE_DROP
                        ),
                    ],
                ),
                StringField(
                    name="where",
                    label="WHERE Clause",
                    description="Condition filtering rows to archive (required unless SWAP_DROP).",
                    # Validator 6: required when swap_drop != SWAP_DROP.
                    requires=[
                        FieldGate(when=F("swap_drop") != SwapDropEnum.SWAP_DROP),
                    ],
                    # Validator 6: forbidden when swap_drop == SWAP_DROP.
                    forbidden=[
                        FieldGate(when=F("swap_drop") == SwapDropEnum.SWAP_DROP),
                    ],
                ),
            ],
        ),
        FormSection(
            title="Advanced",
            collapsible=True,
            collapsed_by_default=True,
            fields=[
                StringField(
                    name="use_index",
                    label="Use Index",
                    description="Index hint to optimise the query.",
                ),
                StringField(
                    name="extra_args",
                    label="Extra Args",
                    description="Additional pt-archiver CLI arguments.",
                ),
                IntegerField(
                    name="limit",
                    label="Limit",
                    ge=1,
                    description="Maximum rows per archiver run.",
                ),
                IntegerField(
                    name="sleep",
                    label="Sleep (s)",
                    ge=0,
                    description="Sleep duration between chunk operations (seconds).",
                ),
                BoolField(
                    name="disable_binlog",
                    label="Disable Binlog",
                    description="Disable binary logging for this operation.",
                ),
                BoolField(
                    name="disable_bulk_insert",
                    label="Disable Bulk Insert",
                    description="Disable bulk-insert optimisation.",
                ),
                BoolField(
                    name="delete_data",
                    label="Delete Without Archiving",
                    description="Source rows are deleted without being written to any destination; the Destination Table/File fields are disabled.",
                ),
            ],
        ),
    ],
    # Validator 1a: same table IDs.
    fail_when=[
        FailRule(
            fail_when=all_(
                present("source_table_id"),
                present("dest_table_id"),
                F("source_table_id") == F("dest_table_id"),
            ),
            error_fields=["source_table_id", "dest_table_id"],
            message="Source and Destination tables cannot be the same.",
        ),
        # Validator 1b: same destination identity (host + schema + table name).
        # Empty destination host/schema falls back to source at execution time, so
        # self-archive is detected only when host, schema, and table name all match.
        FailRule(
            fail_when=all_(
                truthy("source_db_name"),
                truthy("source_table_name"),
                truthy("dest_table_name"),
                F("source_table_name") == F("dest_table_name"),
                # Destination host resolves to the source host.
                any_(
                    all_(absent("dest_service_id"), falsy("dest_host")),
                    F("dest_service_id") == F("service_id"),
                ),
                # Destination schema resolves to the source schema.
                any_(
                    all_(absent("dest_db_id"), falsy("dest_db_name")),
                    F("dest_db_name") == F("source_db_name"),
                ),
            ),
            error_fields=["source_table_name", "dest_table_name"],
            message="Source and Destination tables cannot be the same.",
        ),
    ],
    capabilities=Capabilities(
        chaining=True,
        alert_on_fail=True,
        scheduling=True,
        stats=True,
    ),
    list_view=ListView(
        columns=[
            Column(key="name", label="Name", sortable=True),
            Column(key="status", label="Status", format=ColumnFormat.STATUS),
            Column(key="service_type", label="Service Type", format=ColumnFormat.CHIP),
            Column(key="created_at", label="Created", format=ColumnFormat.RELATIVE),
            Column(key="created_by", label="Created By"),
        ],
    ),
    detail_view=DetailView(
        sections=[
            DetailSection(
                title="Archive Configuration",
                fields=[
                    DetailField(path="data.meta.target", label="Executor Host"),
                    DetailField(path="data.meta.config", label="Config (YAML)"),
                ],
            ),
        ],
    ),
)
