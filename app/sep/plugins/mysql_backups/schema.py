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

"""Define the PluginSchema for the MySQL Backups plugin.

Per-mode field gating is uniformly schema-declared:

- ``forbidden=`` :class:`FieldGate` for string/int/choice fields. We use
  ``forbidden=[when != mode]`` (not ``requires=[when == mode]``) because
  the framework's ``requires=`` semantics (``rules.py:1442-1449``) mean
  "when predicate true, the field MUST be present" — using it for mode
  gating would make every X-mode field mandatory in X mode, which is
  incorrect: these fields are optional within their mode and only
  forbidden outside it.
- Schema-level :class:`FailRule` entries (``_MODE_BOOL_FAIL_RULES``) for
  booleans. ``forbidden=`` on a bool field would reject the legitimate
  default because ``_field_is_present`` treats ``False`` as "present";
  ``FailRule(fail_when=truthy(name) & (F('backup_type') != owner))``
  fires only on the explicit ``True`` case, which is what we want.
"""

from app.inventory.models import ServiceTypeEnum
from app.sep.plugins.framework.rules import (
    Contains,
    F,
    FailRule,
    falsy,
    FieldGate,
    not_,
    truthy,
)
from app.sep.plugins.framework.schema import (
    BoolField,
    Capabilities,
    Choice,
    ChoiceField,
    Column,
    ColumnFormat,
    FormSection,
    HostField,
    IntegerField,
    ListView,
    MultiChoiceField,
    PluginSchema,
    ServiceField,
    StringField,
)

_BACKUP_TYPE_CHOICES = [
    Choice(label="Mydumper", value="M"),
    Choice(label="XtraBackup", value="X"),
    Choice(label="Binlog", value="B"),
]

# Upload-provider choice values. Re-used by the schema's ``Contains`` gates
# (see the Upload section below) so the choice values, the gate operands,
# and the ``UploadProvider`` enum names stay in sync. The frontend submits
# these strings verbatim; the backend coerces them to ``UploadProvider``
# via ``EnumFieldMixin``.
_UPLOAD_S3 = "S3"
_UPLOAD_RSYNC = "RSYNC"
_UPLOAD_GSUTIL = "GSUTIL"

_UPLOAD_CHOICES = [
    Choice(label="Rsync", value=_UPLOAD_RSYNC),
    Choice(label="S3", value=_UPLOAD_S3),
    Choice(label="Google Cloud Storage", value=_UPLOAD_GSUTIL),
]


def _upload_excludes(provider: str) -> list[FieldGate]:
    """Hide / forbid a destination field unless ``provider`` is in ``upload``.

    Used by :attr:`BaseField.forbidden` on string upload-destination fields.
    On the frontend ``useConditionalField`` hides + unregisters the field
    when the gate fires (provider missing from the user's selection); on
    the backend ``_evaluate_field_gate_forbidden`` rejects a present value
    in the same case, giving us "explicit MultiChoice contract" enforcement
    without duplicating the bidirectional check from
    :meth:`BackupCreate.validate_upload_provider_consistency`.

    Bool fields (e.g. ``skip_s3_safety_check``) intentionally skip this
    gate because ``_field_is_present(False)`` is ``True`` and would reject
    the legitimate default — those remain covered by the model validator.
    """
    return [FieldGate(when=not_(Contains("upload", provider)))]


def _other_modes_forbid(mode: str) -> list[FieldGate]:
    """Return a gate forbidding the field when ``backup_type`` is not ``mode``."""
    return [FieldGate(when=F("backup_type") != mode)]


_mydumper_forbidden = _other_modes_forbid("M")
_xtrabackup_forbidden = _other_modes_forbid("X")
_binlog_forbidden = _other_modes_forbid("B")

# Bool fields owned by a specific backup mode. A truthy value outside its
# owning mode fails validation via the schema-level FailRules below.
# ``binlog_run_all`` defaults to True and the legacy form always sends it,
# so the BINLOG entry is intentionally empty until the form migrates off
# that default.
_MODE_BOOL_FIELDS: dict[str, tuple[str, ...]] = {
    "M": (
        "mydumper_dump_triggers",
        "mydumper_desync_pxc",
        "mydumper_use_numa",
    ),
    "X": (
        "xtrabackup_kill_queries",
        "xtrabackup_verify",
        "xtrabackup_prepare",
        "xtrabackup_desync_pxc",
        "xtrabackup_rsync",
        "xtrabackup_replica_info",
        "xtrabackup_stop_replica",
        "xtrabackup_lock_ddl",
    ),
    "B": (),
}

_MODE_BOOL_FAIL_RULES: list[FailRule] = [
    FailRule(
        fail_when=truthy(name) & (F("backup_type") != owner_mode),
        error_fields=[name],
        message=f"{name!r} must not be set when backup_type is not {owner_mode!r}.",
    )
    for owner_mode, names in _MODE_BOOL_FIELDS.items()
    for name in names
]


mysql_backups_schema = PluginSchema(
    name="mysql_backups",
    display_name="MySQL Backups",
    description="Run XtraBackup, Mydumper, and Binlog backups against MySQL hosts.",
    forms=[
        FormSection(
            title="Task",
            fields=[
                StringField(name="task_name", label="Task Name", required=True),
                HostField(name="hostname", label="Executor Host", required=True),
                ServiceField(
                    name="service_id",
                    label="Database Host",
                    required=True,
                    service_types=[ServiceTypeEnum.MYSQL],
                ),
                ChoiceField(
                    name="backup_type",
                    label="Backup Type",
                    required=True,
                    choices=_BACKUP_TYPE_CHOICES,
                ),
                BoolField(
                    name="alert_on_fail", label="Alert on Failure", default=False
                ),
                StringField(name="alias", label="Server Alias"),
            ],
        ),
        FormSection(
            title="General",
            collapsible=True,
            collapsed_by_default=True,
            fields=[
                BoolField(
                    name="hardlink", label="Hardlink full backups", default=False
                ),
                BoolField(name="compress", label="Compress backup data", default=False),
                BoolField(
                    name="check_disk_space",
                    label="Check disk space first",
                    default=False,
                ),
                BoolField(
                    name="only_if_running_replica",
                    label="Only if running replica",
                    default=False,
                ),
                BoolField(
                    name="only_if_read_only", label="Only if read-only", default=False
                ),
                BoolField(
                    name="use_ftwrl_guardian", label="FTWRL guardian", default=False
                ),
                StringField(name="logging_dir", label="Logging directory"),
                StringField(name="backup_dir", label="Backup directory"),
                StringField(name="defaults_file", label="MySQL defaults file"),
                ChoiceField(
                    name="compression_algorithm",
                    label="Compression algorithm",
                    choices=[
                        Choice(label="zstd", value="zstd"),
                        Choice(label="lz4", value="lz4"),
                        Choice(label="gzip", value="gzip"),
                        Choice(label="quicklz", value="quicklz"),
                    ],
                ),
            ],
        ),
        FormSection(
            title="Mydumper",
            collapsible=True,
            fields=[
                IntegerField(
                    name="mydumper_daily_purge",
                    label="Daily purge (days)",
                    forbidden=_mydumper_forbidden,
                ),
                IntegerField(
                    name="mydumper_weekly_purge",
                    label="Weekly purge (weeks)",
                    forbidden=_mydumper_forbidden,
                ),
                BoolField(
                    name="mydumper_dump_triggers",
                    label="Dump triggers",
                    default=False,
                ),
                BoolField(
                    name="mydumper_desync_pxc",
                    label="Desync PXC node",
                    default=False,
                ),
                BoolField(
                    name="mydumper_use_numa",
                    label="Use NUMA",
                    default=False,
                ),
                StringField(
                    name="mydumper_extra_args",
                    label="Extra args",
                    forbidden=_mydumper_forbidden,
                ),
            ],
        ),
        FormSection(
            title="XtraBackup",
            collapsible=True,
            fields=[
                IntegerField(
                    name="xtrabackup_copies",
                    label="Number of backup copies",
                    forbidden=_xtrabackup_forbidden,
                ),
                BoolField(
                    name="xtrabackup_kill_queries",
                    label="Kill blocking queries",
                    default=False,
                ),
                IntegerField(
                    name="xtrabackup_kill_queries_timeout",
                    label="Kill-queries timeout (s)",
                    forbidden=_xtrabackup_forbidden,
                ),
                ChoiceField(
                    name="xtrabackup_kill_query_type",
                    label="Kill query type",
                    choices=[
                        Choice(label="SELECT", value="select"),
                        Choice(label="All", value="all"),
                    ],
                    forbidden=_xtrabackup_forbidden,
                ),
                BoolField(
                    name="xtrabackup_verify",
                    label="Verify after backup",
                    default=False,
                ),
                BoolField(
                    name="xtrabackup_prepare",
                    label="Prepare for restore",
                    default=False,
                ),
                StringField(
                    name="xtrabackup_prepare_memory",
                    label="Prepare memory",
                    forbidden=_xtrabackup_forbidden,
                ),
                BoolField(
                    name="xtrabackup_desync_pxc",
                    label="Desync PXC node",
                    default=False,
                ),
                BoolField(
                    name="xtrabackup_rsync",
                    label="Use rsync",
                    default=False,
                ),
                BoolField(
                    name="xtrabackup_replica_info",
                    label="Include replica info",
                    default=False,
                ),
                StringField(
                    name="xtrabackup_defaults_file",
                    label="XtraBackup defaults file",
                    forbidden=_xtrabackup_forbidden,
                ),
                StringField(
                    name="xtrabackup_extra_args",
                    label="Extra args",
                    forbidden=_xtrabackup_forbidden,
                ),
                ChoiceField(
                    name="xtrabackup_incremental_method",
                    label="Incremental method",
                    choices=[
                        Choice(label="Less space", value="less_space"),
                        Choice(label="Fast restore", value="fast_restore"),
                    ],
                    forbidden=_xtrabackup_forbidden,
                ),
                ChoiceField(
                    name="xtrabackup_incremental_cycle",
                    label="Incremental cycle",
                    choices=[
                        Choice(label="Daily", value="daily"),
                        Choice(label="Weekly", value="weekly"),
                        Choice(label="2 days", value="2"),
                        Choice(label="3 days", value="3"),
                        Choice(label="4 days", value="4"),
                        Choice(label="5 days", value="5"),
                        Choice(label="6 days", value="6"),
                        Choice(label="7 days", value="7"),
                    ],
                    forbidden=_xtrabackup_forbidden,
                ),
                StringField(
                    name="xtrabackup_local_ssh_destination",
                    label="Local SSH destination",
                    forbidden=_xtrabackup_forbidden,
                ),
                StringField(
                    name="xtrabackup_aes256_keyfile",
                    label="AES-256 key file path",
                    forbidden=_xtrabackup_forbidden,
                ),
                BoolField(
                    name="xtrabackup_stop_replica",
                    label="Stop replica before backup",
                    default=False,
                ),
                BoolField(
                    name="xtrabackup_lock_ddl",
                    label="Lock DDL",
                    default=False,
                ),
                ChoiceField(
                    name="xtrabackup_bin_cmd",
                    label="Backup binary",
                    choices=[
                        Choice(label="xtrabackup", value="xtrabackup"),
                        Choice(label="mariadb-backup", value="mariadb-backup"),
                        Choice(label="innobackupex", value="innobackupex"),
                    ],
                    forbidden=_xtrabackup_forbidden,
                ),
            ],
        ),
        FormSection(
            title="Binlog",
            collapsible=True,
            fields=[
                StringField(
                    name="binlog_prefix",
                    label="Binlog prefix",
                    forbidden=_binlog_forbidden,
                ),
                IntegerField(
                    name="binlog_purge_days",
                    label="Purge after (days)",
                    forbidden=_binlog_forbidden,
                ),
                StringField(
                    name="binlog_extra_args",
                    label="Extra args",
                    forbidden=_binlog_forbidden,
                ),
                StringField(
                    name="binlog_compress_cmd",
                    label="Compress command",
                    forbidden=_binlog_forbidden,
                ),
                StringField(
                    name="binlog_cmd",
                    label="Binlog command",
                    forbidden=_binlog_forbidden,
                ),
                BoolField(
                    name="binlog_run_all",
                    label="Run all binlog backups",
                    default=True,
                ),
                StringField(
                    name="binlog_alternative_host",
                    label="Alternative binlog host",
                    forbidden=_binlog_forbidden,
                ),
            ],
        ),
        FormSection(
            title="Encryption",
            collapsible=True,
            fields=[
                BoolField(name="encrypt", label="Encrypt backup", default=False),
                BoolField(
                    name="encrypt_using_tmpdir",
                    label="Encrypt using tmpdir",
                    default=False,
                ),
                BoolField(
                    name="post_run_encrypt",
                    label="Encrypt after backup completes",
                    default=False,
                ),
                StringField(
                    name="encryption_recipient",
                    label="Encryption recipient",
                    requires=[FieldGate(when=truthy("encrypt"))],
                    forbidden=[FieldGate(when=falsy("encrypt"))],
                ),
            ],
        ),
        FormSection(
            title="Upload",
            collapsible=True,
            fields=[
                MultiChoiceField(
                    name="upload",
                    label="Upload providers",
                    choices=_UPLOAD_CHOICES,
                    required=True,
                ),
                StringField(
                    name="s3_bucket",
                    label="S3 bucket",
                    forbidden=_upload_excludes(_UPLOAD_S3),
                ),
                StringField(
                    name="s3_storage_class",
                    label="S3 storage class",
                    forbidden=_upload_excludes(_UPLOAD_S3),
                ),
                BoolField(
                    name="skip_s3_safety_check",
                    label="Skip S3 safety check",
                    default=False,
                ),
                StringField(
                    name="awscli_s3_upload_extra_args",
                    label="AWS S3 upload extra args",
                    forbidden=_upload_excludes(_UPLOAD_S3),
                ),
                StringField(
                    name="gs_bucket",
                    label="Google Cloud Storage bucket",
                    forbidden=_upload_excludes(_UPLOAD_GSUTIL),
                ),
                StringField(
                    name="rsync_path",
                    label="Rsync destination path",
                    forbidden=_upload_excludes(_UPLOAD_RSYNC),
                ),
            ],
        ),
    ],
    fail_when=_MODE_BOOL_FAIL_RULES,
    capabilities=Capabilities(chaining=True, alert_on_fail=True, scheduling=True),
    list_view=ListView(
        columns=[
            Column(key="name", label="Name", sortable=True),
            Column(key="status", label="Status", format=ColumnFormat.STATUS),
            Column(key="backup_type", label="Type", format=ColumnFormat.CHIP),
            Column(key="hostname", label="Host"),
            Column(key="created_at", label="Created", format=ColumnFormat.RELATIVE),
            Column(key="created_by", label="Created By"),
        ],
    ),
)
