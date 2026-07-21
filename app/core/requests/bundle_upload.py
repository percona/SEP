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

"""Define the generic bundle-upload seam: protocol and result type.

A bundle upload POSTs a file bundle plus scalar metadata to a configured intake
endpoint. :class:`BundleUploader` is the narrow protocol a send pipeline programs
against, backed by :meth:`app.core.requests.remote_api.RemoteAPI.upload`.
``source_ref`` is an opaque reference string, not a domain concept, so this
module stays vendor-neutral.
"""

__all__ = [
    "BundleUploader",
    "UploadResult",
]

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class UploadResult:
    """Represent the outcome of a bundle upload.

    :param reference: The extracted upload reference, if the executor
        extracted one.
    :param detail: The response payload preserved for the send log.
    """

    reference: str | None
    detail: Mapping[str, Any] | None


@runtime_checkable
class BundleUploader(Protocol):
    """Describe the structural surface a bundle-send pipeline consumes."""

    async def upload_bundle(
        self,
        *,
        source_ref: str,
        bundle_path: Path,
        case_ref: str | None,
        manifest: Mapping[str, Any],
    ) -> UploadResult:
        """Upload the bundle at ``bundle_path`` with its metadata.

        :param source_ref: An opaque reference string identifying the upload's
            origin.
        :param bundle_path: The path to the bundle file to send.
        :param case_ref: An optional case reference, or ``None`` to omit it.
        :param manifest: The bundle manifest sent alongside the file.
        :return: The parsed upload result.
        """
