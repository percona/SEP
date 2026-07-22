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

"""Define tests for the ``BundleUploader`` protocol surface."""

from collections.abc import Mapping
from typing import Any

from app.sep.bundle_upload.seam import BundleSource, BundleUploader, UploadResult


class _MinimalBundleUploader:
    """Satisfy the ``BundleUploader`` protocol with a no-op implementation."""

    async def upload_bundle(
        self,
        *,
        source_ref: str,
        bundle: BundleSource,
        case_ref: str | None,
        manifest: Mapping[str, Any],
    ) -> UploadResult:
        """Return an empty result without performing any upload."""
        return UploadResult(reference=None, detail=None)


class TestProtocolConformance:
    """Cover the runtime-checkable ``BundleUploader`` protocol."""

    def test_minimal_uploader_satisfies_protocol(self):
        """Assert a minimal test double is a runtime ``BundleUploader``."""
        assert isinstance(_MinimalBundleUploader(), BundleUploader)

    def test_object_without_upload_bundle_is_not_a_bundle_uploader(self):
        """Reject an object lacking ``upload_bundle`` as a ``BundleUploader``."""
        assert not isinstance(object(), BundleUploader)
