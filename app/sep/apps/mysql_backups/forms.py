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

"""Define the Backups plugin's task-form models and API request/response shapes.

Imports ``app.inventory`` and the app framework's form DSL, so — unlike
:mod:`app.sep.apps.mysql_backups.models` — this module cannot be loaded at
Alembic migration time; see that module's docstring for the split rationale.
"""

from enum import auto, IntEnum, StrEnum
from typing import Annotated, Any, ClassVar, Literal, Self

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
)

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import (
    bounded_int_from_empty_str_factory,
    EmptyStrToNone,
    EnumFieldMixin,
    NonEmptyStr,
)
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework.form_dsl import (
    Choices,
    Forbidden,
    FormRules,
    Requires,
    ServiceRef,
    TaskFormModel,
    Ui,
)
from app.sep.apps.framework.rules import (
    AllFalsy,
    any_,
    AnyTruthy,
    Contains,
    F,
    FailRule,
    falsy,
    not_,
    truthy,
)
from app.sep.apps.mysql_backups.models import BackupType
from app.sep.apps.shared.backups.responses import BackupTaskBase

OWNER = "BACKUPS"


class SwapDropEnum(IntEnum):
    """Enum for defining types of swap actions for table data handling."""

    PURGE_ONLY = 0
    SWAP_DROP = 1
    SWAP_ARCHIVE_DROP = 2


class CompressionAlgorithm(EnumFieldMixin, StrEnum):
    """Enumeration for Compression Algorithms."""

    ZSTD = "zstd"
    LZ4 = "lz4"
    GZIP = "gzip"
    QUICKLZ = "quicklz"


ALLOWED_COMPRESSIONS = {
    BackupType.MYDUMPER: [CompressionAlgorithm.GZIP, CompressionAlgorithm.ZSTD],
    BackupType.XTRABACKUP: [
        CompressionAlgorithm.ZSTD,
        CompressionAlgorithm.LZ4,
        CompressionAlgorithm.QUICKLZ,
    ],
    BackupType.BINLOG: [CompressionAlgorithm.GZIP],
}


class EncryptionFormat(EnumFieldMixin, StrEnum):
    """Represent the backup-time encryption formats an operator can select."""

    NONE = "none"
    GPG = "gpg"
    AES256 = "aes256"
    DUAL = "dual"


# Ordered so a format's index encodes its passes — bit 1 is AES-256, bit 0 is GPG.
# The backup payload carries the same ordering, which is what lets both sides infer
# a pre-selector task's format without keeping a second copy of the mode table.
ENCRYPTION_FORMAT_BY_PASSES = (
    EncryptionFormat.NONE,
    EncryptionFormat.GPG,
    EncryptionFormat.AES256,
    EncryptionFormat.DUAL,
)


def encryption_format_for_passes(*, aes256: bool, gpg: bool) -> EncryptionFormat:
    """Return the format that runs exactly the given passes.

    Owns the index arithmetic so each caller only has to decide which passes a
    stored task ran — the stored config and a stored form spell those fields
    differently, but they agree on the format the pair implies.

    :param aes256: Whether the task runs XtraBackup's built-in AES-256 pass.
    :param gpg: Whether the task runs a GPG pass.
    :return: The matching format.
    """
    return ENCRYPTION_FORMAT_BY_PASSES[aes256 * 2 + gpg]


# AES-256 is XtraBackup's own ``--encrypt`` / xbcrypt path, so only that engine
# can reach the AES-bearing formats; GPG is applied to the finished directory and
# works for every engine.
ALLOWED_ENCRYPTION_FORMATS = {
    BackupType.MYDUMPER: [EncryptionFormat.NONE, EncryptionFormat.GPG],
    BackupType.XTRABACKUP: list(EncryptionFormat),
    BackupType.BINLOG: [EncryptionFormat.NONE, EncryptionFormat.GPG],
}


class UploadProvider(EnumFieldMixin, StrEnum):
    """Upload providers."""

    RSYNC = auto()
    S3 = auto()
    GSUTIL = auto()


# Single source for the ``upload`` choice values and the destination-field
# ``Contains`` gate operands, kept in sync with the ``UploadProvider`` enum names.
_UPLOAD_S3 = "S3"
_UPLOAD_RSYNC = "RSYNC"
_UPLOAD_GSUTIL = "GSUTIL"

# ``forbidden`` (not ``requires``): these fields are optional within their owning
# mode, only forbidden outside it. Bool fields are gated by the ``FailRule``s below
# instead — ``_field_is_present`` treats ``False`` as absent, so a gate here would
# never fire on their default.
_MYDUMPER_ONLY = Forbidden(when=F("backup_type") != "M")
_XTRABACKUP_ONLY = Forbidden(when=F("backup_type") != "X")
_BINLOG_ONLY = Forbidden(when=F("backup_type") != "B")

# ``encryption_format`` is the signal for *which* encryption runs; the key file
# and the GPG timing bools below are its format-specific parameters, unreachable
# outside their format. Reused across those fields the way the ``_ONLY`` gates
# are, so the vocabulary lives in one place.
_FMT = F("encryption_format")
_FMT_HAS_AES = any_(_FMT == EncryptionFormat.AES256, _FMT == EncryptionFormat.DUAL)
_FMT_HAS_GPG = any_(_FMT == EncryptionFormat.GPG, _FMT == EncryptionFormat.DUAL)

# The GPG timing bools, gated by ``encryption_format`` rather than by
# ``Forbidden``: ``_field_is_present`` treats ``False`` as absent, so a field gate
# would never fire on their default.
_GPG_TIMING_FIELDS = ("encrypt", "post_run_encrypt")

# Each timing also needs a runtime that reaches it. In-place GPG runs inside the
# upload provider loop for every engine, and a Binlog backup encrypts nowhere else,
# so those combinations require an upload target — accepting them would let a task
# report a GPG format and still finish in plaintext. Post-run GPG on Mydumper and
# XtraBackup encrypts the finished directory on the host, so it needs no target.

_S3_ONLY = Forbidden(when=not_(Contains("upload", _UPLOAD_S3)))
_GSUTIL_ONLY = Forbidden(when=not_(Contains("upload", _UPLOAD_GSUTIL)))
_RSYNC_ONLY = Forbidden(when=not_(Contains("upload", _UPLOAD_RSYNC)))

# Bool fields owned by each backup mode. The BINLOG entry is intentionally empty:
# ``binlog_run_all`` defaults to True and the legacy form always sends it, so no
# BINLOG-only bool needs gating.
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
        "xtrabackup_quiet",
    ),
    "B": (),
}


class DirEncryptConfig(BaseModel):
    """Represent the encryption configuration for the backup task.

    :param encryption_recipient: The recipient of the encryption key.
    :type encryption_recipient: NonEmptyStr | None
    """

    encryption_recipient: NonEmptyStr | None = Field(
        None, serialization_alias="encryption recipient"
    )


class BackupConfigAll(BaseCaseInsensitiveModel):
    """Represent the general configuration for the backup task."""

    hardlink: bool = False
    compress: bool = False
    check_disk_space: bool = False
    encryption_format: EncryptionFormat = EncryptionFormat.NONE
    encrypt: bool = False
    encrypt_using_tmpdir: bool = False
    post_run_encrypt: bool = False
    only_if_running_replica: bool = False
    only_if_read_only: bool = False
    logging_dir: NonEmptyStr | EmptyStrToNone = None
    backup_dir: NonEmptyStr | EmptyStrToNone = None
    defaults_file: NonEmptyStr | EmptyStrToNone = None
    compression_algorithm: CompressionAlgorithm | EmptyStrToNone = None
    mydumper_daily_purge: int | EmptyStrToNone = None
    mydumper_weekly_purge: int | EmptyStrToNone = None
    mydumper_dump_triggers: bool = False
    mydumper_desync_pxc: bool = False
    mydumper_use_numa: bool = False
    mydumper_extra_args: str | EmptyStrToNone = None
    mydumper_verbose: Annotated[int, Field(ge=0, le=3)] | EmptyStrToNone = None
    use_ftwrl_guardian: bool = False
    xtrabackup_copies: int | EmptyStrToNone = None
    xtrabackup_kill_queries: bool = False
    xtrabackup_kill_queries_timeout: int | EmptyStrToNone = None
    xtrabackup_kill_query_type: Literal["select", "all"] | EmptyStrToNone = None
    xtrabackup_verify: bool = False
    xtrabackup_prepare: bool = False
    xtrabackup_prepare_memory: NonEmptyStr | EmptyStrToNone = None
    xtrabackup_desync_pxc: bool = False
    xtrabackup_rsync: bool = False
    xtrabackup_replica_info: bool = False
    xtrabackup_defaults_file: NonEmptyStr | EmptyStrToNone = None
    xtrabackup_extra_args: NonEmptyStr | EmptyStrToNone = None
    xtrabackup_incremental_method: (
        Literal["less_space", "fast_restore"] | EmptyStrToNone
    ) = None
    # Spelled out on three surfaces: this union, BackupCreate's union, and its Choices
    # labels (the standalone payload carries a fourth, since it runs on the DB host).
    # A StrEnum would collapse the unions but republish the field as a named OpenAPI
    # component rather than an inline enum, and the weekday labels would still need
    # Choices; the vocabulary parity tests fail on a partial edit meanwhile.
    xtrabackup_incremental_cycle: (
        Literal["daily", "weekly", "1", "2", "3", "4", "5", "6", "7"] | EmptyStrToNone
    ) = None
    xtrabackup_local_ssh_destination: NonEmptyStr | EmptyStrToNone = None
    xtrabackup_aes256_keyfile: NonEmptyStr | EmptyStrToNone = None
    xtrabackup_stop_replica: bool = False
    xtrabackup_lock_ddl: bool = False
    xtrabackup_quiet: bool = False
    xtrabackup_bin_cmd: (
        Literal["xtrabackup", "mariadb-backup", "innobackupex"] | EmptyStrToNone
    ) = None
    binlog_prefix: NonEmptyStr | EmptyStrToNone = None
    binlog_purge_days: int | EmptyStrToNone = None
    binlog_extra_args: NonEmptyStr | EmptyStrToNone = None
    binlog_compress_cmd: NonEmptyStr | EmptyStrToNone = None
    binlog_cmd: NonEmptyStr | EmptyStrToNone = None
    binlog_run_all: bool = True
    binlog_alternative_host: NonEmptyStr | EmptyStrToNone = None
    s3_bucket: NonEmptyStr | EmptyStrToNone = None
    s3_storage_class: NonEmptyStr | EmptyStrToNone = None
    skip_s3_safety_check: bool = False
    upload_quiet: bool = False
    awscli_s3_upload_extra_args: NonEmptyStr | EmptyStrToNone = None
    gs_bucket: NonEmptyStr | EmptyStrToNone = None
    rsync_path: NonEmptyStr | EmptyStrToNone = None


class BackupCreate(TaskFormModel):
    """Declare the model-first create/update body and ``GET /schema`` source for MySQL Backups.

    Declares each form field once, in section order (Task, General, Mydumper,
    XtraBackup, Binlog, Encryption, Upload), with the DSL markers driving the
    derived schema. Field declaration order is load-bearing: the derived section
    order follows each section's first field, and the within-section order follows
    declaration order, so the derived section and field order matches the
    hand-written schema. The conditional gating that the legacy ``schema.py`` declared
    (per-mode ``forbidden`` gates, the upload-provider ``Contains`` gates, the
    encryption gates — ``encryption_format`` selects which encryption runs and the
    rest of the section parameterises it: the key file is required by the
    AES-bearing formats and forbidden outside them, a GPG-bearing format needs one
    of the two independent timings (``encrypt`` in place, ``post_run_encrypt``
    after), ``encrypt_using_tmpdir`` requires ``encrypt`` and is forbidden
    alongside ``post_run_encrypt`` so post-run takes precedence (matching the
    backend at ``mydumper_payload``), and ``encryption_recipient`` is required iff
    either timing is on — and the per-mode and encryption-format bool
    ``FailRule``s in
    :attr:`__form_rules__`) now lives on the model; ``AppFormModel`` extracts it
    into the conditional-rule plan at class definition, so no
    ``@apply_conditional_rules`` decorator is needed. The config sub-models
    (:class:`BackupConfigAll` and friends) stay the serialization target the
    payload builder populates, not this model's base class.

    :cvar __form_rules__: The bool fail rules — a truthy mode-owned bool outside
        its mode, or a GPG timing outside a GPG ``encryption_format``, fails
        validation with a per-field message, as does a GPG format with no timing.
    """

    __form_rules__: ClassVar[FormRules] = FormRules(
        fail_when=(
            *(
                FailRule(
                    fail_when=truthy(name) & (F("backup_type") != owner_mode),
                    error_fields=[name],
                    message=(
                        f"{name!r} must not be set when backup_type is not "
                        f"{owner_mode!r}."
                    ),
                )
                for owner_mode, names in _MODE_BOOL_FIELDS.items()
                for name in names
            ),
            *(
                FailRule(
                    fail_when=truthy(name) & not_(_FMT_HAS_GPG),
                    error_fields=[name],
                    message=(
                        f"{name!r} must not be set when 'encryption_format' does "
                        "not include GPG."
                    ),
                )
                for name in _GPG_TIMING_FIELDS
            ),
            FailRule(
                fail_when=_FMT_HAS_GPG & AllFalsy(_GPG_TIMING_FIELDS),
                error_fields=list(_GPG_TIMING_FIELDS),
                message=(
                    "A GPG 'encryption_format' requires 'encrypt' or "
                    "'post_run_encrypt' to select when the backup is encrypted."
                ),
            ),
            FailRule(
                fail_when=truthy("encrypt") & falsy("upload"),
                error_fields=["encrypt", "upload"],
                message=(
                    "'encrypt' encrypts the backup in place as part of an upload, "
                    "so it requires at least one upload provider. Use "
                    "'post_run_encrypt' to encrypt on the host instead."
                ),
            ),
            FailRule(
                fail_when=truthy("post_run_encrypt")
                & (F("backup_type") == "B")
                & falsy("upload"),
                error_fields=["post_run_encrypt", "upload"],
                message=(
                    "A Binlog backup encrypts only as part of an upload, so "
                    "'post_run_encrypt' requires at least one upload provider."
                ),
            ),
        )
    )

    service_id: Annotated[
        int,
        ServiceRef(service_types=(ServiceTypeEnum.MYSQL,), check_connectivity=True),
        Ui(label="Database Host", section="Task"),
    ]
    backup_type: Annotated[
        BackupType,
        Choices((("M", "Mydumper"), ("X", "XtraBackup"), ("B", "Binlog"))),
        Ui(section="Task"),
    ]
    alias: Annotated[
        NonEmptyStr | EmptyStrToNone, Ui(label="Server Alias", section="Task")
    ] = None

    hardlink: Annotated[bool, Ui(label="Hardlink full backups", section="General")] = (
        False
    )
    compress: Annotated[bool, Ui(label="Compress backup data", section="General")] = (
        False
    )
    check_disk_space: Annotated[
        bool, Ui(label="Check disk space first", section="General")
    ] = False
    only_if_running_replica: Annotated[
        bool, Ui(label="Only if running replica", section="General")
    ] = False
    only_if_read_only: Annotated[
        bool, Ui(label="Only if read-only", section="General")
    ] = False
    use_ftwrl_guardian: Annotated[
        bool, Ui(label="FTWRL guardian", section="General")
    ] = False
    logging_dir: Annotated[
        NonEmptyStr | EmptyStrToNone, Ui(label="Logging directory", section="General")
    ] = None
    backup_dir: Annotated[
        NonEmptyStr | EmptyStrToNone, Ui(label="Backup directory", section="General")
    ] = None
    defaults_file: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Ui(label="MySQL defaults file", section="General"),
    ] = None
    compression_algorithm: Annotated[
        CompressionAlgorithm | EmptyStrToNone,
        Ui(label="Compression algorithm", section="General"),
    ] = None

    mydumper_daily_purge: Annotated[
        int | EmptyStrToNone,
        _MYDUMPER_ONLY,
        Ui(label="Daily purge (days)", section="Mydumper"),
    ] = None
    mydumper_weekly_purge: Annotated[
        int | EmptyStrToNone,
        _MYDUMPER_ONLY,
        Ui(label="Weekly purge (weeks)", section="Mydumper"),
    ] = None
    mydumper_dump_triggers: Annotated[
        bool, Ui(label="Dump triggers", section="Mydumper")
    ] = False
    mydumper_desync_pxc: Annotated[
        bool, Ui(label="Desync PXC node", section="Mydumper")
    ] = False
    mydumper_use_numa: Annotated[bool, Ui(label="Use NUMA", section="Mydumper")] = False
    mydumper_extra_args: Annotated[
        str | EmptyStrToNone, _MYDUMPER_ONLY, Ui(label="Extra args", section="Mydumper")
    ] = None
    mydumper_verbose: Annotated[
        bounded_int_from_empty_str_factory(0, 3),
        _MYDUMPER_ONLY,
        Ui(label="Verbose level", section="Mydumper"),
    ] = None

    xtrabackup_copies: Annotated[
        int | EmptyStrToNone,
        _XTRABACKUP_ONLY,
        Ui(label="Number of backup copies", section="XtraBackup"),
    ] = None
    xtrabackup_kill_queries: Annotated[
        bool, Ui(label="Kill blocking queries", section="XtraBackup")
    ] = False
    xtrabackup_kill_queries_timeout: Annotated[
        int | EmptyStrToNone,
        _XTRABACKUP_ONLY,
        Ui(label="Kill-queries timeout (s)", section="XtraBackup"),
    ] = None
    xtrabackup_kill_query_type: Annotated[
        Literal["select", "all"] | EmptyStrToNone,
        _XTRABACKUP_ONLY,
        Choices((("select", "SELECT"), ("all", "All"))),
        Ui(label="Kill query type", section="XtraBackup"),
    ] = None
    xtrabackup_verify: Annotated[
        bool, Ui(label="Verify after backup", section="XtraBackup")
    ] = False
    xtrabackup_prepare: Annotated[
        bool, Ui(label="Prepare for restore", section="XtraBackup")
    ] = False
    xtrabackup_prepare_memory: Annotated[
        NonEmptyStr | EmptyStrToNone,
        _XTRABACKUP_ONLY,
        Ui(label="Prepare memory", section="XtraBackup"),
    ] = None
    xtrabackup_desync_pxc: Annotated[
        bool, Ui(label="Desync PXC node", section="XtraBackup")
    ] = False
    xtrabackup_rsync: Annotated[bool, Ui(label="Use rsync", section="XtraBackup")] = (
        False
    )
    xtrabackup_replica_info: Annotated[
        bool, Ui(label="Include replica info", section="XtraBackup")
    ] = False
    xtrabackup_defaults_file: Annotated[
        NonEmptyStr | EmptyStrToNone,
        _XTRABACKUP_ONLY,
        Ui(label="XtraBackup defaults file", section="XtraBackup"),
    ] = None
    xtrabackup_extra_args: Annotated[
        NonEmptyStr | EmptyStrToNone,
        _XTRABACKUP_ONLY,
        Ui(label="Extra args", section="XtraBackup"),
    ] = None
    xtrabackup_incremental_method: Annotated[
        Literal["less_space", "fast_restore"] | EmptyStrToNone,
        _XTRABACKUP_ONLY,
        Choices((("less_space", "Less space"), ("fast_restore", "Fast restore"))),
        Ui(label="Incremental method", section="XtraBackup"),
    ] = None
    # Vocabulary duplicated -- see the note on BackupConfigAll.xtrabackup_incremental_cycle.
    xtrabackup_incremental_cycle: Annotated[
        Literal["daily", "weekly", "1", "2", "3", "4", "5", "6", "7"] | EmptyStrToNone,
        _XTRABACKUP_ONLY,
        Choices(
            (
                ("daily", "Daily"),
                ("weekly", "Weekly (Monday)"),
                ("1", "Monday"),
                ("2", "Tuesday"),
                ("3", "Wednesday"),
                ("4", "Thursday"),
                ("5", "Friday"),
                ("6", "Saturday"),
                ("7", "Sunday"),
            )
        ),
        Ui(
            label="Incremental cycle",
            section="XtraBackup",
            description=(
                "``daily``, ``weekly``, or an ISO weekday number (1-7, "
                "Monday-Sunday) controlling when the FULL backup runs. Applies to "
                "the ``less_space`` incremental method only."
            ),
        ),
    ] = None
    xtrabackup_local_ssh_destination: Annotated[
        NonEmptyStr | EmptyStrToNone,
        _XTRABACKUP_ONLY,
        Ui(label="Local SSH destination", section="XtraBackup"),
    ] = None
    xtrabackup_stop_replica: Annotated[
        bool,
        Ui(
            label="Safe replica backup",
            section="XtraBackup",
            description=(
                "Passes --safe-slave-backup so xtrabackup pauses the replica "
                "SQL thread during the backup (required for --slave-info on a "
                "multi-threaded replica with GTID off)."
            ),
        ),
    ] = False
    xtrabackup_lock_ddl: Annotated[bool, Ui(label="Lock DDL", section="XtraBackup")] = (
        False
    )
    xtrabackup_quiet: Annotated[
        bool, Ui(label="Quiet log (drop per-file copy lines)", section="XtraBackup")
    ] = False
    xtrabackup_bin_cmd: Annotated[
        Literal["xtrabackup", "mariadb-backup", "innobackupex"] | EmptyStrToNone,
        _XTRABACKUP_ONLY,
        Ui(label="Backup binary", section="XtraBackup"),
    ] = None

    binlog_prefix: Annotated[
        NonEmptyStr | EmptyStrToNone,
        _BINLOG_ONLY,
        Ui(label="Binlog prefix", section="Binlog"),
    ] = None
    binlog_purge_days: Annotated[
        int | EmptyStrToNone,
        _BINLOG_ONLY,
        Ui(label="Purge after (days)", section="Binlog"),
    ] = None
    binlog_extra_args: Annotated[
        NonEmptyStr | EmptyStrToNone,
        _BINLOG_ONLY,
        Ui(label="Extra args", section="Binlog"),
    ] = None
    binlog_compress_cmd: Annotated[
        NonEmptyStr | EmptyStrToNone,
        _BINLOG_ONLY,
        Ui(label="Compress command", section="Binlog"),
    ] = None
    binlog_cmd: Annotated[
        NonEmptyStr | EmptyStrToNone,
        _BINLOG_ONLY,
        Ui(label="Binlog command", section="Binlog"),
    ] = None
    binlog_run_all: Annotated[
        bool, Ui(label="Run all binlog backups", section="Binlog")
    ] = True
    binlog_alternative_host: Annotated[
        NonEmptyStr | EmptyStrToNone,
        _BINLOG_ONLY,
        Ui(label="Alternative binlog host", section="Binlog"),
    ] = None

    encryption_format: Annotated[
        EncryptionFormat,
        Choices(
            (
                (EncryptionFormat.NONE, "No encryption"),
                (EncryptionFormat.GPG, "GPG"),
                (EncryptionFormat.AES256, "AES-256 (XtraBackup only)"),
                (EncryptionFormat.DUAL, "AES-256 + GPG (XtraBackup only)"),
            )
        ),
        Ui(
            label="Encryption format",
            section="Encryption",
            description=(
                "Which encryption this task applies. 'GPG' needs a recipient and "
                "a timing below: 'Encrypt backup' encrypts in place as part of an "
                "upload, so it needs an upload target, while 'Encrypt after backup "
                "completes' encrypts on the host. 'AES-256' and 'AES-256 + GPG' "
                "need a key file and are XtraBackup-only. 'AES-256 + GPG' selects "
                "XtraBackup's built-in AES-256 and skips the GPG pass, which the "
                "backend cannot apply on top of it."
            ),
        ),
    ] = EncryptionFormat.NONE
    xtrabackup_aes256_keyfile: Annotated[
        NonEmptyStr | EmptyStrToNone,
        _XTRABACKUP_ONLY,
        Requires(
            when=_FMT_HAS_AES,
            message=(
                "'xtrabackup_aes256_keyfile' is required when 'encryption_format' "
                "includes AES-256."
            ),
        ),
        Forbidden(
            when=not_(_FMT_HAS_AES),
            message=(
                "'xtrabackup_aes256_keyfile' must not be set when "
                "'encryption_format' does not include AES-256."
            ),
        ),
        Ui(label="AES-256 key file path", section="Encryption"),
    ] = None
    encrypt: Annotated[
        bool,
        Ui(
            label="Encrypt backup",
            section="Encryption",
            description=(
                "GPG-encrypt the backup in place as part of an upload, so it "
                "needs an upload target. Combine with 'Encrypt using tmpdir', or "
                "use 'Encrypt after backup completes' to encrypt on the host "
                "instead. Needs a GPG 'Encryption format' and a recipient."
            ),
        ),
    ] = False
    encrypt_using_tmpdir: Annotated[
        bool,
        Forbidden(
            when=falsy("encrypt"),
            message="'encrypt_using_tmpdir' requires 'encrypt' to be enabled.",
        ),
        Forbidden(
            when=truthy("post_run_encrypt"),
            message=(
                "'encrypt_using_tmpdir' cannot be combined with 'post_run_encrypt'."
            ),
        ),
        Ui(
            label="Encrypt using tmpdir",
            section="Encryption",
            description=(
                "Encrypt in a temporary directory during the backup. Requires "
                "'Encrypt backup'; mutually exclusive with 'Encrypt after backup "
                "completes'."
            ),
        ),
    ] = False
    post_run_encrypt: Annotated[
        bool,
        Ui(
            label="Encrypt after backup completes",
            section="Encryption",
            description=(
                "GPG-encrypt the finished backup once it completes. Independent of "
                "'Encrypt backup'; mutually exclusive with 'Encrypt using tmpdir'. "
                "Needs a GPG 'Encryption format' and a recipient. Mydumper and "
                "XtraBackup encrypt on the host; a Binlog backup encrypts only "
                "during an upload, so it also needs an upload target."
            ),
        ),
    ] = False
    encryption_recipient: Annotated[
        NonEmptyStr | EmptyStrToNone,
        Requires(
            when=AnyTruthy(_GPG_TIMING_FIELDS),
            message=(
                "'encryption_recipient' is required when 'encrypt' or "
                "'post_run_encrypt' is enabled."
            ),
        ),
        Forbidden(
            when=AllFalsy(_GPG_TIMING_FIELDS),
            message=(
                "'encryption_recipient' must not be set when no encryption mode is "
                "enabled."
            ),
        ),
        Ui(
            label="Encryption recipient",
            section="Encryption",
            description=(
                "GPG recipient/key the backup is encrypted for. Required when "
                "either GPG timing is enabled."
            ),
        ),
    ] = None

    upload: Annotated[
        list[UploadProvider],
        Choices(
            (
                (_UPLOAD_RSYNC, "Rsync"),
                (_UPLOAD_S3, "S3"),
                (_UPLOAD_GSUTIL, "Google Cloud Storage"),
            )
        ),
        Ui(label="Upload providers", section="Upload"),
    ] = Field(default_factory=list)
    s3_bucket: Annotated[
        NonEmptyStr | EmptyStrToNone, _S3_ONLY, Ui(label="S3 bucket", section="Upload")
    ] = None
    s3_storage_class: Annotated[
        NonEmptyStr | EmptyStrToNone,
        _S3_ONLY,
        Ui(label="S3 storage class", section="Upload"),
    ] = None
    skip_s3_safety_check: Annotated[
        bool, _S3_ONLY, Ui(label="Skip S3 safety check", section="Upload")
    ] = False
    upload_quiet: Annotated[bool, Ui(label="Quiet upload logs", section="Upload")] = (
        False
    )
    awscli_s3_upload_extra_args: Annotated[
        NonEmptyStr | EmptyStrToNone,
        _S3_ONLY,
        Ui(label="AWS S3 upload extra args", section="Upload"),
    ] = None
    gs_bucket: Annotated[
        NonEmptyStr | EmptyStrToNone,
        _GSUTIL_ONLY,
        Ui(label="Google Cloud Storage bucket", section="Upload"),
    ] = None
    rsync_path: Annotated[
        NonEmptyStr | EmptyStrToNone,
        _RSYNC_ONLY,
        Ui(label="Rsync destination path", section="Upload"),
    ] = None

    @field_validator("encryption_format", mode="before")
    @classmethod
    def _normalize_encryption_format(cls, value: Any) -> Any:
        """Normalise an omitted ``encryption_format`` to "no encryption".

        A client that leaves the field empty sends ``""``, which means it picked
        nothing — the same state as the default. Left uncoerced it fails the enum
        instead, rejecting a request that selected no encryption.

        :param value: The raw ``encryption_format`` input before validation.
        :return: The normalised value passed on to enum validation.
        """
        if value is None or value == "":
            return EncryptionFormat.NONE
        return value

    @field_validator("upload", mode="before")
    @classmethod
    def _normalize_upload_input(cls, value: Any) -> Any:
        """Normalise scalar ``upload`` input from legacy form callers.

        A bare string is wrapped (``"S3"`` -> ``["S3"]``); an empty string
        becomes ``[]``. ``upload`` is optional, so an empty selection is a
        valid "no upload" config.

        :param value: The raw ``upload`` input before validation.
        :return: The normalised value passed on to list validation.
        """
        if isinstance(value, str):
            if not value:
                return []
            return [value]
        return value

    @model_validator(mode="after")
    def validate_upload_provider_consistency(self) -> Self:
        """Enforce bidirectional consistency between ``upload`` and provider fields.

        ``upload`` is optional and may be empty. Each provider must appear in
        ``upload`` iff its destination field is set: a destination without its
        provider fails, and a selected provider with an empty destination
        fails. S3 auxiliary fields likewise require ``S3`` in ``upload`` (the
        schema's ``forbidden=`` gates cannot express this symmetrically because
        boolean defaults trip the rule).

        :return: The validated instance.
        :raises ValueError: When a provider's destination field disagrees
            with the ``upload`` list, or when S3 auxiliary fields are set
            without ``S3`` in ``upload``.
        """
        selected = set(self.upload)
        pairs = (
            (UploadProvider.S3, self.s3_bucket),
            (UploadProvider.GSUTIL, self.gs_bucket),
            (UploadProvider.RSYNC, self.rsync_path),
        )
        for provider, value in pairs:
            present = bool(value)
            in_list = provider in selected
            if present and not in_list:
                raise ValueError(
                    f"{provider.name} destination field set but {provider.name!r} "
                    "is not in the upload list."
                )
            if in_list and not present:
                raise ValueError(
                    f"{provider.name!r} selected in upload but its destination "
                    "field is empty."
                )
        s3_aux = (
            self.s3_storage_class
            or self.skip_s3_safety_check
            or self.awscli_s3_upload_extra_args
        )
        if s3_aux and UploadProvider.S3 not in selected:
            raise ValueError(
                "S3 auxiliary fields set but 'S3' is not in the upload list."
            )
        return self

    @model_validator(mode="after")
    def validate_encryption_format(self) -> Self:
        """Validate the encryption format against the selected backup type.

        Expressed as a validator rather than a conditional ``Choices`` set because
        the DSL's option list is static: the AES-bearing formats stay published and
        are rejected here for the engines that have no AES-256 path.

        :return: The validated instance.
        :raises ValueError: If the format is not valid for the backup type.
        """
        allowed_formats = ALLOWED_ENCRYPTION_FORMATS.get(self.backup_type, [])
        if self.encryption_format not in allowed_formats:
            raise ValueError(
                f"Invalid encryption_format {self.encryption_format.value!r} for "
                f"{self.backup_type.name} backup. Options are "
                f"{[fmt.value for fmt in allowed_formats]}"
            )

        return self

    @model_validator(mode="after")
    def validate_compression_algorithm(self) -> Self:
        """Validate that the compression_algorithm is compatible with the selected backup_type.

        :return: The validated instance
        :rtype: Self
        :raises ValueError: If the compression_algorithm is not valid for the specified backup_type.
        """
        allowed_algorithms = ALLOWED_COMPRESSIONS.get(self.backup_type, [])
        if (
            self.compression_algorithm is not None
            and self.compression_algorithm not in allowed_algorithms
        ):
            raise ValueError(
                f"Invalid compression algorithm "
                f"{self.compression_algorithm.value!r} for "
                f"{self.backup_type.name} backup. Options are "
                f"{[algorithm.value for algorithm in allowed_algorithms]}"
            )

        return self


class BackupConfigServer(BaseCaseInsensitiveModel):
    """Represent an individual server configuration.

    :param alias: A unique alias for the server.
    :type alias: NonEmptyStr
    :param backup_type: The type of the backup.
    :type backup_type: BackupType
    :param host: The hostname or address of the server.
    :type host: NonEmptyStr
    :param port: The port number used to connect to the host.
    :type port: int | None
    :param upload: A unique list of upload providers to use for the backup, if any.
    :type upload: UniqueList[UploadProvider] | None
    :param dir_encrypt_config: Specific configuration for the backup encryption.
    :type dir_encrypt_config: DirEncryptConfig | None
    """

    alias: NonEmptyStr
    backup_type: str
    host: NonEmptyStr
    port: int | None
    upload: list[str] | None = None
    dir_encrypt_config: DirEncryptConfig | None = None


class BackupConfig(BaseCaseInsensitiveModel):
    """Represent the overall backup configuration.

    :param all_servers: General settings for the backup.
    :type all_servers: BackupConfigAll
    :param server_list: A list of backup configuration for each server.
    :type server_list: list[BackupConfigServer]
    """

    all_servers: BackupConfigAll
    server_list: list[BackupConfigServer]


class BackupTaskResponse(BackupTaskBase):
    """Represent a backup task API response.

    :param backup_type: The backup type recorded in task config.
    """

    backup_type: BackupType | None = None
