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

"""Conditional-rule gating tests for ``BackupCreate``."""

import pytest
from pydantic import ValidationError

from app.sep.apps.framework.form_dsl.derivation import derive_form_sections
from app.sep.apps.mysql_backups.forms import (
    BackupConfigAll,
    BackupCreate,
    EncryptionFormat,
    UploadProvider,
)
from app.sep.apps.mysql_backups.models import BackupType
from app.sep.apps.mysql_backups.views import mysql_backups_views


def _base_payload(backup_type: BackupType, **overrides) -> dict:
    """Build a minimal valid ``BackupCreate`` kwargs dict.

    ``upload`` is optional (an empty list is accepted); the default pair
    (S3 + ``s3_bucket``) keeps the bidirectional provider-consistency
    validator happy so each test can override ``upload`` / bucket fields
    only when that is the assertion under test.
    """
    payload = {
        "task_name": "task1",
        "hostname": "host1",
        "service_id": 1,
        "backup_type": backup_type,
        "upload": [UploadProvider.S3],
        "s3_bucket": "default-bucket",
    }
    payload.update(overrides)
    return payload


class TestPerModeGates:
    """Each mode rejects fields belonging to other modes."""

    def test_mydumper_happy_path(self):
        """``backup_type=M`` with only mydumper fields validates."""
        BackupCreate(**_base_payload(BackupType.MYDUMPER, mydumper_extra_args="--foo"))

    def test_xtrabackup_happy_path(self):
        """``backup_type=X`` with only xtrabackup fields validates."""
        BackupCreate(
            **_base_payload(BackupType.XTRABACKUP, xtrabackup_extra_args="--foo")
        )

    def test_binlog_happy_path(self):
        """``backup_type=B`` with only binlog fields validates."""
        BackupCreate(**_base_payload(BackupType.BINLOG, binlog_prefix="bp"))

    def test_mydumper_rejects_xtrabackup_field(self):
        """xtrabackup_* fields are forbidden when backup_type=M."""
        with pytest.raises(ValidationError, match="xtrabackup_extra_args"):
            BackupCreate(
                **_base_payload(BackupType.MYDUMPER, xtrabackup_extra_args="--foo")
            )

    def test_mydumper_rejects_binlog_field(self):
        """binlog_* fields are forbidden when backup_type=M."""
        with pytest.raises(ValidationError, match="binlog_prefix"):
            BackupCreate(**_base_payload(BackupType.MYDUMPER, binlog_prefix="bp"))

    def test_xtrabackup_rejects_mydumper_field(self):
        """mydumper_* fields are forbidden when backup_type=X."""
        with pytest.raises(ValidationError, match="mydumper_extra_args"):
            BackupCreate(
                **_base_payload(BackupType.XTRABACKUP, mydumper_extra_args="--x")
            )

    def test_xtrabackup_rejects_binlog_field(self):
        """binlog_* fields are forbidden when backup_type=X."""
        with pytest.raises(ValidationError, match="binlog_prefix"):
            BackupCreate(**_base_payload(BackupType.XTRABACKUP, binlog_prefix="bp"))

    def test_binlog_rejects_xtrabackup_field(self):
        """xtrabackup_* fields are forbidden when backup_type=B."""
        with pytest.raises(ValidationError, match="xtrabackup_extra_args"):
            BackupCreate(
                **_base_payload(BackupType.BINLOG, xtrabackup_extra_args="--x")
            )

    def test_binlog_rejects_mydumper_field(self):
        """mydumper_* fields are forbidden when backup_type=B."""
        with pytest.raises(ValidationError, match="mydumper_extra_args"):
            BackupCreate(**_base_payload(BackupType.BINLOG, mydumper_extra_args="--x"))


class TestPerModeBoolGates:
    """Truthy boolean fields from a wrong mode are rejected."""

    def test_mydumper_rejects_xtrabackup_bool(self):
        """xtrabackup_verify=True with backup_type=M → 422."""
        with pytest.raises(ValidationError, match="xtrabackup_verify"):
            BackupCreate(**_base_payload(BackupType.MYDUMPER, xtrabackup_verify=True))

    def test_mydumper_rejects_xtrabackup_prepare(self):
        """xtrabackup_prepare=True with backup_type=M → 422."""
        with pytest.raises(ValidationError, match="xtrabackup_prepare"):
            BackupCreate(**_base_payload(BackupType.MYDUMPER, xtrabackup_prepare=True))

    def test_xtrabackup_rejects_mydumper_bool(self):
        """mydumper_dump_triggers=True with backup_type=X → 422."""
        with pytest.raises(ValidationError, match="mydumper_dump_triggers"):
            BackupCreate(
                **_base_payload(BackupType.XTRABACKUP, mydumper_dump_triggers=True)
            )

    def test_binlog_rejects_mydumper_bool(self):
        """mydumper_use_numa=True with backup_type=B → 422."""
        with pytest.raises(ValidationError, match="mydumper_use_numa"):
            BackupCreate(**_base_payload(BackupType.BINLOG, mydumper_use_numa=True))

    def test_default_false_bools_allowed_cross_mode(self):
        """Default-False bools cross-mode is the common path and validates."""
        BackupCreate(
            **_base_payload(
                BackupType.MYDUMPER,
                xtrabackup_verify=False,
                xtrabackup_prepare=False,
            )
        )


class TestEncryptionGate:
    """Enforce the independent-modes encryption model within the GPG formats.

    ``encrypt`` (in-place) and ``post_run_encrypt`` are independent timings;
    ``encrypt_using_tmpdir`` requires ``encrypt`` and is mutually exclusive with
    ``post_run_encrypt``; and ``encryption_recipient`` is required iff either
    timing is enabled. Every case here selects a GPG-bearing
    ``encryption_format``, which is what makes the timing fields reachable.
    """

    def test_defaults_yield_valid_disabled_config(self):
        """Accept an untouched Encryption section (all defaults) as a disabled config."""
        form = BackupCreate(**_base_payload(BackupType.MYDUMPER))
        assert form.encryption_format is EncryptionFormat.NONE
        assert form.encrypt is False
        assert form.encrypt_using_tmpdir is False
        assert form.post_run_encrypt is False
        assert form.encryption_recipient is None

    def test_encrypt_with_recipient_ok(self):
        """encrypt=True + recipient validates."""
        BackupCreate(
            **_base_payload(
                BackupType.MYDUMPER,
                encryption_format=EncryptionFormat.GPG,
                encrypt=True,
                encryption_recipient="ops@example.com",
            )
        )

    def test_encrypt_without_recipient_fails(self):
        """encrypt=True without recipient → 422."""
        with pytest.raises(ValidationError, match="encryption_recipient"):
            BackupCreate(
                **_base_payload(
                    BackupType.MYDUMPER,
                    encryption_format=EncryptionFormat.GPG,
                    encrypt=True,
                )
            )

    def test_recipient_without_any_encryption_fails(self):
        """Reject a recipient set with no encryption timing enabled → 422."""
        with pytest.raises(ValidationError, match="encryption_recipient"):
            BackupCreate(
                **_base_payload(
                    BackupType.MYDUMPER,
                    encrypt=False,
                    encryption_recipient="ops@example.com",
                )
            )

    def test_tmpdir_with_encrypt_ok(self):
        """Accept encrypt with encrypt_using_tmpdir and a recipient (tmpdir timing)."""
        BackupCreate(
            **_base_payload(
                BackupType.MYDUMPER,
                encryption_format=EncryptionFormat.GPG,
                encrypt=True,
                encrypt_using_tmpdir=True,
                encryption_recipient="ops@example.com",
            )
        )

    def test_post_run_with_encrypt_ok(self):
        """Accept encrypt with post_run_encrypt and a recipient (both timings)."""
        BackupCreate(
            **_base_payload(
                BackupType.MYDUMPER,
                encryption_format=EncryptionFormat.GPG,
                encrypt=True,
                post_run_encrypt=True,
                encryption_recipient="ops@example.com",
            )
        )

    def test_tmpdir_without_encrypt_fails(self):
        """Reject encrypt_using_tmpdir when encrypt is off."""
        with pytest.raises(ValidationError, match="encrypt_using_tmpdir"):
            BackupCreate(
                **_base_payload(BackupType.MYDUMPER, encrypt_using_tmpdir=True)
            )

    def test_post_run_without_encrypt_ok(self):
        """Accept post_run_encrypt with a recipient but no in-place encrypt.

        Post-run encryption produces an encrypted backup on its own, so it must
        not depend on the in-place ``encrypt`` toggle.
        """
        BackupCreate(
            **_base_payload(
                BackupType.MYDUMPER,
                encryption_format=EncryptionFormat.GPG,
                encrypt=False,
                post_run_encrypt=True,
                encryption_recipient="ops@example.com",
            )
        )

    def test_post_run_without_recipient_fails(self):
        """Reject post_run_encrypt without a recipient (post-run GPG needs one)."""
        with pytest.raises(ValidationError, match="encryption_recipient"):
            BackupCreate(
                **_base_payload(
                    BackupType.MYDUMPER,
                    encryption_format=EncryptionFormat.GPG,
                    post_run_encrypt=True,
                )
            )

    def test_tmpdir_and_post_run_together_fails(self):
        """Reject encrypt_using_tmpdir combined with post_run_encrypt."""
        with pytest.raises(ValidationError, match="encrypt_using_tmpdir"):
            BackupCreate(
                **_base_payload(
                    BackupType.MYDUMPER,
                    encryption_format=EncryptionFormat.GPG,
                    encrypt=True,
                    encrypt_using_tmpdir=True,
                    post_run_encrypt=True,
                    encryption_recipient="ops@example.com",
                )
            )


class TestEncryptionFormatGate:
    """``encryption_format`` decides which encryption runs, not field presence.

    The format is the signal; the key file and the GPG timing bools are its
    format-specific parameters and are unreachable outside their format.
    """

    @pytest.mark.parametrize(
        ("override", "rejected_field"),
        [
            (
                {"encrypt": True, "encryption_recipient": "ops@example.com"},
                "encrypt",
            ),
            (
                {"post_run_encrypt": True, "encryption_recipient": "ops@example.com"},
                "post_run_encrypt",
            ),
            (
                {"xtrabackup_aes256_keyfile": "/etc/keyfile"},
                "xtrabackup_aes256_keyfile",
            ),
        ],
    )
    def test_none_leaves_every_encryption_field_unreachable(
        self, override: dict[str, object], rejected_field: str
    ):
        """Reject each encryption parameter under the default ``none`` format."""
        with pytest.raises(ValidationError, match=rejected_field):
            BackupCreate(**_base_payload(BackupType.XTRABACKUP, **override))

    @pytest.mark.parametrize("timing", ["encrypt", "post_run_encrypt"])
    def test_gpg_accepts_either_timing(self, timing: str):
        """Accept ``gpg`` with in-place or post-run timing (both are GPG modes)."""
        BackupCreate(
            **_base_payload(
                BackupType.XTRABACKUP,
                encryption_format=EncryptionFormat.GPG,
                encryption_recipient="ops@example.com",
                **{timing: True},
            )
        )

    def test_gpg_without_a_timing_fails(self):
        """Reject ``gpg`` with neither timing selected — nothing would encrypt."""
        with pytest.raises(ValidationError, match="encrypt"):
            BackupCreate(
                **_base_payload(
                    BackupType.XTRABACKUP, encryption_format=EncryptionFormat.GPG
                )
            )

    def test_gpg_forbids_the_key_file(self):
        """Reject a key file under ``gpg`` — a stale one must not reach the backend."""
        with pytest.raises(ValidationError, match="xtrabackup_aes256_keyfile"):
            BackupCreate(
                **_base_payload(
                    BackupType.XTRABACKUP,
                    encryption_format=EncryptionFormat.GPG,
                    encrypt=True,
                    encryption_recipient="ops@example.com",
                    xtrabackup_aes256_keyfile="/etc/keyfile",
                )
            )

    def test_aes256_requires_the_key_file(self):
        """Reject ``aes256`` without a key file."""
        with pytest.raises(ValidationError, match="xtrabackup_aes256_keyfile"):
            BackupCreate(
                **_base_payload(
                    BackupType.XTRABACKUP, encryption_format=EncryptionFormat.AES256
                )
            )

    def test_aes256_with_the_key_file_ok(self):
        """Accept ``aes256`` with a key file and no GPG timing."""
        BackupCreate(
            **_base_payload(
                BackupType.XTRABACKUP,
                encryption_format=EncryptionFormat.AES256,
                xtrabackup_aes256_keyfile="/etc/keyfile",
            )
        )

    def test_aes256_forbids_a_gpg_timing(self):
        """Reject a GPG timing under ``aes256`` — a stale flag must not run GPG."""
        with pytest.raises(ValidationError, match="post_run_encrypt"):
            BackupCreate(
                **_base_payload(
                    BackupType.XTRABACKUP,
                    encryption_format=EncryptionFormat.AES256,
                    xtrabackup_aes256_keyfile="/etc/keyfile",
                    post_run_encrypt=True,
                    encryption_recipient="ops@example.com",
                )
            )

    def test_dual_requires_the_key_file(self):
        """Reject ``dual`` with a GPG timing but no key file."""
        with pytest.raises(ValidationError, match="xtrabackup_aes256_keyfile"):
            BackupCreate(
                **_base_payload(
                    BackupType.XTRABACKUP,
                    encryption_format=EncryptionFormat.DUAL,
                    post_run_encrypt=True,
                    encryption_recipient="ops@example.com",
                )
            )

    def test_dual_requires_a_gpg_timing(self):
        """Reject ``dual`` with a key file but neither GPG timing."""
        with pytest.raises(ValidationError, match="encrypt"):
            BackupCreate(
                **_base_payload(
                    BackupType.XTRABACKUP,
                    encryption_format=EncryptionFormat.DUAL,
                    xtrabackup_aes256_keyfile="/etc/keyfile",
                )
            )

    def test_dual_with_both_halves_ok(self):
        """Accept ``dual`` with a key file and a GPG timing."""
        BackupCreate(
            **_base_payload(
                BackupType.XTRABACKUP,
                encryption_format=EncryptionFormat.DUAL,
                xtrabackup_aes256_keyfile="/etc/keyfile",
                post_run_encrypt=True,
                encryption_recipient="ops@example.com",
            )
        )

    @pytest.mark.parametrize("backup_type", [BackupType.MYDUMPER, BackupType.BINLOG])
    @pytest.mark.parametrize(
        "encryption_format", [EncryptionFormat.AES256, EncryptionFormat.DUAL]
    )
    def test_aes_formats_rejected_outside_xtrabackup(
        self, backup_type, encryption_format
    ):
        """Reject the AES-bearing formats for backup types with no AES-256 path."""
        with pytest.raises(ValidationError, match="encryption_format"):
            BackupCreate(
                **_base_payload(backup_type, encryption_format=encryption_format)
            )

    @pytest.mark.parametrize(
        "backup_type", [BackupType.MYDUMPER, BackupType.XTRABACKUP, BackupType.BINLOG]
    )
    def test_gpg_allowed_for_every_backup_type(self, backup_type):
        """Accept ``gpg`` for every backup type — GPG is engine-independent."""
        BackupCreate(
            **_base_payload(
                backup_type,
                encryption_format=EncryptionFormat.GPG,
                post_run_encrypt=True,
                encryption_recipient="ops@example.com",
            )
        )

    def test_empty_string_coerces_to_none(self):
        """Treat an unselected ``<select>`` (posting ``""``) as ``none``."""
        form = BackupCreate(
            **_base_payload(BackupType.XTRABACKUP, encryption_format="")
        )
        assert form.encryption_format is EncryptionFormat.NONE


class TestUploadProviderGate:
    """``upload`` MultiChoice must agree with provider-specific destination fields."""

    def test_s3_bucket_without_s3_in_upload_fails(self):
        """``s3_bucket`` set with ``S3`` absent from ``upload`` → 422.

        The schema-level ``forbidden`` gate (Contains predicate) fires first;
        the bidirectional model validator covers the same case as a backstop.
        """
        with pytest.raises(ValidationError, match="s3_bucket"):
            BackupCreate(
                **_base_payload(
                    BackupType.MYDUMPER,
                    upload=[UploadProvider.RSYNC],
                    rsync_path="/r",
                    s3_bucket="bkt",
                )
            )

    def test_s3_in_upload_without_bucket_fails(self):
        """``S3`` in ``upload`` with empty ``s3_bucket`` → 422."""
        with pytest.raises(ValidationError, match="S3"):
            BackupCreate(
                **_base_payload(
                    BackupType.MYDUMPER,
                    upload=[UploadProvider.S3],
                    s3_bucket=None,
                )
            )

    def test_gcs_in_upload_without_bucket_fails(self):
        """``GSUTIL`` in ``upload`` with empty ``gs_bucket`` → 422."""
        with pytest.raises(ValidationError, match="GSUTIL"):
            BackupCreate(
                **_base_payload(
                    BackupType.MYDUMPER,
                    upload=[UploadProvider.GSUTIL],
                    s3_bucket=None,
                )
            )

    def test_rsync_in_upload_without_path_fails(self):
        """``RSYNC`` in ``upload`` with empty ``rsync_path`` → 422."""
        with pytest.raises(ValidationError, match="RSYNC"):
            BackupCreate(
                **_base_payload(
                    BackupType.MYDUMPER,
                    upload=[UploadProvider.RSYNC],
                    s3_bucket=None,
                )
            )

    def test_s3_auxiliary_without_s3_fails(self):
        """``s3_storage_class`` etc. without ``S3`` in upload → 422.

        The schema-level ``forbidden`` gate on ``s3_storage_class`` fires
        before the model validator's ``auxiliary`` check; either error is
        a valid 422 surface for the same contract.
        """
        with pytest.raises(ValidationError, match="s3_storage_class"):
            BackupCreate(
                **_base_payload(
                    BackupType.MYDUMPER,
                    upload=[UploadProvider.RSYNC],
                    rsync_path="/r",
                    s3_bucket=None,
                    s3_storage_class="STANDARD",
                )
            )

    def test_s3_bool_auxiliary_without_s3_fails(self):
        """Reject ``skip_s3_safety_check=True`` without ``S3`` in upload → 422.

        A *truthy* bool is "present", so its ``_S3_ONLY`` schema ``forbidden``
        gate fires (only the ``False`` default is treated as absent); the model
        validator's ``s3_aux`` branch is the backstop for the same contract.
        """
        with pytest.raises(ValidationError, match="skip_s3_safety_check"):
            BackupCreate(
                **_base_payload(
                    BackupType.MYDUMPER,
                    upload=[],
                    s3_bucket=None,
                    skip_s3_safety_check=True,
                )
            )

    def test_multi_provider_happy_path(self):
        """All providers selected with matching destinations validates."""
        BackupCreate(
            **_base_payload(
                BackupType.MYDUMPER,
                upload=[UploadProvider.S3, UploadProvider.RSYNC],
                s3_bucket="bkt",
                rsync_path="/r",
            )
        )

    def test_empty_upload_list_accepted(self):
        """Accept ``upload=[]``: uploading a backup off-host is optional."""
        model = BackupCreate(
            **_base_payload(BackupType.MYDUMPER, upload=[], s3_bucket=None)
        )
        assert model.upload == []

    def test_missing_upload_defaults_empty(self):
        """Default ``upload`` to ``[]`` when a payload omits it (optional)."""
        payload = _base_payload(BackupType.MYDUMPER)
        payload.pop("upload")
        payload.pop("s3_bucket")
        model = BackupCreate(**payload)
        assert model.upload == []

    def test_empty_upload_with_destination_set_fails(self):
        """Reject ``upload=[]`` when a destination field is set → 422.

        Regression guard on the reverse-pairing branch: relaxing the
        ``upload`` requirement must not let a stray destination (e.g.
        ``s3_bucket``) slip through without its provider selected.
        """
        with pytest.raises(ValidationError, match="s3_bucket|S3"):
            BackupCreate(
                **_base_payload(BackupType.MYDUMPER, upload=[], s3_bucket="bkt")
            )

    def test_empty_upload_with_gs_bucket_set_fails(self):
        """Reject ``upload=[]`` when ``gs_bucket`` is set → 422 (reverse-pair, GSUTIL).

        The schema ``forbidden`` gate on ``gs_bucket`` fires first; the model
        validator's reverse-pair branch is the backstop for the same contract.
        """
        with pytest.raises(ValidationError, match="gs_bucket|GSUTIL"):
            BackupCreate(
                **_base_payload(
                    BackupType.MYDUMPER, upload=[], s3_bucket=None, gs_bucket="g"
                )
            )

    def test_empty_upload_with_rsync_path_set_fails(self):
        """Reject ``upload=[]`` when ``rsync_path`` is set → 422 (reverse-pair, RSYNC)."""
        with pytest.raises(ValidationError, match="rsync_path|RSYNC"):
            BackupCreate(
                **_base_payload(
                    BackupType.MYDUMPER, upload=[], s3_bucket=None, rsync_path="/r"
                )
            )


class TestUploadInputNormalization:
    """Coerce legacy scalar form values to a list via ``_normalize_upload_input``."""

    def test_scalar_string_is_wrapped(self):
        """Wrap a bare provider string from a legacy form into a list."""
        model = BackupCreate(
            **_base_payload(BackupType.MYDUMPER, upload="S3", s3_bucket="bkt")
        )
        assert model.upload == [UploadProvider.S3]

    def test_empty_string_becomes_empty_list(self):
        """Coerce an empty-string ``upload`` to ``[]`` (a valid "no upload")."""
        model = BackupCreate(
            **_base_payload(BackupType.MYDUMPER, upload="", s3_bucket=None)
        )
        assert model.upload == []


class TestCompressionAlgorithmValidator:
    """The existing per-mode compression-algorithm validator stays."""

    def test_binlog_rejects_lz4(self):
        """compression_algorithm=lz4 is invalid for B (B allows only gzip)."""
        with pytest.raises(ValidationError, match="compression algorithm"):
            BackupCreate(
                **_base_payload(BackupType.BINLOG, compression_algorithm="lz4")
            )

    def test_binlog_accepts_gzip(self):
        """compression_algorithm=gzip is valid for B."""
        BackupCreate(**_base_payload(BackupType.BINLOG, compression_algorithm="gzip"))


class TestMydumperVerbose:
    """``mydumper_verbose`` accepts only valid integer levels and is gated to mydumper mode."""

    WARNINGS_LEVEL = 2  # mydumper --verbose=2 (warnings)

    def test_accepts_int_level(self):
        """A valid integer level validates and is stored as an int."""
        backup = BackupCreate(
            **_base_payload(BackupType.MYDUMPER, mydumper_verbose=self.WARNINGS_LEVEL)
        )
        assert backup.mydumper_verbose == self.WARNINGS_LEVEL

    def test_accepts_numeric_string(self):
        """A numeric form string coerces to the equivalent int (Pydantic)."""
        backup = BackupCreate(
            **_base_payload(BackupType.MYDUMPER, mydumper_verbose="2")
        )
        assert backup.mydumper_verbose == self.WARNINGS_LEVEL

    def test_blank_is_none(self):
        """An empty form value coerces to None (EmptyStrToNone)."""
        backup = BackupCreate(**_base_payload(BackupType.MYDUMPER, mydumper_verbose=""))
        assert backup.mydumper_verbose is None

    @pytest.mark.parametrize("level", [0, 3])
    def test_boundary_levels_accepted(self, level: int):
        """The inclusive ends of the 0 to 3 range validate."""
        backup = BackupCreate(
            **_base_payload(BackupType.MYDUMPER, mydumper_verbose=level)
        )
        assert backup.mydumper_verbose == level

    @pytest.mark.parametrize("bad", [4, -1, "abc"])
    def test_out_of_range_rejected(self, bad: int | str):
        """Out-of-range / garbage values are rejected before reaching YAML/CLI."""
        with pytest.raises(ValidationError, match="(?i)mydumper_verbose"):
            BackupCreate(**_base_payload(BackupType.MYDUMPER, mydumper_verbose=bad))

    def test_binlog_rejects_verbose(self):
        """mydumper_verbose is forbidden when backup_type=B."""
        with pytest.raises(ValidationError, match="mydumper_verbose"):
            BackupCreate(**_base_payload(BackupType.BINLOG, mydumper_verbose=1))

    def test_xtrabackup_rejects_verbose(self):
        """mydumper_verbose is forbidden when backup_type=X."""
        with pytest.raises(ValidationError, match="mydumper_verbose"):
            BackupCreate(**_base_payload(BackupType.XTRABACKUP, mydumper_verbose=1))

    def test_field_lives_on_backup_config_all(self):
        """The field must persist via BackupConfigAll, not only BackupCreate.

        BackupConfigAll.model_validate silently drops undeclared fields
        (Pydantic extra='ignore'); a BackupCreate-only field would never
        serialize into the persisted ALL_SERVERS YAML. Assert it round-trips
        and serializes as a plain int under the uppercase alias.
        """
        cfg = BackupConfigAll.model_validate({"MYDUMPER_VERBOSE": 2})
        assert cfg.mydumper_verbose == self.WARNINGS_LEVEL

        dumped = cfg.model_dump(by_alias=True, mode="json")
        assert dumped["MYDUMPER_VERBOSE"] == self.WARNINGS_LEVEL

    def test_derived_schema_bounds_preserved(self):
        """Keep the derived ``mydumper_verbose`` form bounds at 0-3 after the factory swap.

        The bounded factory result is the first arg of an outer ``Annotated``; this
        guards that Pydantic's metadata flattening keeps ``Ge``/``Le`` visible to the
        form-DSL derivation, so a wrong substitution cannot silently drop the bounds.
        """
        sections = derive_form_sections(BackupCreate, mysql_backups_views.layout)
        field = next(
            f
            for section in sections
            for f in section.fields
            if getattr(f, "name", None) == "mydumper_verbose"
        )
        expected_min, expected_max = 0, 3
        assert field.ge == expected_min
        assert field.le == expected_max
