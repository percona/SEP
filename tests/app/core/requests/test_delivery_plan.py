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

"""Define tests for the config-driven delivery plan schema and executor."""

import re
from pathlib import Path
from typing import Any

import pytest
from aiohttp import MultipartWriter
from aioresponses import aioresponses
from fastapi import status
from pydantic import ValidationError

from app.core.exceptions import HTTPBadGatewayException, HTTPConflictException
from app.core.requests import RemoteAPI
from app.core.requests.bundle_upload import BundleUploader
from app.core.requests.delivery_plan import (
    DeliveryPlan,
    DeliveryPlanError,
    DeliveryPlanExecutor,
)

_BASE_URL = "http://localhost:8000/"
_UPLOAD_URL = "http://localhost:8000/attachment/upload"
_TICKET_URL = "http://localhost:8000/ticket_details"
_ACCOUNT_URL = "http://localhost:8000/case_account"
_MANIFEST: dict[str, Any] = {"bundle": "diag", "size": 12}


@pytest.fixture(name="api")
def api_fixture() -> RemoteAPI:
    """Provide a real ``RemoteAPI`` client pointed at a local base URL."""
    return RemoteAPI(endpoint=_BASE_URL)


@pytest.fixture(name="bundle_path")
def bundle_path_fixture(tmp_path: Path) -> Path:
    """Write a small bundle file and return its path."""
    path = tmp_path / "bundle.tar.gz"
    path.write_bytes(b"bundle-bytes")
    return path


def _multipart_fields(payload: MultipartWriter) -> dict[str, str]:
    """Return the scalar form fields of a recorded multipart body.

    :param payload: The multipart body aiohttp was handed for the upload.
    :return: Scalar field values keyed by field name; the file part is skipped.
    """
    fields = {}
    for part, _encoding, _transfer_encoding in payload:
        disposition = part.headers.get("Content-Disposition", "")
        name = re.search(r'name="([^"]+)"', disposition)
        if name and "filename=" not in disposition:
            fields[name.group(1)] = part.decode()
    return fields


def _file_part_dispositions(payload: MultipartWriter) -> list[str]:
    """Return the Content-Disposition headers of a multipart body's file parts.

    :param payload: The multipart body aiohttp was handed for the upload.
    :return: One disposition string per part carrying a ``filename``.
    """
    return [
        disposition
        for part, _encoding, _transfer_encoding in payload
        if "filename=" in (disposition := part.headers.get("Content-Disposition", ""))
    ]


def _recorded(mock: aioresponses, path_fragment: str) -> Any:
    """Return the first request aioresponses recorded for a matching path.

    :param mock: The active ``aioresponses`` context.
    :param path_fragment: A substring of the request URL to match.
    :return: The recorded request call.
    :raises AssertionError: When no recorded request matches.
    """
    for key, calls in mock.requests.items():
        if path_fragment in str(key[1]):
            return calls[0]
    raise AssertionError(f"no request recorded for {path_fragment!r}")


def _upload_only_plan(**upload_overrides: Any) -> dict[str, Any]:
    """Return a zero-resolution-step plan payload with an overridable upload step."""
    upload = {
        "path": "attachment/upload",
        "fields": {
            "table_name": {"source": "literal", "value": "sn_customerservice_case"},
            "source": {"source": "input", "field": "source_ref"},
        },
        "reference_pointer": "/result/sys_id",
    }
    upload.update(upload_overrides)
    return {"endpoint": _BASE_URL, "upload": upload}


def _one_step_plan() -> dict[str, Any]:
    """Return a ServiceNow-shaped plan with one resolution step feeding the upload."""
    return {
        "endpoint": _BASE_URL,
        "secrets": {"api_key": "real-api-key", "client_token": "real-client-token"},
        "resolution_steps": [
            {
                "name": "lookup",
                "method": "POST",
                "path": "ticket_details",
                "headers": {"x-sn-apikey": {"source": "secret", "name": "api_key"}},
                "body": {
                    "client_token": {"source": "secret", "name": "client_token"},
                    "ticket_number": {"source": "input", "field": "case_ref"},
                },
                "outputs": {"sys_id": "/result/sys_id"},
            }
        ],
        "upload": {
            "path": "attachment/upload",
            "headers": {"x-sn-apikey": {"source": "secret", "name": "api_key"}},
            "fields": {
                "table_name": {
                    "source": "literal",
                    "value": "sn_customerservice_case",
                },
                "table_sys_id": {
                    "source": "output",
                    "step": "lookup",
                    "output": "sys_id",
                },
                "manifest": {"source": "input", "field": "manifest"},
            },
            "reference_pointer": "/result/sys_id",
        },
    }


def _two_step_plan() -> dict[str, Any]:
    """Return a plan whose second resolution step consumes the first step's output."""
    payload = _one_step_plan()
    payload["resolution_steps"].append(
        {
            "name": "account",
            "method": "POST",
            "path": "case_account",
            "body": {
                "case": {"source": "output", "step": "lookup", "output": "sys_id"}
            },
            "outputs": {"account_id": "/result/account_id"},
        }
    )
    payload["upload"]["fields"]["account_id"] = {
        "source": "output",
        "step": "account",
        "output": "account_id",
    }
    return payload


class TestDeliveryPlanValidation:
    """Cover the load-time cross-reference validator on ``DeliveryPlan``."""

    def test_zero_step_plan_is_valid(self):
        """Accept a plan with no resolution steps and a terminal upload step."""
        plan = DeliveryPlan(**_upload_only_plan())

        assert plan.resolution_steps == []
        assert plan.upload.file_field == "file"

    def test_one_step_service_now_shaped_plan_is_valid(self):
        """Accept a header secret, a body secret, and an output feeding the upload."""
        plan = DeliveryPlan(**_one_step_plan())

        assert [step.name for step in plan.resolution_steps] == ["lookup"]
        assert plan.secrets["api_key"].get_secret_value() == "real-api-key"

    def test_missing_upload_block_is_rejected(self):
        """Reject a plan that declares no terminal upload step."""
        with pytest.raises(ValidationError, match="upload"):
            DeliveryPlan(endpoint=_BASE_URL)

    def test_undefined_secret_reference_is_rejected(self):
        """Reject a secret reference that names no declared secret."""
        payload = _upload_only_plan(
            headers={"x-sn-apikey": {"source": "secret", "name": "missing"}}
        )
        with pytest.raises(ValidationError, match="undefined secret 'missing'"):
            DeliveryPlan(**payload)

    def test_output_reference_to_unknown_step_is_rejected(self):
        """Reject an output reference naming a step the plan never declares."""
        payload = _upload_only_plan(
            fields={
                "table_sys_id": {
                    "source": "output",
                    "step": "ghost",
                    "output": "sys_id",
                }
            }
        )
        with pytest.raises(ValidationError, match="step 'ghost'"):
            DeliveryPlan(**payload)

    def test_forward_output_reference_is_rejected(self):
        """Reject a step referencing an output declared by a later step."""
        payload = _one_step_plan()
        payload["resolution_steps"].append(
            {
                "name": "second",
                "method": "GET",
                "path": "later",
                "outputs": {"other": "/result/other"},
            }
        )
        payload["resolution_steps"][0]["query"] = {
            "hint": {"source": "output", "step": "second", "output": "other"}
        }
        with pytest.raises(ValidationError, match="step 'second'"):
            DeliveryPlan(**payload)

    def test_self_output_reference_is_rejected(self):
        """Reject a step referencing its own output."""
        payload = _one_step_plan()
        payload["resolution_steps"][0]["query"] = {
            "hint": {"source": "output", "step": "lookup", "output": "sys_id"}
        }
        with pytest.raises(ValidationError, match="step 'lookup'"):
            DeliveryPlan(**payload)

    def test_unknown_output_name_on_known_step_is_rejected(self):
        """Reject an output reference naming an output the step does not declare."""
        payload = _one_step_plan()
        payload["upload"]["fields"]["table_sys_id"]["output"] = "not_declared"
        with pytest.raises(ValidationError, match="output 'not_declared'"):
            DeliveryPlan(**payload)

    def test_duplicate_step_names_are_rejected(self):
        """Reject two resolution steps sharing a name."""
        payload = _one_step_plan()
        payload["resolution_steps"].append(dict(payload["resolution_steps"][0]))
        with pytest.raises(ValidationError, match="Duplicate resolution step"):
            DeliveryPlan(**payload)

    def test_secret_in_resolution_step_query_is_rejected(self):
        """Reject a secret placed in a resolution step's query string."""
        payload = _one_step_plan()
        payload["resolution_steps"][0]["query"] = {
            "key": {"source": "secret", "name": "api_key"}
        }
        with pytest.raises(ValidationError, match="may not use a secret"):
            DeliveryPlan(**payload)

    def test_secret_in_upload_query_is_rejected(self):
        """Reject a secret placed in the upload step's query string."""
        payload = _one_step_plan()
        payload["upload"]["query"] = {"key": {"source": "secret", "name": "api_key"}}
        with pytest.raises(ValidationError, match="may not use a secret"):
            DeliveryPlan(**payload)

    def test_malformed_step_output_pointer_is_rejected(self):
        """Reject a malformed JSON Pointer in a step's ``outputs`` map."""
        payload = _one_step_plan()
        payload["resolution_steps"][0]["outputs"]["sys_id"] = "result/sys_id"
        with pytest.raises(ValidationError, match="must start with"):
            DeliveryPlan(**payload)

    def test_malformed_reference_pointer_is_rejected(self):
        """Reject a malformed JSON Pointer in ``reference_pointer``."""
        payload = _upload_only_plan(reference_pointer="result~2id")
        with pytest.raises(ValidationError):
            DeliveryPlan(**payload)

    def test_unknown_value_source_tag_is_rejected(self):
        """Reject a value whose ``source`` tag is not one of the four kinds."""
        payload = _upload_only_plan(
            fields={"who": {"source": "env", "name": "HOSTNAME"}}
        )
        with pytest.raises(ValidationError):
            DeliveryPlan(**payload)

    def test_unknown_input_field_is_rejected(self):
        """Reject an input value naming a send input outside the known surface."""
        payload = _upload_only_plan(
            fields={"who": {"source": "input", "field": "hostname"}}
        )
        with pytest.raises(ValidationError):
            DeliveryPlan(**payload)


@pytest.mark.asyncio
class TestDeliveryPlanExecutor:
    """Cover plan execution against a real ``RemoteAPI`` over mocked HTTP."""

    async def test_conforms_to_bundle_uploader_protocol(self, api: RemoteAPI):
        """Expose the executor as a runtime-checkable ``BundleUploader``."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_upload_only_plan()), api)

        assert isinstance(executor, BundleUploader)

    async def test_zero_step_plan_issues_only_the_upload(
        self, api: RemoteAPI, bundle_path: Path
    ):
        """Send exactly one multipart POST carrying the literal and input fields."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_upload_only_plan()), api)
        with aioresponses() as mock:
            mock.post(
                _UPLOAD_URL,
                status=status.HTTP_201_CREATED,
                payload={"result": {"sys_id": "att-1"}},
            )
            async with api:
                result = await executor.upload_bundle(
                    source_ref="src-9",
                    bundle_path=bundle_path,
                    case_ref=None,
                    manifest=_MANIFEST,
                )
            requests = [req for reqs in mock.requests.values() for req in reqs]

        assert len(requests) == 1
        content_type = requests[0].kwargs["headers"]["Content-Type"]
        assert content_type.startswith("multipart/form-data")
        assert "boundary=" in content_type
        assert result.reference == "att-1"
        assert result.detail == {"result": {"sys_id": "att-1"}}

    async def test_zero_step_plan_omits_empty_request_maps(
        self, api: RemoteAPI, bundle_path: Path
    ):
        """Omit query parameters entirely when the plan declares none."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_upload_only_plan()), api)
        with aioresponses() as mock:
            mock.post(_UPLOAD_URL, status=status.HTTP_201_CREATED, payload={})
            async with api:
                await executor.upload_bundle(
                    source_ref="src-9",
                    bundle_path=bundle_path,
                    case_ref=None,
                    manifest=_MANIFEST,
                )
            request = next(iter(mock.requests.values()))[0]

        assert "params" not in request.kwargs

    async def test_one_step_plan_feeds_output_into_the_upload(
        self, api: RemoteAPI, bundle_path: Path
    ):
        """Issue the lookup then the upload, carrying the extracted value forward."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_one_step_plan()), api)
        with aioresponses() as mock:
            mock.post(
                _TICKET_URL,
                status=status.HTTP_200_OK,
                payload={"result": {"sys_id": "case-77", "notes": "customer data"}},
            )
            mock.post(
                _UPLOAD_URL,
                status=status.HTTP_201_CREATED,
                payload={"result": {"sys_id": "att-2"}},
            )
            async with api:
                result = await executor.upload_bundle(
                    source_ref="src-9",
                    bundle_path=bundle_path,
                    case_ref="CS0001",
                    manifest=_MANIFEST,
                )
            lookup = _recorded(mock, "ticket_details")
            fields = _multipart_fields(
                _recorded(mock, "attachment/upload").kwargs["data"]
            )
            dispositions = _file_part_dispositions(
                _recorded(mock, "attachment/upload").kwargs["data"]
            )

        assert lookup.kwargs["json"]["ticket_number"] == "CS0001"
        assert fields["table_sys_id"] == "case-77"
        assert "notes" not in fields
        assert dispositions == ['form-data; name="file"; filename="bundle.tar.gz"']
        assert result.reference == "att-2"
        assert result.detail == {"result": {"sys_id": "att-2"}}

    async def test_two_step_plan_chains_each_step_output_forward(
        self, api: RemoteAPI, bundle_path: Path
    ):
        """Forward the first step's output into the second, then both to the upload."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_two_step_plan()), api)
        with aioresponses() as mock:
            mock.post(
                _TICKET_URL,
                status=status.HTTP_200_OK,
                payload={"result": {"sys_id": "case-77"}},
            )
            mock.post(
                _ACCOUNT_URL,
                status=status.HTTP_200_OK,
                payload={"result": {"account_id": "acct-5"}},
            )
            mock.post(
                _UPLOAD_URL,
                status=status.HTTP_201_CREATED,
                payload={"result": {"sys_id": "att-3"}},
            )
            async with api:
                result = await executor.upload_bundle(
                    source_ref="src-9",
                    bundle_path=bundle_path,
                    case_ref="CS0001",
                    manifest=_MANIFEST,
                )
            account = _recorded(mock, "case_account")
            fields = _multipart_fields(
                _recorded(mock, "attachment/upload").kwargs["data"]
            )

        assert account.kwargs["json"] == {"case": "case-77"}
        assert fields["table_sys_id"] == "case-77"
        assert fields["account_id"] == "acct-5"
        assert result.reference == "att-3"

    async def test_manifest_input_is_sent_as_json(
        self, api: RemoteAPI, bundle_path: Path
    ):
        """Send the manifest as a JSON object string in its own multipart field."""
        payload = _upload_only_plan(
            fields={"manifest": {"source": "input", "field": "manifest"}},
            reference_pointer=None,
        )
        executor = DeliveryPlanExecutor(DeliveryPlan(**payload), api)
        with aioresponses() as mock:
            mock.post(_UPLOAD_URL, status=status.HTTP_201_CREATED, payload={})
            async with api:
                await executor.upload_bundle(
                    source_ref="src-9",
                    bundle_path=bundle_path,
                    case_ref=None,
                    manifest=_MANIFEST,
                )
            fields = _multipart_fields(
                next(iter(mock.requests.values()))[0].kwargs["data"]
            )

        assert fields["manifest"] == '{"bundle": "diag", "size": 12}'

    async def test_oversized_bundle_fails_before_any_request(
        self, api: RemoteAPI, bundle_path: Path
    ):
        """Reject an over-cap bundle without touching the session."""
        payload = _upload_only_plan()
        payload["max_bundle_size_mb"] = 1
        bundle_path.write_bytes(b"x" * (1024 * 1024 + 1))
        executor = DeliveryPlanExecutor(DeliveryPlan(**payload), api)

        with aioresponses() as mock:
            async with api:
                with pytest.raises(DeliveryPlanError, match="limit"):
                    await executor.upload_bundle(
                        source_ref="src-9",
                        bundle_path=bundle_path,
                        case_ref=None,
                        manifest=_MANIFEST,
                    )
            assert mock.requests == {}

    async def test_missing_case_ref_input_is_reported(
        self, api: RemoteAPI, bundle_path: Path
    ):
        """Fail with the input name when the plan needs a ``case_ref`` and none came."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_one_step_plan()), api)

        with aioresponses() as mock:
            async with api:
                with pytest.raises(DeliveryPlanError, match="case_ref"):
                    await executor.upload_bundle(
                        source_ref="src-9",
                        bundle_path=bundle_path,
                        case_ref=None,
                        manifest=_MANIFEST,
                    )
            assert mock.requests == {}

    async def test_step_without_body_but_with_outputs_fails(
        self, api: RemoteAPI, bundle_path: Path
    ):
        """Fail naming the step when a 204 leaves declared outputs unextractable."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_one_step_plan()), api)
        with aioresponses() as mock:
            mock.post(_TICKET_URL, status=status.HTTP_204_NO_CONTENT)
            async with api:
                with pytest.raises(DeliveryPlanError, match="lookup") as excinfo:
                    await executor.upload_bundle(
                        source_ref="src-9",
                        bundle_path=bundle_path,
                        case_ref="CS0001",
                        manifest=_MANIFEST,
                    )

        assert "no body" in str(excinfo.value)

    async def test_unresolvable_output_pointer_reports_step_and_pointer(
        self, api: RemoteAPI, bundle_path: Path
    ):
        """Fail naming the step and pointer without echoing the response body."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_one_step_plan()), api)
        with aioresponses() as mock:
            mock.post(
                _TICKET_URL,
                status=status.HTTP_200_OK,
                payload={"result": {"notes": "customer data"}},
            )
            async with api:
                with pytest.raises(DeliveryPlanError) as excinfo:
                    await executor.upload_bundle(
                        source_ref="src-9",
                        bundle_path=bundle_path,
                        case_ref="CS0001",
                        manifest=_MANIFEST,
                    )

        message = str(excinfo.value)
        assert "lookup" in message
        assert "/result/sys_id" in message
        assert "customer data" not in message

    async def test_boolean_output_keeps_its_json_spelling(
        self, api: RemoteAPI, bundle_path: Path
    ):
        """Forward a JSON ``true`` as ``"true"``, not Python's ``"True"``."""
        payload = _one_step_plan()
        payload["resolution_steps"][0]["outputs"] = {"eligible": "/result/eligible"}
        payload["upload"]["fields"]["table_sys_id"]["output"] = "eligible"
        executor = DeliveryPlanExecutor(DeliveryPlan(**payload), api)
        with aioresponses() as mock:
            mock.post(
                _TICKET_URL,
                status=status.HTTP_200_OK,
                payload={"result": {"eligible": True}},
            )
            mock.post(_UPLOAD_URL, status=status.HTTP_201_CREATED, payload={})
            async with api:
                await executor.upload_bundle(
                    source_ref="src-9",
                    bundle_path=bundle_path,
                    case_ref="CS0001",
                    manifest=_MANIFEST,
                )
            fields = _multipart_fields(
                _recorded(mock, "attachment/upload").kwargs["data"]
            )

        assert fields["table_sys_id"] == "true"

    async def test_non_scalar_output_pointer_is_rejected(
        self, api: RemoteAPI, bundle_path: Path
    ):
        """Fail when a declared output pointer resolves to a container."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_one_step_plan()), api)
        with aioresponses() as mock:
            mock.post(
                _TICKET_URL,
                status=status.HTTP_200_OK,
                payload={"result": {"sys_id": {"nested": "value"}}},
            )
            async with api:
                with pytest.raises(DeliveryPlanError, match="non-scalar"):
                    await executor.upload_bundle(
                        source_ref="src-9",
                        bundle_path=bundle_path,
                        case_ref="CS0001",
                        manifest=_MANIFEST,
                    )

    @pytest.mark.parametrize(
        ("http_status", "expected_exception"),
        [
            (status.HTTP_409_CONFLICT, HTTPConflictException),
            (status.HTTP_502_BAD_GATEWAY, HTTPBadGatewayException),
        ],
    )
    async def test_step_error_propagates_and_stops_the_plan(
        self,
        api: RemoteAPI,
        bundle_path: Path,
        http_status: int,
        expected_exception: type[Exception],
    ):
        """Propagate the mapped project exception and issue no further request."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_one_step_plan()), api)
        with aioresponses() as mock:
            mock.post(_TICKET_URL, status=http_status, payload={"detail": "nope"})
            async with api:
                with pytest.raises(expected_exception):
                    await executor.upload_bundle(
                        source_ref="src-9",
                        bundle_path=bundle_path,
                        case_ref="CS0001",
                        manifest=_MANIFEST,
                    )
            requests = [req for reqs in mock.requests.values() for req in reqs]

        assert len(requests) == 1

    async def test_non_json_upload_response_yields_an_empty_result(
        self, api: RemoteAPI, bundle_path: Path, caplog
    ):
        """Return an empty result and warn when a 2xx carries no JSON object."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_upload_only_plan()), api)
        with aioresponses() as mock:
            mock.post(
                _UPLOAD_URL,
                status=status.HTTP_201_CREATED,
                body="accepted",
                content_type="text/plain",
            )
            with caplog.at_level("WARNING"):
                async with api:
                    result = await executor.upload_bundle(
                        source_ref="src-9",
                        bundle_path=bundle_path,
                        case_ref=None,
                        manifest=_MANIFEST,
                    )

        assert result.reference is None
        assert result.detail is None
        assert any("NoneType" in record.getMessage() for record in caplog.records)

    async def test_list_upload_response_yields_an_empty_result(
        self, api: RemoteAPI, bundle_path: Path, caplog
    ):
        """Return an empty result and warn when the receiver answers with a list."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_upload_only_plan()), api)
        with aioresponses() as mock:
            mock.post(
                _UPLOAD_URL, status=status.HTTP_201_CREATED, payload=[{"sys_id": "x"}]
            )
            with caplog.at_level("WARNING"):
                async with api:
                    result = await executor.upload_bundle(
                        source_ref="src-9",
                        bundle_path=bundle_path,
                        case_ref=None,
                        manifest=_MANIFEST,
                    )

        assert result.reference is None
        assert result.detail is None
        assert any("list" in record.getMessage() for record in caplog.records)

    async def test_unresolvable_reference_pointer_keeps_the_detail(
        self, api: RemoteAPI, bundle_path: Path, caplog
    ):
        """Preserve the response detail while reporting no reference, with a warning."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_upload_only_plan()), api)
        with aioresponses() as mock:
            mock.post(
                _UPLOAD_URL, status=status.HTTP_201_CREATED, payload={"other": "x"}
            )
            with caplog.at_level("WARNING"):
                async with api:
                    result = await executor.upload_bundle(
                        source_ref="src-9",
                        bundle_path=bundle_path,
                        case_ref=None,
                        manifest=_MANIFEST,
                    )

        assert result.reference is None
        assert result.detail == {"other": "x"}
        assert any("/result/sys_id" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
class TestDeliveryPlanSecretRedaction:
    """Cover that plan-supplied secrets reach the wire but never the logs."""

    async def _run_one_step(self, api: RemoteAPI, bundle_path: Path, caplog) -> list:
        """Run the ServiceNow-shaped plan and return the recorded requests."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_one_step_plan()), api)
        with aioresponses() as mock:
            mock.post(
                _TICKET_URL,
                status=status.HTTP_200_OK,
                payload={"result": {"sys_id": "case-77"}},
            )
            mock.post(
                _UPLOAD_URL,
                status=status.HTTP_201_CREATED,
                payload={"result": {"sys_id": "att-2"}},
            )
            with caplog.at_level("DEBUG", logger=api.logger.name):
                async with api:
                    await executor.upload_bundle(
                        source_ref="src-9",
                        bundle_path=bundle_path,
                        case_ref="CS0001",
                        manifest=_MANIFEST,
                    )
            return [req for reqs in mock.requests.values() for req in reqs]

    async def test_header_secret_is_sent_but_masked_in_logs(
        self, api: RemoteAPI, bundle_path: Path, caplog
    ):
        """Send the real API key on the wire while the debug log shows only a mask."""
        requests = await self._run_one_step(api, bundle_path, caplog)

        messages = [record.getMessage() for record in caplog.records]
        assert any("Sending" in message for message in messages)
        assert all("real-api-key" not in message for message in messages)
        assert any("****" in message for message in messages)
        assert any(
            request.kwargs.get("headers", {}).get("x-sn-apikey") == "real-api-key"
            for request in requests
        )

    async def test_body_secret_is_sent_but_masked_in_logs(
        self, api: RemoteAPI, bundle_path: Path, caplog
    ):
        """Send the real client token in the JSON body while the log shows a mask."""
        requests = await self._run_one_step(api, bundle_path, caplog)

        messages = [record.getMessage() for record in caplog.records]
        assert all("real-client-token" not in message for message in messages)
        assert any(
            request.kwargs.get("json", {}).get("client_token") == "real-client-token"
            for request in requests
        )

    async def test_multipart_field_secret_is_sent_but_absent_from_logs(
        self, api: RemoteAPI, bundle_path: Path, caplog
    ):
        """Send the real secret in a multipart field while no log record carries it.

        This placement has no redaction context behind it -- the multipart body
        is an opaque payload the request log never expands -- so assert the
        guarantee directly on both sides: the receiver gets the real value, and
        no captured record does.
        """
        payload = _upload_only_plan(
            fields={"client_token": {"source": "secret", "name": "client_token"}},
            reference_pointer=None,
        )
        payload["secrets"] = {"client_token": "real-client-token"}
        executor = DeliveryPlanExecutor(DeliveryPlan(**payload), api)
        with aioresponses() as mock:
            mock.post(_UPLOAD_URL, status=status.HTTP_201_CREATED, payload={})
            with caplog.at_level("DEBUG", logger=api.logger.name):
                async with api:
                    await executor.upload_bundle(
                        source_ref="src-9",
                        bundle_path=bundle_path,
                        case_ref=None,
                        manifest=_MANIFEST,
                    )
            fields = _multipart_fields(
                _recorded(mock, "attachment/upload").kwargs["data"]
            )

        assert fields["client_token"] == "real-client-token"
        assert all(
            "real-client-token" not in record.getMessage() for record in caplog.records
        )

    async def test_redaction_is_released_after_the_send(
        self, api: RemoteAPI, bundle_path: Path, caplog
    ):
        """Restore the empty redaction sets once the plan finishes."""
        await self._run_one_step(api, bundle_path, caplog)

        assert api._extra_sensitive_headers.get() == frozenset()
        assert api._extra_sensitive_body_fields.get() == frozenset()
