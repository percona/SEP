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

from app.sep.plugins.mysql_backups.models import (
    BackupConfigAll,
    BackupCreate,
    BackupType,
    UploadProvider,
)


def _base_payload(backup_type: BackupType, **overrides) -> dict:
    """Build a minimal valid ``BackupCreate`` kwargs dict.

    ``upload`` is required and non-empty per the SEP-1061 explicit
    MultiChoice contract; the default pair (S3 + ``s3_bucket``) keeps the
    bidirectional validator happy so each test can override ``upload`` /
    bucket fields only when that is the assertion under test.
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
    """``encryption_recipient`` is required iff ``encrypt`` is truthy."""

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

    def test_recipient_without_encrypt_fails(self):
        """Recipient set with encrypt=False → 422."""
        with pytest.raises(ValidationError, match="encryption_recipient"):
            BackupCreate(
                **_base_payload(
                    BackupType.MYDUMPER,
                    encrypt=False,
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

    def test_empty_upload_list_rejected(self):
        """``upload=[]`` violates the explicit MultiChoice contract → 422.

        Per SEP-1061 codex feedback: the React multichoice field initialises
        to ``[]``; a missing or empty selection must surface 422 instead of
        silently falling back to a legacy bucket-inference path. The
        ``min_length=1`` constraint on ``BackupCreate.upload`` enforces this.
        """
        with pytest.raises(ValidationError, match="(?i)upload"):
            BackupCreate(**_base_payload(BackupType.MYDUMPER, upload=[]))

    def test_missing_upload_rejected(self):
        """``upload`` is required; a payload without it surfaces a 422."""
        payload = _base_payload(BackupType.MYDUMPER)
        payload.pop("upload")
        payload.pop("s3_bucket")
        with pytest.raises(ValidationError, match=r"(?i)upload"):
            BackupCreate(**payload)


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
