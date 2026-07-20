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

"""Define tests for the bundle-upload protocol and RemoteAPI-backed uploader."""

import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientTimeout
from aioresponses import aioresponses
from pydantic import SecretStr

from app.core.exceptions import HTTPBadRequestException
from app.core.requests import RemoteAPI
from app.core.requests.bundle_upload import (
    BundleUploader,
    CredentialPlacement,
    RemoteAPIBundleUploader,
    RESERVED_UPLOAD_FIELDS,
    UploadResult,
)

_SECRET = "s3cr3t-value"

pytestmark = pytest.mark.asyncio


def _make_uploader(client: RemoteAPI, **overrides) -> RemoteAPIBundleUploader:
    """Build a ``RemoteAPIBundleUploader`` with sensible test defaults."""
    kwargs = {
        "path": "upload",
        "client_id": "acme-123",
        "credential": SecretStr(_SECRET),
        "credential_placement": CredentialPlacement.HEADER,
        "credential_name": "Authorization",
        "credential_scheme": "Bearer",
        "metadata": {},
        "max_bundle_bytes": 1024 * 1024,
        "response_reference_key": None,
        "timeout": None,
    }
    kwargs.update(overrides)
    return RemoteAPIBundleUploader(client, **kwargs)


@pytest.fixture
def bundle_path(tmp_path: Path) -> Path:
    """Provide a small on-disk bundle file."""
    path = tmp_path / "diagnostics.tar.gz"
    path.write_bytes(b"bundle-bytes")
    return path


@pytest.fixture
def mock_client() -> AsyncMock:
    """Provide a spec'd RemoteAPI boundary mock."""
    return AsyncMock(spec=RemoteAPI)


@pytest.fixture
def remote_api() -> RemoteAPI:
    """Provide a real RemoteAPI client pointed at a local base URL."""
    return RemoteAPI(endpoint="http://localhost:8000/")


class TestProtocolConformance:
    """Cover the runtime-checkable ``BundleUploader`` protocol."""

    def test_remote_api_uploader_satisfies_protocol(self, mock_client):
        """Assert the concrete uploader is a runtime ``BundleUploader``."""
        assert isinstance(_make_uploader(mock_client), BundleUploader)

    def test_object_without_upload_bundle_is_not_a_bundle_uploader(self):
        """Reject an object lacking ``upload_bundle`` as a ``BundleUploader``."""
        assert not isinstance(object(), BundleUploader)


class TestConstructionGuards:
    """Cover the reserved-field collision guards enforced at construction."""

    def test_metadata_key_colliding_with_reserved_field_rejected(self, mock_client):
        """Reject metadata whose key shadows a reserved multipart field."""
        with pytest.raises(ValueError, match="manifest"):
            _make_uploader(mock_client, metadata={"manifest": "x"})

    def test_form_field_credential_named_reserved_field_rejected(self, mock_client):
        """Reject a form-field credential named after a reserved field."""
        with pytest.raises(ValueError, match="file"):
            _make_uploader(
                mock_client,
                credential_placement=CredentialPlacement.FORM_FIELD,
                credential_name="file",
                credential_scheme="",
            )

    def test_form_field_credential_duplicating_metadata_rejected(self, mock_client):
        """Reject a form-field credential name that duplicates a metadata key."""
        with pytest.raises(ValueError, match="src"):
            _make_uploader(
                mock_client,
                credential_placement=CredentialPlacement.FORM_FIELD,
                credential_name="src",
                credential_scheme="",
                metadata={"src": "y"},
            )

    def test_header_credential_named_reserved_field_allowed(self, mock_client):
        """Allow a header credential named after a reserved field (distinct namespace)."""
        _make_uploader(
            mock_client,
            credential_placement=CredentialPlacement.HEADER,
            credential_name="file",
        )


class TestFieldConstruction:
    """Cover the multipart fields and file the uploader emits."""

    async def test_reserved_fields_and_metadata_merged(self, mock_client, bundle_path):
        """Emit client_id, source_ref, serialized manifest, and static metadata."""
        mock_client.upload.return_value = None
        uploader = _make_uploader(mock_client, metadata={"product": "pmm"})

        await uploader.upload_bundle(
            source_ref="ref-1",
            bundle_path=bundle_path,
            case_ref="CASE-9",
            manifest={"count": 3},
        )

        fields = mock_client.upload.call_args.kwargs["fields"]
        assert fields["client_id"] == "acme-123"
        assert fields["source_ref"] == "ref-1"
        assert fields["case_ref"] == "CASE-9"
        assert fields["product"] == "pmm"
        assert json.loads(fields["manifest"]) == {"count": 3}

    async def test_file_field_carries_bundle_filename(self, mock_client, bundle_path):
        """Send the bundle under the reserved ``file`` field with its filename."""
        mock_client.upload.return_value = None
        uploader = _make_uploader(mock_client)

        await uploader.upload_bundle(
            source_ref="ref-1",
            bundle_path=bundle_path,
            case_ref=None,
            manifest={},
        )

        files = mock_client.upload.call_args.kwargs["files"]
        assert files["file"][0] == bundle_path.name

    async def test_case_ref_none_omits_field(self, mock_client, bundle_path):
        """Omit the ``case_ref`` field entirely when the reference is ``None``."""
        mock_client.upload.return_value = None
        uploader = _make_uploader(mock_client)

        await uploader.upload_bundle(
            source_ref="ref-1",
            bundle_path=bundle_path,
            case_ref=None,
            manifest={"count": 3},
        )

        assert "case_ref" not in mock_client.upload.call_args.kwargs["fields"]

    async def test_empty_manifest_serializes_to_empty_object(
        self, mock_client, bundle_path
    ):
        """Serialize an empty manifest to ``{}`` without error."""
        mock_client.upload.return_value = None
        uploader = _make_uploader(mock_client)

        await uploader.upload_bundle(
            source_ref="ref-1",
            bundle_path=bundle_path,
            case_ref=None,
            manifest={},
        )

        assert mock_client.upload.call_args.kwargs["fields"]["manifest"] == "{}"

    async def test_empty_metadata_sends_only_core_fields(
        self, mock_client, bundle_path
    ):
        """Send no extra static fields when metadata is empty."""
        mock_client.upload.return_value = None
        uploader = _make_uploader(mock_client, metadata={})

        await uploader.upload_bundle(
            source_ref="ref-1",
            bundle_path=bundle_path,
            case_ref=None,
            manifest={},
        )

        assert set(mock_client.upload.call_args.kwargs["fields"]) == {
            "client_id",
            "source_ref",
            "manifest",
        }

    async def test_configured_timeout_threaded_to_upload(
        self, mock_client, bundle_path
    ):
        """Provide a configured timeout to the upload call as a ``ClientTimeout``."""
        expected_total = 12.5
        mock_client.upload.return_value = None
        uploader = _make_uploader(mock_client, timeout=expected_total)

        await uploader.upload_bundle(
            source_ref="ref-1",
            bundle_path=bundle_path,
            case_ref=None,
            manifest={},
        )

        timeout = mock_client.upload.call_args.kwargs["timeout"]
        assert isinstance(timeout, ClientTimeout)
        assert timeout.total == expected_total

    async def test_no_timeout_omits_timeout_kwarg(self, mock_client, bundle_path):
        """Omit the timeout kwarg when no timeout is configured."""
        mock_client.upload.return_value = None
        uploader = _make_uploader(mock_client, timeout=None)

        await uploader.upload_bundle(
            source_ref="ref-1",
            bundle_path=bundle_path,
            case_ref=None,
            manifest={},
        )

        assert "timeout" not in mock_client.upload.call_args.kwargs


class TestCredentialPlacement:
    """Cover header vs form-field credential placement."""

    async def test_header_placement_uses_extra_and_redact_headers(
        self, mock_client, bundle_path
    ):
        """Inject the credential header via ``extra_headers`` and mask it via ``redact_headers``."""
        mock_client.upload.return_value = None
        uploader = _make_uploader(
            mock_client,
            credential_placement=CredentialPlacement.HEADER,
            credential_name="X-Custom-Token",
            credential_scheme="Bearer",
        )

        await uploader.upload_bundle(
            source_ref="ref-1",
            bundle_path=bundle_path,
            case_ref=None,
            manifest={},
        )

        mock_client.extra_headers.assert_called_once_with(
            {"X-Custom-Token": f"Bearer {_SECRET}"}
        )
        mock_client.redact_headers.assert_called_once_with({"X-Custom-Token"})
        assert "X-Custom-Token" not in mock_client.upload.call_args.kwargs["fields"]

    async def test_form_field_placement_adds_credential_field(
        self, mock_client, bundle_path
    ):
        """Send the credential inside the multipart body as a form field."""
        mock_client.upload.return_value = None
        uploader = _make_uploader(
            mock_client,
            credential_placement=CredentialPlacement.FORM_FIELD,
            credential_name="api_key",
            credential_scheme="",
        )

        await uploader.upload_bundle(
            source_ref="ref-1",
            bundle_path=bundle_path,
            case_ref=None,
            manifest={},
        )

        assert mock_client.upload.call_args.kwargs["fields"]["api_key"] == _SECRET
        mock_client.extra_headers.assert_not_called()
        mock_client.redact_headers.assert_not_called()


class TestSizeCap:
    """Cover the pre-request bundle size cap."""

    async def test_oversized_bundle_raises_without_request(self, mock_client, tmp_path):
        """Reject an oversized bundle before issuing any HTTP request."""
        bundle = tmp_path / "big.bin"
        bundle.write_bytes(b"x" * 100)
        uploader = _make_uploader(mock_client, max_bundle_bytes=10)

        with pytest.raises(HTTPBadRequestException):
            await uploader.upload_bundle(
                source_ref="ref-1",
                bundle_path=bundle,
                case_ref=None,
                manifest={},
            )

        mock_client.upload.assert_not_called()

    async def test_missing_bundle_raises_file_not_found(self, mock_client, tmp_path):
        """Surface a missing bundle file as ``FileNotFoundError`` before any request."""
        uploader = _make_uploader(mock_client)

        with pytest.raises(FileNotFoundError):
            await uploader.upload_bundle(
                source_ref="ref-1",
                bundle_path=tmp_path / "absent.bin",
                case_ref=None,
                manifest={},
            )

        mock_client.upload.assert_not_called()


class TestResponseReference:
    """Cover extraction of ``UploadResult`` from the upload response."""

    async def test_reference_key_present_reads_value(self, mock_client, bundle_path):
        """Read ``reference`` from the configured key and keep the full body."""
        mock_client.upload.return_value = {"sys_id": "INC123", "state": "new"}
        uploader = _make_uploader(mock_client, response_reference_key="sys_id")

        result = await uploader.upload_bundle(
            source_ref="ref-1", bundle_path=bundle_path, case_ref=None, manifest={}
        )

        assert result == UploadResult(
            reference="INC123", detail={"sys_id": "INC123", "state": "new"}
        )

    async def test_non_string_reference_coerced_to_string(
        self, mock_client, bundle_path
    ):
        """Coerce a non-string reference value to ``str`` to honor the field type."""
        mock_client.upload.return_value = {"sys_id": 12345}
        uploader = _make_uploader(mock_client, response_reference_key="sys_id")

        result = await uploader.upload_bundle(
            source_ref="ref-1", bundle_path=bundle_path, case_ref=None, manifest={}
        )

        assert result.reference == "12345"

    async def test_reference_key_missing_yields_none_reference(
        self, mock_client, bundle_path
    ):
        """Yield ``None`` reference when the configured key is absent, keep the body."""
        mock_client.upload.return_value = {"state": "new"}
        uploader = _make_uploader(mock_client, response_reference_key="sys_id")

        result = await uploader.upload_bundle(
            source_ref="ref-1", bundle_path=bundle_path, case_ref=None, manifest={}
        )

        assert result.reference is None
        assert result.detail == {"state": "new"}

    async def test_list_body_yields_none_reference_and_detail(
        self, mock_client, bundle_path
    ):
        """Yield ``None`` reference and detail when the response is a list."""
        mock_client.upload.return_value = [{"sys_id": "INC123"}]
        uploader = _make_uploader(mock_client, response_reference_key="sys_id")

        result = await uploader.upload_bundle(
            source_ref="ref-1", bundle_path=bundle_path, case_ref=None, manifest={}
        )

        assert result.reference is None
        assert result.detail is None

    async def test_reference_key_unset_yields_none_reference(
        self, mock_client, bundle_path
    ):
        """Yield ``None`` reference when no reference key is configured."""
        mock_client.upload.return_value = {"sys_id": "INC123"}
        uploader = _make_uploader(mock_client, response_reference_key=None)

        result = await uploader.upload_bundle(
            source_ref="ref-1", bundle_path=bundle_path, case_ref=None, manifest={}
        )

        assert result.reference is None
        assert result.detail == {"sys_id": "INC123"}

    async def test_non_json_success_yields_empty_result(self, mock_client, bundle_path):
        """Yield an empty ``UploadResult`` when the upload returns ``None`` (2xx, no JSON)."""
        mock_client.upload.return_value = None
        uploader = _make_uploader(mock_client, response_reference_key="sys_id")

        result = await uploader.upload_bundle(
            source_ref="ref-1", bundle_path=bundle_path, case_ref=None, manifest={}
        )

        assert result.reference is None
        assert result.detail is None


class TestCredentialRedaction:
    """Cover that the credential never reaches the debug request log."""

    async def test_header_credential_masked_in_debug_log(
        self, remote_api, bundle_path, caplog
    ):
        """Mask a custom credential header in the request-log line."""
        uploader = _make_uploader(
            remote_api,
            credential_placement=CredentialPlacement.HEADER,
            credential_name="X-Custom-Token",
            credential_scheme="",
        )

        with aioresponses() as mock, caplog.at_level(logging.DEBUG):
            mock.post("http://localhost:8000/upload", status=201, payload={"ok": True})
            async with remote_api:
                await uploader.upload_bundle(
                    source_ref="ref-1",
                    bundle_path=bundle_path,
                    case_ref=None,
                    manifest={},
                )

        assert _SECRET not in caplog.text
        assert "****" in caplog.text

    async def test_form_field_credential_absent_from_debug_log(
        self, remote_api, bundle_path, caplog
    ):
        """Keep a form-field credential out of the log (it rides in the opaque body)."""
        uploader = _make_uploader(
            remote_api,
            credential_placement=CredentialPlacement.FORM_FIELD,
            credential_name="api_key",
            credential_scheme="",
        )

        with aioresponses() as mock, caplog.at_level(logging.DEBUG):
            mock.post("http://localhost:8000/upload", status=201, payload={"ok": True})
            async with remote_api:
                await uploader.upload_bundle(
                    source_ref="ref-1",
                    bundle_path=bundle_path,
                    case_ref=None,
                    manifest={},
                )

        assert _SECRET not in caplog.text


class TestCredentialReachesServer:
    """Cover that the credential is transmitted in the configured location."""

    async def test_header_credential_sent_in_request_header(
        self, remote_api, bundle_path
    ):
        """Send a header credential in the outgoing request headers."""
        uploader = _make_uploader(
            remote_api,
            credential_placement=CredentialPlacement.HEADER,
            credential_name="X-Custom-Token",
            credential_scheme="Bearer",
        )

        with aioresponses() as mock:
            mock.post("http://localhost:8000/upload", status=201, payload={"ok": True})
            async with remote_api:
                await uploader.upload_bundle(
                    source_ref="ref-1",
                    bundle_path=bundle_path,
                    case_ref=None,
                    manifest={},
                )
            request = next(iter(mock.requests.values()))[0]

        assert request.kwargs["headers"]["X-Custom-Token"] == f"Bearer {_SECRET}"

    async def test_form_field_credential_absent_from_request_headers(
        self, remote_api, bundle_path
    ):
        """Keep a form-field credential out of the outgoing request headers."""
        uploader = _make_uploader(
            remote_api,
            credential_placement=CredentialPlacement.FORM_FIELD,
            credential_name="api_key",
            credential_scheme="",
        )

        with aioresponses() as mock:
            mock.post("http://localhost:8000/upload", status=201, payload={"ok": True})
            async with remote_api:
                await uploader.upload_bundle(
                    source_ref="ref-1",
                    bundle_path=bundle_path,
                    case_ref=None,
                    manifest={},
                )
            request = next(iter(mock.requests.values()))[0]

        assert "api_key" not in (request.kwargs.get("headers") or {})


def test_reserved_upload_fields_membership():
    """Assert the reserved-field set names the fields the uploader always emits."""
    assert (
        frozenset({"client_id", "case_ref", "source_ref", "manifest", "file"})
        == RESERVED_UPLOAD_FIELDS
    )
