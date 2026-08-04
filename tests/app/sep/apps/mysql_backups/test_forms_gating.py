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
    """Enforce the independent-modes encryption model.

    ``encrypt`` (in-place) and ``post_run_encrypt`` are independent modes;
    ``encrypt_using_tmpdir`` requires ``encrypt`` and is mutually exclusive with
    ``post_run_encrypt``; and ``encryption_recipient`` is required iff either mode
    is enabled.
    """

    def test_defaults_yield_valid_disabled_config(self):
        """Accept an untouched Encryption section (all defaults) as a disabled config."""
        form = BackupCreate(**_base_payload(BackupType.MYDUMPER))
        assert form.encrypt is False
        assert form.encrypt_using_tmpdir is False
        assert form.post_run_encrypt is False
        assert form.encryption_recipient is None

    def test_encrypt_with_recipient_ok(self):
        """encrypt=True + recipient validates."""
        BackupCreate(
            **_base_payload(
                BackupType.MYDUMPER,
                encrypt=True,
                encryption_recipient="ops@example.com",
            )
        )

    def test_encrypt_without_recipient_fails(self):
        """encrypt=True without recipient → 422."""
        with pytest.raises(ValidationError, match="encryption_recipient"):
            BackupCreate(**_base_payload(BackupType.MYDUMPER, encrypt=True))

    def test_recipient_without_any_encryption_fails(self):
        """Recipient set with no encryption mode enabled → 422."""
        with pytest.raises(ValidationError, match="encryption_recipient"):
            BackupCreate(
                **_base_payload(
                    BackupType.MYDUMPER,
                    encrypt=False,
                    encryption_recipient="ops@example.com",
                )
            )

    def test_tmpdir_with_encrypt_ok(self):
        """Accept encrypt with encrypt_using_tmpdir and a recipient (tmpdir mode)."""
        BackupCreate(
            **_base_payload(
                BackupType.MYDUMPER,
                encrypt=True,
                encrypt_using_tmpdir=True,
                encryption_recipient="ops@example.com",
            )
        )

    def test_post_run_with_encrypt_ok(self):
        """Accept encrypt with post_run_encrypt and a recipient (post-run mode)."""
        BackupCreate(
            **_base_payload(
                BackupType.MYDUMPER,
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
                encrypt=False,
                post_run_encrypt=True,
                encryption_recipient="ops@example.com",
            )
        )

    def test_post_run_without_recipient_fails(self):
        """Reject post_run_encrypt without a recipient (post-run GPG needs one)."""
        with pytest.raises(ValidationError, match="encryption_recipient"):
            BackupCreate(**_base_payload(BackupType.MYDUMPER, post_run_encrypt=True))

    def test_tmpdir_and_post_run_together_fails(self):
        """Reject encrypt_using_tmpdir combined with post_run_encrypt."""
        with pytest.raises(ValidationError, match="encrypt_using_tmpdir"):
            BackupCreate(
                **_base_payload(
                    BackupType.MYDUMPER,
                    encrypt=True,
                    encrypt_using_tmpdir=True,
                    post_run_encrypt=True,
                    encryption_recipient="ops@example.com",
                )
            )


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
