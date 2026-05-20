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
    BackupCreate,
    BackupType,
    UploadProvider,
)


def _base_payload(backup_type: BackupType, **overrides) -> dict:
    """Build a minimal valid ``BackupCreate`` kwargs dict."""
    payload = {
        "task_name": "task1",
        "hostname": "host1",
        "service_id": 1,
        "backup_type": backup_type,
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
        """``s3_bucket`` set with ``S3`` absent from ``upload`` → 422."""
        with pytest.raises(ValidationError, match="S3"):
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
                **_base_payload(BackupType.MYDUMPER, upload=[UploadProvider.S3])
            )

    def test_gcs_in_upload_without_bucket_fails(self):
        """``GSUTIL`` in ``upload`` with empty ``gs_bucket`` → 422."""
        with pytest.raises(ValidationError, match="GSUTIL"):
            BackupCreate(
                **_base_payload(BackupType.MYDUMPER, upload=[UploadProvider.GSUTIL])
            )

    def test_rsync_in_upload_without_path_fails(self):
        """``RSYNC`` in ``upload`` with empty ``rsync_path`` → 422."""
        with pytest.raises(ValidationError, match="RSYNC"):
            BackupCreate(
                **_base_payload(BackupType.MYDUMPER, upload=[UploadProvider.RSYNC])
            )

    def test_s3_auxiliary_without_s3_fails(self):
        """``s3_storage_class`` etc. without ``S3`` in upload → 422."""
        with pytest.raises(ValidationError, match="auxiliary"):
            BackupCreate(
                **_base_payload(
                    BackupType.MYDUMPER,
                    upload=[UploadProvider.RSYNC],
                    rsync_path="/r",
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

    def test_none_upload_preserves_legacy_behavior(self):
        """``upload=None`` (legacy form path) does NOT enforce coupling."""
        BackupCreate(
            **_base_payload(
                BackupType.MYDUMPER,
                s3_bucket="bkt",
            )
        )


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
