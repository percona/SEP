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

"""Define the generic bundle-upload seam: protocol, result, and RemoteAPI impl.

A bundle upload POSTs a file bundle plus scalar metadata to a configured intake
endpoint. :class:`BundleUploader` is the narrow protocol a send pipeline programs
against; :class:`RemoteAPIBundleUploader` is the one concrete implementation,
backed by :meth:`app.core.requests.remote_api.RemoteAPI.upload`. Everything
instance-specific (endpoint, credential and its placement, client id, metadata,
size cap) is supplied by the consumer, so this module stays vendor-neutral --
``source_ref`` is an opaque reference string, not a domain concept.
"""

__all__ = [
    "RESERVED_UPLOAD_FIELDS",
    "BundleUploader",
    "CredentialPlacement",
    "RemoteAPIBundleUploader",
    "UploadResult",
]

from collections.abc import Mapping
from dataclasses import dataclass
from enum import auto, StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from aiohttp import ClientTimeout
from pydantic import SecretStr

from app.core.exceptions import HTTPBadRequestException
from app.core.requests.remote_api import RemoteAPI
from app.core.utils import json_serializer


class CredentialPlacement(StrEnum):
    """Enumerate where the upload credential is carried on the request."""

    HEADER = auto()
    FORM_FIELD = auto()


#: Multipart field names the uploader always emits. Operator-configured metadata
#: keys and a form-field credential name must not collide with these, else a
#: required field or the file part would be silently overwritten.
RESERVED_UPLOAD_FIELDS: frozenset[str] = frozenset(
    {"client_id", "case_ref", "source_ref", "manifest", "file"}
)


@dataclass(frozen=True, slots=True)
class UploadResult:
    """Represent the outcome of a bundle upload.

    :param reference: The value read from the configured response reference key,
        or ``None`` when unconfigured, absent, or the body is not a JSON object.
    :param detail: The raw JSON-object response body, or ``None`` when the body
        is absent or not a JSON object.
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


class RemoteAPIBundleUploader:
    """Upload a bundle through :meth:`RemoteAPI.upload` against a configured endpoint."""

    def __init__(
        self,
        client: RemoteAPI,
        *,
        path: str = "",
        client_id: str,
        credential: SecretStr,
        credential_placement: CredentialPlacement,
        credential_name: str,
        credential_scheme: str,
        metadata: Mapping[str, str],
        max_bundle_bytes: int,
        response_reference_key: str | None = None,
        timeout: float | None = None,
    ) -> None:
        """Configure the uploader and reject reserved-field collisions.

        The settings layer is the primary collision gate, but the uploader owns
        :data:`RESERVED_UPLOAD_FIELDS`, so it re-checks its own contract here.

        :param client: The RemoteAPI client bound to the intake endpoint.
        :param path: The endpoint path to POST bundles to.
        :param client_id: The customer identifier sent with every upload.
        :param credential: The upload credential.
        :param credential_placement: Whether the credential rides in a header or
            a form field.
        :param credential_name: The header name or form-field name for the
            credential.
        :param credential_scheme: The header scheme prefix (e.g. ``Bearer``);
            empty for a raw header value or a form-field credential.
        :param metadata: Static form fields sent with every upload.
        :param max_bundle_bytes: The maximum accepted bundle size in bytes.
        :param response_reference_key: The top-level response key read into
            :attr:`UploadResult.reference`, or ``None`` to always yield ``None``.
        :param timeout: The per-request timeout in seconds, or ``None`` to use
            the client default.
        :raises ValueError: When a metadata key or a form-field credential name
            collides with a reserved upload field or a metadata key.
        """
        reserved_clashes = set(metadata) & RESERVED_UPLOAD_FIELDS
        if reserved_clashes:
            raise ValueError(
                f"metadata keys collide with reserved upload fields: "
                f"{sorted(reserved_clashes)}"
            )
        if credential_placement is CredentialPlacement.FORM_FIELD:
            if credential_name in RESERVED_UPLOAD_FIELDS:
                raise ValueError(
                    f"credential_name '{credential_name}' is a reserved upload "
                    f"field name under form-field placement"
                )
            if credential_name in metadata:
                raise ValueError(
                    f"credential_name '{credential_name}' duplicates a metadata field"
                )
        self._client = client
        self._path = path
        self._client_id = client_id
        self._credential = credential
        self._credential_placement = credential_placement
        self._credential_name = credential_name
        self._credential_scheme = credential_scheme
        self._metadata = metadata
        self._max_bundle_bytes = max_bundle_bytes
        self._response_reference_key = response_reference_key
        self._timeout = timeout

    async def upload_bundle(
        self,
        *,
        source_ref: str,
        bundle_path: Path,
        case_ref: str | None,
        manifest: Mapping[str, Any],
    ) -> UploadResult:
        """Upload ``bundle_path`` with its metadata and return the parsed result.

        Enforce the size cap by stat before opening the file, then stream the
        bundle under the reserved ``file`` field alongside the scalar metadata.
        The credential rides in a masked header or a form field per the
        configured placement.

        :param source_ref: An opaque reference string identifying the upload's
            origin.
        :param bundle_path: The path to the bundle file to send.
        :param case_ref: An optional case reference; omitted from the request
            when ``None``.
        :param manifest: The bundle manifest, serialized as a JSON form field.
        :return: The parsed upload result.
        :raises HTTPBadRequestException: When the bundle exceeds the size cap.
        :raises FileNotFoundError: When the bundle file does not exist.
        :raises HTTPException: Propagates the project exception mapped from an
            upstream error status by :meth:`RemoteAPI.upload`.
        """
        size = bundle_path.stat().st_size
        if size > self._max_bundle_bytes:
            raise HTTPBadRequestException(
                f"Bundle exceeds the maximum upload size "
                f"({self._max_bundle_bytes} bytes)."
            )
        fields = {
            "client_id": self._client_id,
            "source_ref": source_ref,
            "manifest": json_serializer(manifest),
            **self._metadata,
        }
        if case_ref is not None:
            fields["case_ref"] = case_ref
        request_kwargs = {}
        if self._timeout is not None:
            request_kwargs["timeout"] = ClientTimeout(total=self._timeout)
        with bundle_path.open("rb") as bundle:
            files = {"file": (bundle_path.name, bundle, "application/octet-stream")}
            if self._credential_placement is CredentialPlacement.HEADER:
                secret = self._credential.get_secret_value()
                header_value = f"{self._credential_scheme} {secret}".strip()
                with (
                    self._client.extra_headers({self._credential_name: header_value}),
                    self._client.redact_headers({self._credential_name}),
                ):
                    response = await self._client.upload(
                        self._path, files=files, fields=fields, **request_kwargs
                    )
            else:
                fields[self._credential_name] = self._credential.get_secret_value()
                response = await self._client.upload(
                    self._path, files=files, fields=fields, **request_kwargs
                )
        raw_reference = (
            response.get(self._response_reference_key)
            if self._response_reference_key and isinstance(response, dict)
            else None
        )
        reference = None if raw_reference is None else str(raw_reference)
        detail = response if isinstance(response, dict) else None
        return UploadResult(reference=reference, detail=detail)
