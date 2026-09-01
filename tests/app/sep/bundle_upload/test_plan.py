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
from collections.abc import AsyncIterator
from typing import Any

import pytest
from aiohttp import MultipartWriter
from aioresponses import aioresponses
from fastapi import HTTPException, status
from pydantic import ValidationError

from app.core.exceptions import HTTPBadGatewayException, HTTPConflictException
from app.core.requests import RemoteAPI
from app.sep.bundle_upload.plan import (
    DeliveryPlan,
    DeliveryPlanError,
    DeliveryPlanExecutor,
    StepRecord,
)
from app.sep.bundle_upload.seam import BundleSource, BundleUploader

_BASE_URL = "http://localhost:8000/"
_UPLOAD_URL = "http://localhost:8000/attachment/upload"
_TICKET_URL = "http://localhost:8000/ticket_details"
_ACCOUNT_URL = "http://localhost:8000/case_account"
_PROBE_URL = "http://localhost:8000/health"
_MANIFEST: dict[str, Any] = {"bundle": "diag", "size": 12}
_PLAN_LOGGER = "app.sep.bundle_upload.plan"


@pytest.fixture(name="api")
def api_fixture() -> RemoteAPI:
    """Provide a real ``RemoteAPI`` client pointed at a local base URL."""
    return RemoteAPI(endpoint=_BASE_URL)


@pytest.fixture(name="bundle")
def bundle_fixture() -> BundleSource:
    """Provide a small in-memory bundle source."""
    content = b"bundle-bytes"
    return BundleSource(filename="bundle.tar.gz", content=content, size=len(content))


async def _chunks(content: bytes) -> AsyncIterator[bytes]:
    """Yield ``content`` one byte at a time as an upstream stream would.

    :param content: The bundle bytes to hand out in chunks.
    :return: An async iterator over single-byte chunks.
    """
    for index in range(len(content)):
        yield content[index : index + 1]


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


async def _multipart_body(payload: MultipartWriter) -> bytes:
    """Serialize a recorded multipart body, draining any streamed part.

    :param payload: The multipart body aiohttp was handed for the upload.
    :return: The encoded body, headers and boundaries included.
    """
    collected: list[bytes] = []

    class _Collector:
        async def write(self, chunk: bytes, **_kwargs: Any) -> None:
            collected.append(bytes(chunk))

    await payload.write(_Collector())
    return b"".join(collected)


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


def _probe_plan(**probe_overrides: Any) -> dict[str, Any]:
    """Return an upload-only plan payload carrying an overridable probe step.

    :param probe_overrides: Probe-step keys replacing the defaults below.
    :return: The plan payload to validate.
    """
    probe = {"path": "health"}
    probe.update(probe_overrides)
    payload = _upload_only_plan()
    payload["secrets"] = {"api_key": "real-api-key"}
    payload["probe"] = probe
    return payload


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

    def test_manifest_key_is_allowed_in_query(self):
        """Accept a manifest-key value in the query map, which rejects secrets."""
        payload = _upload_only_plan(
            query={"week": {"source": "manifest_key", "key": "report_week"}}
        )

        assert DeliveryPlan(**payload).upload.query["week"].key == "report_week"

    def test_manifest_key_without_a_key_is_rejected(self):
        """Reject a manifest-key value that names no manifest key."""
        payload = _upload_only_plan(fields={"week": {"source": "manifest_key"}})
        with pytest.raises(ValidationError):
            DeliveryPlan(**payload)


class TestProbeStepValidation:
    """Cover the probe step's narrowed value sources and same-origin path rule."""

    def test_literal_and_secret_values_are_accepted(self):
        """Accept the two sources a probe can resolve without a send in flight."""
        payload = _probe_plan(
            headers={"x-sn-apikey": {"source": "secret", "name": "api_key"}},
            query={"sysparm_limit": {"source": "literal", "value": "1"}},
        )

        plan = DeliveryPlan(**payload)

        assert plan.probe.headers["x-sn-apikey"].name == "api_key"
        assert plan.probe.query["sysparm_limit"].value == "1"

    @pytest.mark.parametrize(
        "source",
        [
            {"source": "input", "field": "case_ref"},
            {"source": "manifest_key", "key": "collected_at"},
            {"source": "output", "step": "lookup", "output": "sys_id"},
        ],
        ids=["input", "manifest_key", "output"],
    )
    def test_send_scoped_sources_are_refused(self, source: dict[str, Any]):
        """Reject every source that only a send in flight could supply."""
        payload = _probe_plan(headers={"x-probe": source})

        with pytest.raises(ValidationError, match="does not match any of the expected"):
            DeliveryPlan(**payload)

    def test_a_refused_source_fails_as_an_invalid_tag(self):
        """Refuse a send-scoped source by its tag, so no message wording is load-bearing.

        The refusal comes from the probe value type itself rather than from the
        cross-reference validator, so a caller distinguishing this rejection from
        a resolvable-but-wrong value has a stable error type to match on.
        """
        payload = _probe_plan(
            headers={"x-probe": {"source": "input", "field": "case_ref"}}
        )

        with pytest.raises(ValidationError) as exc_info:
            DeliveryPlan(**payload)

        assert exc_info.value.errors()[0]["type"] == "union_tag_invalid"

    def test_undeclared_secret_is_refused(self):
        """Reject a probe secret the plan never declares, as any other step's is."""
        payload = _probe_plan(
            headers={"x-probe": {"source": "secret", "name": "missing"}}
        )

        with pytest.raises(ValidationError, match="undefined secret 'missing'"):
            DeliveryPlan(**payload)

    def test_secret_in_the_query_map_is_refused(self):
        """Keep a probe credential out of the query string, as every other step does."""
        payload = _probe_plan(query={"key": {"source": "secret", "name": "api_key"}})

        with pytest.raises(ValidationError, match="may not use a secret"):
            DeliveryPlan(**payload)

    @pytest.mark.parametrize(
        "path",
        ["https://attacker.example/probe", "//attacker.example/probe"],
        ids=["absolute_url", "network_path_reference"],
    )
    def test_an_off_origin_path_is_refused(self, path: str):
        """Reject a path that would carry the probe's credentials to another host."""
        payload = _probe_plan(path=path)

        with pytest.raises(ValidationError, match="must be relative"):
            DeliveryPlan(**payload)

    @pytest.mark.parametrize(
        "path", ["api/now/table/x", "/api/now/table/x"], ids=["relative", "rooted"]
    )
    def test_ordinary_paths_are_accepted(self, path: str):
        """Accept both spellings of a path that stays under the plan's endpoint."""
        assert DeliveryPlan(**_probe_plan(path=path)).probe.path == path

    def test_a_plan_without_a_probe_still_validates(self):
        """Leave every already-deployed plan valid, with no probe declared."""
        plan = DeliveryPlan(**_one_step_plan())

        assert plan.probe is None


@pytest.mark.asyncio
class TestDeliveryPlanExecutor:
    """Cover plan execution against a real ``RemoteAPI`` over mocked HTTP."""

    async def test_conforms_to_bundle_uploader_protocol(self, api: RemoteAPI):
        """Expose the executor as a runtime-checkable ``BundleUploader``."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_upload_only_plan()), api)

        assert isinstance(executor, BundleUploader)

    async def test_zero_step_plan_issues_only_the_upload(
        self, api: RemoteAPI, bundle: BundleSource
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
                    bundle=bundle,
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

    async def test_streamed_bundle_reaches_the_multipart_body(self, api: RemoteAPI):
        """Carry a bundle that arrives as an async byte stream, never buffering it."""
        streamed = BundleSource(
            filename="bundle.tar.gz", content=_chunks(b"bundle-bytes"), size=12
        )
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
                    bundle=streamed,
                    case_ref=None,
                    manifest=_MANIFEST,
                )
            body = await _multipart_body(
                _recorded(mock, "attachment/upload").kwargs["data"]
            )

        assert b'filename="bundle.tar.gz"' in body
        assert b"bundle-bytes" in body
        assert result.reference == "att-1"

    async def test_zero_step_plan_omits_empty_request_maps(
        self, api: RemoteAPI, bundle: BundleSource
    ):
        """Omit query parameters entirely when the plan declares none."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_upload_only_plan()), api)
        with aioresponses() as mock:
            mock.post(_UPLOAD_URL, status=status.HTTP_201_CREATED, payload={})
            async with api:
                await executor.upload_bundle(
                    source_ref="src-9",
                    bundle=bundle,
                    case_ref=None,
                    manifest=_MANIFEST,
                )
            request = next(iter(mock.requests.values()))[0]

        assert "params" not in request.kwargs

    async def test_one_step_plan_feeds_output_into_the_upload(
        self, api: RemoteAPI, bundle: BundleSource
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
                    bundle=bundle,
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
        self, api: RemoteAPI, bundle: BundleSource
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
                    bundle=bundle,
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
        self, api: RemoteAPI, bundle: BundleSource
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
                    bundle=bundle,
                    case_ref=None,
                    manifest=_MANIFEST,
                )
            fields = _multipart_fields(
                next(iter(mock.requests.values()))[0].kwargs["data"]
            )

        assert fields["manifest"] == '{"bundle": "diag", "size": 12}'

    async def test_oversized_bundle_fails_before_any_request(self, api: RemoteAPI):
        """Reject a bundle whose stated size is over cap without touching the session."""
        payload = _upload_only_plan()
        payload["max_bundle_size_mb"] = 1
        oversized = BundleSource(
            filename="bundle.tar.gz",
            content=_chunks(b"bundle-bytes"),
            size=1024 * 1024 + 1,
        )
        executor = DeliveryPlanExecutor(DeliveryPlan(**payload), api)

        with aioresponses() as mock:
            async with api:
                with pytest.raises(DeliveryPlanError, match="limit"):
                    await executor.upload_bundle(
                        source_ref="src-9",
                        bundle=oversized,
                        case_ref=None,
                        manifest=_MANIFEST,
                    )
            assert mock.requests == {}

    async def test_missing_case_ref_input_is_reported(
        self, api: RemoteAPI, bundle: BundleSource
    ):
        """Fail with the input name when the plan needs a ``case_ref`` and none came."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_one_step_plan()), api)

        with aioresponses() as mock:
            async with api:
                with pytest.raises(DeliveryPlanError, match="case_ref"):
                    await executor.upload_bundle(
                        source_ref="src-9",
                        bundle=bundle,
                        case_ref=None,
                        manifest=_MANIFEST,
                    )
            assert mock.requests == {}

    async def test_step_without_body_but_with_outputs_fails(
        self, api: RemoteAPI, bundle: BundleSource
    ):
        """Fail naming the step when a 204 leaves declared outputs unextractable."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_one_step_plan()), api)
        with aioresponses() as mock:
            mock.post(_TICKET_URL, status=status.HTTP_204_NO_CONTENT)
            async with api:
                with pytest.raises(DeliveryPlanError, match="lookup") as excinfo:
                    await executor.upload_bundle(
                        source_ref="src-9",
                        bundle=bundle,
                        case_ref="CS0001",
                        manifest=_MANIFEST,
                    )

        assert "no body" in str(excinfo.value)

    async def test_unresolvable_output_pointer_reports_step_and_pointer(
        self, api: RemoteAPI, bundle: BundleSource
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
                        bundle=bundle,
                        case_ref="CS0001",
                        manifest=_MANIFEST,
                    )

        message = str(excinfo.value)
        assert "lookup" in message
        assert "/result/sys_id" in message
        assert "customer data" not in message

    async def test_boolean_output_keeps_its_json_spelling(
        self, api: RemoteAPI, bundle: BundleSource
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
                    bundle=bundle,
                    case_ref="CS0001",
                    manifest=_MANIFEST,
                )
            fields = _multipart_fields(
                _recorded(mock, "attachment/upload").kwargs["data"]
            )

        assert fields["table_sys_id"] == "true"

    async def test_non_scalar_output_pointer_is_rejected(
        self, api: RemoteAPI, bundle: BundleSource
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
                        bundle=bundle,
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
        bundle: BundleSource,
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
                        bundle=bundle,
                        case_ref="CS0001",
                        manifest=_MANIFEST,
                    )
            requests = [req for reqs in mock.requests.values() for req in reqs]

        assert len(requests) == 1

    async def test_non_json_upload_response_yields_an_empty_result(
        self, api: RemoteAPI, bundle: BundleSource, caplog
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
            with caplog.at_level("WARNING", logger=_PLAN_LOGGER):
                async with api:
                    result = await executor.upload_bundle(
                        source_ref="src-9",
                        bundle=bundle,
                        case_ref=None,
                        manifest=_MANIFEST,
                    )

        assert result.reference is None
        assert result.detail is None
        assert any("NoneType" in record.getMessage() for record in caplog.records)

    async def test_list_upload_response_yields_an_empty_result(
        self, api: RemoteAPI, bundle: BundleSource, caplog
    ):
        """Return an empty result and warn when the receiver answers with a list."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_upload_only_plan()), api)
        with aioresponses() as mock:
            mock.post(
                _UPLOAD_URL, status=status.HTTP_201_CREATED, payload=[{"sys_id": "x"}]
            )
            with caplog.at_level("WARNING", logger=_PLAN_LOGGER):
                async with api:
                    result = await executor.upload_bundle(
                        source_ref="src-9",
                        bundle=bundle,
                        case_ref=None,
                        manifest=_MANIFEST,
                    )

        assert result.reference is None
        assert result.detail is None
        assert any("list" in record.getMessage() for record in caplog.records)

    async def test_unresolvable_reference_pointer_keeps_the_detail(
        self, api: RemoteAPI, bundle: BundleSource, caplog
    ):
        """Preserve the response detail while reporting no reference, with a warning."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_upload_only_plan()), api)
        with aioresponses() as mock:
            mock.post(
                _UPLOAD_URL, status=status.HTTP_201_CREATED, payload={"other": "x"}
            )
            with caplog.at_level("WARNING", logger=_PLAN_LOGGER):
                async with api:
                    result = await executor.upload_bundle(
                        source_ref="src-9",
                        bundle=bundle,
                        case_ref=None,
                        manifest=_MANIFEST,
                    )

        assert result.reference is None
        assert result.detail == {"other": "x"}
        assert any("/result/sys_id" in record.getMessage() for record in caplog.records)

    async def test_manifest_key_field_resolves_from_the_send_manifest(
        self, api: RemoteAPI, bundle: BundleSource
    ):
        """Read one manifest key into a multipart field, not the whole mapping."""
        payload = _upload_only_plan(
            fields={"report_week": {"source": "manifest_key", "key": "report_week"}},
            reference_pointer=None,
        )
        executor = DeliveryPlanExecutor(DeliveryPlan(**payload), api)
        with aioresponses() as mock:
            mock.post(_UPLOAD_URL, status=status.HTTP_201_CREATED, payload={})
            async with api:
                await executor.upload_bundle(
                    source_ref="src-9",
                    bundle=bundle,
                    case_ref=None,
                    manifest={"report_week": "2026-W29", "size": 12},
                )
            fields = _multipart_fields(
                _recorded(mock, "attachment/upload").kwargs["data"]
            )

        assert fields == {"report_week": "2026-W29"}

    async def test_manifest_key_missing_raises_naming_the_key(
        self, api: RemoteAPI, bundle: BundleSource
    ):
        """Fail the send when the manifest carries no such key."""
        payload = _upload_only_plan(
            fields={"report_week": {"source": "manifest_key", "key": "report_week"}},
            reference_pointer=None,
        )
        executor = DeliveryPlanExecutor(DeliveryPlan(**payload), api)
        async with api:
            with pytest.raises(DeliveryPlanError, match="report_week"):
                await executor.upload_bundle(
                    source_ref="src-9",
                    bundle=bundle,
                    case_ref=None,
                    manifest={"size": 12},
                )

    async def test_manifest_key_non_scalar_raises_naming_the_key(
        self, api: RemoteAPI, bundle: BundleSource
    ):
        """Fail the send when the manifest value is a container, not a scalar."""
        payload = _upload_only_plan(
            fields={"report_week": {"source": "manifest_key", "key": "report_week"}},
            reference_pointer=None,
        )
        executor = DeliveryPlanExecutor(DeliveryPlan(**payload), api)
        async with api:
            with pytest.raises(DeliveryPlanError, match="report_week"):
                await executor.upload_bundle(
                    source_ref="src-9",
                    bundle=bundle,
                    case_ref=None,
                    manifest={"report_week": {"nested": "value"}},
                )

    async def test_manifest_key_spells_scalars_the_json_way(
        self, api: RemoteAPI, bundle: BundleSource
    ):
        """Spell a boolean and a number as the receiver's JSON wrote them."""
        payload = _upload_only_plan(
            fields={
                "flagged": {"source": "manifest_key", "key": "flagged"},
                "count": {"source": "manifest_key", "key": "count"},
            },
            reference_pointer=None,
        )
        executor = DeliveryPlanExecutor(DeliveryPlan(**payload), api)
        with aioresponses() as mock:
            mock.post(_UPLOAD_URL, status=status.HTTP_201_CREATED, payload={})
            async with api:
                await executor.upload_bundle(
                    source_ref="src-9",
                    bundle=bundle,
                    case_ref=None,
                    manifest={"flagged": True, "count": 3},
                )
            fields = _multipart_fields(
                _recorded(mock, "attachment/upload").kwargs["data"]
            )

        assert fields == {"flagged": "true", "count": "3"}

    async def test_upload_refuses_to_follow_redirects(
        self, api: RemoteAPI, bundle: BundleSource
    ):
        """Forbid redirect following so a credential body is never replayed."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_upload_only_plan()), api)
        with aioresponses() as mock:
            mock.post(_UPLOAD_URL, status=status.HTTP_201_CREATED, payload={})
            async with api:
                await executor.upload_bundle(
                    source_ref="src-9",
                    bundle=bundle,
                    case_ref=None,
                    manifest=_MANIFEST,
                )
            request = _recorded(mock, "attachment/upload")

        assert request.kwargs["allow_redirects"] is False

    async def test_resolution_step_refuses_to_follow_redirects(
        self, api: RemoteAPI, bundle: BundleSource
    ):
        """Forbid redirect following on the steps that carry secret headers."""
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
            async with api:
                await executor.upload_bundle(
                    source_ref="src-9",
                    bundle=bundle,
                    case_ref="CS0001",
                    manifest=_MANIFEST,
                )
            lookup = _recorded(mock, "ticket_details")

        assert lookup.kwargs["allow_redirects"] is False

    async def test_upload_raises_on_a_redirect_instead_of_reporting_success(
        self, api: RemoteAPI, bundle: BundleSource
    ):
        """Fail loudly when the receiver answers the upload with a redirect."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_upload_only_plan()), api)
        with aioresponses() as mock:
            mock.post(
                _UPLOAD_URL,
                status=status.HTTP_307_TEMPORARY_REDIRECT,
                body="",
                content_type="text/html",
                headers={"Location": "http://localhost:8000/attachment/upload/"},
            )
            async with api:
                with pytest.raises(HTTPException) as exc_info:
                    await executor.upload_bundle(
                        source_ref="src-9",
                        bundle=bundle,
                        case_ref=None,
                        manifest=_MANIFEST,
                    )

        assert exc_info.value.status_code == status.HTTP_307_TEMPORARY_REDIRECT

    async def test_upload_raises_on_a_redirect_carrying_a_json_body(
        self, api: RemoteAPI, bundle: BundleSource
    ):
        """Fail loudly on a redirect even when it carries a parseable JSON body."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_upload_only_plan()), api)
        with aioresponses() as mock:
            mock.post(
                _UPLOAD_URL,
                status=status.HTTP_308_PERMANENT_REDIRECT,
                payload={"detail": "moved"},
                headers={"Location": "http://localhost:8000/attachment/upload/"},
            )
            async with api:
                with pytest.raises(HTTPException) as exc_info:
                    await executor.upload_bundle(
                        source_ref="src-9",
                        bundle=bundle,
                        case_ref=None,
                        manifest=_MANIFEST,
                    )

        assert exc_info.value.status_code == status.HTTP_308_PERMANENT_REDIRECT


@pytest.mark.asyncio
class TestDeliveryPlanSecretRedaction:
    """Cover that plan-supplied secrets reach the wire but never the logs."""

    async def _run_one_step(self, api: RemoteAPI, bundle: BundleSource, caplog) -> list:
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
                        bundle=bundle,
                        case_ref="CS0001",
                        manifest=_MANIFEST,
                    )
            return [req for reqs in mock.requests.values() for req in reqs]

    async def test_header_secret_is_sent_but_masked_in_logs(
        self, api: RemoteAPI, bundle: BundleSource, caplog
    ):
        """Send the real API key on the wire while the debug log shows only a mask."""
        requests = await self._run_one_step(api, bundle, caplog)

        messages = [record.getMessage() for record in caplog.records]
        assert any("Sending" in message for message in messages)
        assert all("real-api-key" not in message for message in messages)
        assert any("****" in message for message in messages)
        assert any(
            request.kwargs.get("headers", {}).get("x-sn-apikey") == "real-api-key"
            for request in requests
        )

    async def test_body_secret_is_sent_but_masked_in_logs(
        self, api: RemoteAPI, bundle: BundleSource, caplog
    ):
        """Send the real client token in the JSON body while the log shows a mask."""
        requests = await self._run_one_step(api, bundle, caplog)

        messages = [record.getMessage() for record in caplog.records]
        assert all("real-client-token" not in message for message in messages)
        assert any(
            request.kwargs.get("json", {}).get("client_token") == "real-client-token"
            for request in requests
        )

    async def test_multipart_field_secret_is_sent_but_absent_from_logs(
        self, api: RemoteAPI, bundle: BundleSource, caplog
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
                        bundle=bundle,
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
        self, api: RemoteAPI, bundle: BundleSource, caplog
    ):
        """Restore the empty redaction sets once the plan finishes."""
        await self._run_one_step(api, bundle, caplog)

        assert api._extra_sensitive_headers.get() == frozenset()
        assert api._extra_sensitive_body_fields.get() == frozenset()


@pytest.mark.asyncio
class TestDeliveryPlanExecutorStepObserver:
    """Cover the optional per-step observer the send log records progress through."""

    async def test_observer_sees_running_then_success_with_outputs(
        self, api: RemoteAPI, bundle: BundleSource
    ):
        """Report each resolution step twice: once entering, once with its outputs."""
        records: list[StepRecord] = []
        executor = DeliveryPlanExecutor(
            DeliveryPlan(**_one_step_plan()), api, step_observer=records.append
        )
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
                await executor.upload_bundle(
                    source_ref="src-9",
                    bundle=bundle,
                    case_ref="CS0001",
                    manifest=_MANIFEST,
                )

        assert [(record.name, record.status) for record in records] == [
            ("lookup", "running"),
            ("lookup", "success"),
        ]
        assert records[0].outputs is None
        assert records[1].outputs == {"sys_id": "case-77"}

    async def test_observer_never_receives_a_response_body(
        self, api: RemoteAPI, bundle: BundleSource
    ):
        """Hand the observer declared outputs only, never the raw step response."""
        records: list[StepRecord] = []
        executor = DeliveryPlanExecutor(
            DeliveryPlan(**_one_step_plan()), api, step_observer=records.append
        )
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
                await executor.upload_bundle(
                    source_ref="src-9",
                    bundle=bundle,
                    case_ref="CS0001",
                    manifest=_MANIFEST,
                )

        assert all("customer data" not in str(record.outputs) for record in records)

    async def test_a_failed_step_leaves_its_running_record_as_the_last_one(
        self, api: RemoteAPI, bundle: BundleSource
    ):
        """Leave the failing step recorded as still running so the log names it."""
        records: list[StepRecord] = []
        executor = DeliveryPlanExecutor(
            DeliveryPlan(**_one_step_plan()), api, step_observer=records.append
        )
        with aioresponses() as mock:
            mock.post(_TICKET_URL, status=status.HTTP_409_CONFLICT)
            async with api:
                with pytest.raises(HTTPConflictException):
                    await executor.upload_bundle(
                        source_ref="src-9",
                        bundle=bundle,
                        case_ref="CS0001",
                        manifest=_MANIFEST,
                    )

        assert [(record.name, record.status) for record in records] == [
            ("lookup", "running")
        ]

    async def test_the_upload_step_is_not_observed(
        self, api: RemoteAPI, bundle: BundleSource
    ):
        """Leave the terminal upload out of the step records; its result stands alone."""
        records: list[StepRecord] = []
        executor = DeliveryPlanExecutor(
            DeliveryPlan(**_upload_only_plan()), api, step_observer=records.append
        )
        with aioresponses() as mock:
            mock.post(
                _UPLOAD_URL,
                status=status.HTTP_201_CREATED,
                payload={"result": {"sys_id": "att-2"}},
            )
            async with api:
                await executor.upload_bundle(
                    source_ref="src-9",
                    bundle=bundle,
                    case_ref="CS0001",
                    manifest=_MANIFEST,
                )

        assert records == []


@pytest.mark.asyncio
class TestDeliveryPlanProbe:
    """Cover issuing the plan's declared probe without sending a bundle."""

    async def test_probe_issues_one_get_carrying_the_resolved_secret(
        self, api: RemoteAPI
    ):
        """Issue one request carrying the plan's own credential to the receiver."""
        executor = DeliveryPlanExecutor(
            DeliveryPlan(
                **_probe_plan(
                    headers={"x-sn-apikey": {"source": "secret", "name": "api_key"}}
                )
            ),
            api,
        )
        with aioresponses() as mock:
            mock.get(_PROBE_URL, status=status.HTTP_200_OK, payload={"result": []})
            async with api:
                await executor.probe()

            requests = [req for reqs in mock.requests.values() for req in reqs]

        assert len(requests) == 1
        assert requests[0].kwargs["headers"]["x-sn-apikey"] == "real-api-key"

    async def test_probe_sends_the_declared_query_parameters(self, api: RemoteAPI):
        """Carry the probe's literal query pairs so a receiver can bound its answer."""
        executor = DeliveryPlanExecutor(
            DeliveryPlan(
                **_probe_plan(
                    query={"sysparm_limit": {"source": "literal", "value": "1"}}
                )
            ),
            api,
        )
        with aioresponses() as mock:
            mock.get(
                f"{_PROBE_URL}?sysparm_limit=1",
                status=status.HTTP_200_OK,
                payload={"result": []},
            )
            async with api:
                await executor.probe()

            requests = [req for reqs in mock.requests.values() for req in reqs]

        assert requests[0].kwargs["params"] == {"sysparm_limit": "1"}

    async def test_probe_without_a_query_map_omits_the_params_argument(
        self, api: RemoteAPI
    ):
        """Drop an empty query map rather than sending an empty params dict."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_probe_plan()), api)
        with aioresponses() as mock:
            mock.get(_PROBE_URL, status=status.HTTP_200_OK, payload={})
            async with api:
                await executor.probe()

            requests = [req for reqs in mock.requests.values() for req in reqs]

        assert "params" not in requests[0].kwargs

    async def test_probe_sends_no_body_and_refuses_to_follow_redirects(
        self, api: RemoteAPI
    ):
        """Issue a bodiless GET that never replays the credential to a new origin."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_probe_plan()), api)
        with aioresponses() as mock:
            mock.get(_PROBE_URL, status=status.HTTP_200_OK, payload={})
            async with api:
                await executor.probe()

            requests = [req for reqs in mock.requests.values() for req in reqs]

        assert requests[0].kwargs["allow_redirects"] is False
        assert requests[0].kwargs.get("json") is None
        assert requests[0].kwargs.get("data") is None

    async def test_probe_raises_on_a_redirect_instead_of_reporting_success(
        self, api: RemoteAPI
    ):
        """Fail loudly when the receiver answers the probe with a redirect."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_probe_plan()), api)
        with aioresponses() as mock:
            mock.get(
                _PROBE_URL,
                status=status.HTTP_307_TEMPORARY_REDIRECT,
                headers={"Location": "http://elsewhere.example/health"},
            )
            async with api:
                with pytest.raises(HTTPException) as exc_info:
                    await executor.probe()

        assert exc_info.value.status_code == status.HTTP_307_TEMPORARY_REDIRECT

    async def test_probe_secret_is_sent_but_masked_in_logs(
        self, api: RemoteAPI, caplog
    ):
        """Send the real API key on the wire while the debug log shows only a mask."""
        executor = DeliveryPlanExecutor(
            DeliveryPlan(
                **_probe_plan(
                    headers={"x-sn-apikey": {"source": "secret", "name": "api_key"}}
                )
            ),
            api,
        )
        with aioresponses() as mock:
            mock.get(_PROBE_URL, status=status.HTTP_200_OK, payload={})
            with caplog.at_level("DEBUG", logger=api.logger.name):
                async with api:
                    await executor.probe()

        messages = [record.getMessage() for record in caplog.records]
        assert any("****" in message for message in messages)
        assert all("real-api-key" not in message for message in messages)

    async def test_probe_without_a_declared_step_raises(self, api: RemoteAPI):
        """Refuse to guess a probe request for a plan that declares none."""
        executor = DeliveryPlanExecutor(DeliveryPlan(**_upload_only_plan()), api)

        with pytest.raises(DeliveryPlanError, match="declares no probe step"):
            await executor.probe()

    async def test_probe_runs_none_of_the_plans_resolution_steps(self, api: RemoteAPI):
        """Leave a mutating resolution step unrun, reaching only the probe path."""
        payload = _one_step_plan()
        payload["probe"] = {"path": "health"}
        executor = DeliveryPlanExecutor(DeliveryPlan(**payload), api)
        with aioresponses() as mock:
            mock.get(_PROBE_URL, status=status.HTTP_200_OK, payload={})
            async with api:
                await executor.probe()

            requested = [str(key[1]) for key in mock.requests]

        assert requested == [_PROBE_URL]
