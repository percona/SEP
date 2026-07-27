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
against, backed by :meth:`app.core.requests.remote_api.RemoteAPI.upload`, and
:class:`BundleSource` is the byte payload it carries. ``source_ref`` is an opaque
reference string, not a domain concept, so this module stays vendor-neutral.

This module lives in ``app.sep`` but imports only from ``app.core`` and no other
``app.sep`` module, keeping it promotable to core if a second service ever
becomes a real consumer.
"""

__all__ = [
    "BundleSource",
    "BundleUploader",
    "UploadResult",
]

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.core.requests.remote_api import FileContent


@dataclass(frozen=True, slots=True)
class BundleSource:
    """Carry a bundle's bytes and the metadata its multipart part needs.

    A bundle reaches SEP either already in memory or as a stream from the
    service that produced it, so the source is a byte payload rather than a
    path. The caller owns an open handle or iterator passed as ``content`` and
    closes it once the upload returns.

    :param filename: The filename announced to the receiver.
    :param content: The bundle's bytes, an open binary handle, or an async
        iterator of chunks.
    :param size: The bundle's size in bytes, which the uploader checks against
        its configured cap. A stream cannot be measured, so its producer states
        the size.
    """

    filename: str
    content: FileContent
    size: int


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
        bundle: BundleSource,
        case_ref: str | None,
        manifest: Mapping[str, Any],
    ) -> UploadResult:
        """Upload ``bundle`` with its metadata.

        :param source_ref: An opaque reference string identifying the upload's
            origin.
        :param bundle: The bundle bytes and the metadata describing them.
        :param case_ref: An optional case reference, or ``None`` to omit it.
        :param manifest: The bundle manifest sent alongside the file.
        :return: The parsed upload result.
        """
