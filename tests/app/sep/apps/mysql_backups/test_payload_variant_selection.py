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

"""Tests for selecting the xtrabackup payload variant from the upload selection.

``xtrabackup_payload`` carries all three upload-provider classes and sits against
the 16 KiB Nomad dispatch limit, so each upload selection dispatches a variant
carrying only the providers it can reach. These tests pin the selection for all
eight selections, that ``boto3`` is requested only when an S3 provider ships, and
that the other two backup types are untouched by any of it.
"""

import pytest

from app.core.utils.path import resolve_payload_reference
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework.spec import ResolvedEntities, RunPythonSpec
from app.sep.apps.mysql_backups.forms import BackupCreate, UploadProvider
from app.sep.apps.mysql_backups.payload_variants import PROVIDERS
from app.sep.apps.mysql_backups.spec import build_backup_spec
from app.sep.inventory import CreatedService
from tests.app.factories import CreatedNodeFactory, CreatedServiceFactory

_HOSTNAME = "executor-host"

# The aux field each provider's form gate requires once it is selected.
_PROVIDER_FIELDS = {
    "RSYNC": {"rsync_path": "/data/rsync"},
    "S3": {"s3_bucket": "my-s3-bucket"},
    "GSUTIL": {"gs_bucket": "my-gcs-bucket"},
}

# Every upload selection, and the payload the dispatch must carry for it. The
# all-providers selection is the canonical payload -- it is the complete source,
# not a generated variant.
_SELECTIONS = [
    ([], "xtrabackup_noupload_payload"),
    (["RSYNC"], "xtrabackup_rsync_payload"),
    (["S3"], "xtrabackup_s3_payload"),
    (["GSUTIL"], "xtrabackup_gsutil_payload"),
    (["RSYNC", "S3"], "xtrabackup_rsync_s3_payload"),
    (["RSYNC", "GSUTIL"], "xtrabackup_rsync_gsutil_payload"),
    (["S3", "GSUTIL"], "xtrabackup_s3_gsutil_payload"),
    (["RSYNC", "S3", "GSUTIL"], "xtrabackup_payload"),
]


def _service() -> CreatedService:
    """Return the inventory service the forms resolve against.

    :return: The built ``CreatedService``.
    """
    node = CreatedNodeFactory.build(address="db.internal", node_name="db-node")
    return CreatedServiceFactory.build(
        node=node, type=ServiceTypeEnum.MYSQL, name="svc-backups", port=3306
    )


def _spec(upload: list[str], backup_type: str = "X") -> RunPythonSpec:
    """Build the run-python spec for an upload selection.

    :param upload: The upload providers the form selects.
    :param backup_type: The backup type under test.
    :return: The built ``RunPythonSpec``.
    """
    service = _service()
    fields: dict[str, object] = {}
    for provider in upload:
        fields.update(_PROVIDER_FIELDS[provider])
    form = BackupCreate(
        task_name="backups-variant",
        hostname=_HOSTNAME,
        service_id=service.id,
        backup_type=backup_type,
        upload=upload,
        **fields,
    )
    resolved = ResolvedEntities(
        service=service,
        entities={"service_id": service},
        executor_host=_HOSTNAME,
    )
    return build_backup_spec(form, resolved)


class TestVariantSelection:
    """Assert each upload selection dispatches the payload carrying its providers."""

    @pytest.mark.parametrize(("upload", "expected"), _SELECTIONS, ids=lambda v: str(v))
    def test_selection_picks_its_variant(
        self, upload: list[str], expected: str
    ) -> None:
        """Assert the selection resolves to the variant named for those providers."""
        assert _spec(upload).payload.endswith(f"/{expected}")

    @pytest.mark.parametrize(("upload", "expected"), _SELECTIONS, ids=lambda v: str(v))
    def test_selected_variant_exists_on_disk(
        self, upload: list[str], expected: str
    ) -> None:
        """Assert every selection resolves to a payload file that actually ships."""
        assert resolve_payload_reference(_spec(upload).payload).is_file()

    def test_provider_order_in_the_form_does_not_change_the_variant(self) -> None:
        """Assert the variant is keyed on the set of providers, not the form's order."""
        forward = _spec(["RSYNC", "S3"]).payload
        reverse = _spec(["S3", "RSYNC"]).payload
        assert forward == reverse

    def test_every_selection_maps_to_a_distinct_payload(self) -> None:
        """Assert no two selections collide on one variant, which would ship dead code."""
        payloads = [_spec(upload).payload for upload, _ in _SELECTIONS]
        assert len(set(payloads)) == len(_SELECTIONS)


class TestBoto3Requirement:
    """Assert ``boto3`` is requested exactly when the dispatched variant needs it."""

    @pytest.mark.parametrize("upload", [upload for upload, _ in _SELECTIONS], ids=str)
    def test_boto3_tracks_the_s3_provider(self, upload: list[str]) -> None:
        """Assert boto3 ships only for a variant carrying the S3 provider."""
        requirements = _spec(upload).requirements.splitlines()
        assert ("boto3" in requirements) is ("S3" in upload)

    def test_non_s3_variant_keeps_the_other_requirements(self) -> None:
        """Assert dropping boto3 leaves the rest of the requirement set intact."""
        requirements = _spec(["RSYNC"]).requirements.splitlines()
        assert set(requirements) == {
            "packaging",
            "PyYAML",
            "PyMySQL[rsa,ed25519]",
            "filelock",
        }


class TestOtherBackupTypesUnaffected:
    """Assert only the xtrabackup payload is variant-selected."""

    @pytest.mark.parametrize(
        ("backup_type", "expected"),
        [("M", "mydumper_payload"), ("B", "binlog_payload")],
    )
    def test_payload_is_not_variant_selected(
        self, backup_type: str, expected: str
    ) -> None:
        """Assert mydumper and binlog keep their single payload for any selection."""
        assert _spec(["RSYNC"], backup_type).payload.endswith(f"/{expected}")

    @pytest.mark.parametrize("backup_type", ["M", "B"])
    def test_boto3_still_ships(self, backup_type: str) -> None:
        """Assert both payloads keep boto3 -- each imports it regardless of upload."""
        assert "boto3" in _spec([], backup_type).requirements.splitlines()


class TestNamingRule:
    """Assert the shared naming rule still lines up with the form's enum."""

    def test_provider_slugs_match_the_form_enum(self) -> None:
        """Assert filename slugs and their order track ``UploadProvider``.

        ``PROVIDERS`` is stdlib-only so the generator can read it without standing
        up the app, which leaves the enum free to drift away from it. A renamed or
        reordered member would silently dispatch a payload that does not exist.
        """
        assert tuple(provider.value for provider in UploadProvider) == PROVIDERS
