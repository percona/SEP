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

"""Describe and execute a config-driven bundle-delivery plan.

A delivery plan is an ordered list of HTTP resolution steps followed by exactly
one terminal multipart upload step that carries the bundle file. The schema is
linear by construction: paths are literal strings, every value comes from one of
five typed sources (a literal, a send input, a named secret, an earlier step's
extracted output, or one key of the send's manifest), and no conditional, loop,
or templating construct exists.
:class:`DeliveryPlanExecutor` runs a plan over a
:class:`~app.core.requests.remote_api.RemoteAPI` transport and satisfies the
:class:`~app.sep.bundle_upload.seam.BundleUploader` protocol.

Resolution-step responses are read only for the outputs the plan declares and are
then discarded -- they may carry data the caller must neither retain nor return.
This module lives in ``app.sep`` but imports only from ``app.core`` and no other
``app.sep`` module, keeping it promotable to core if a second service ever
becomes a real consumer.
"""

__all__ = [
    "DeliveryPlan",
    "DeliveryPlanError",
    "DeliveryPlanExecutor",
    "InputValue",
    "LiteralValue",
    "ManifestValue",
    "PlanValue",
    "ResolutionStep",
    "SecretValue",
    "StepOutputValue",
    "UploadStep",
]

import logging
from collections.abc import Collection, Mapping
from typing import Annotated, Any, Literal, Self

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator, PositiveInt, SecretStr

from app.core.requests.remote_api import RemoteAPI
from app.core.utils import json_serializer, remove_falsy_values_from_dict
from app.core.utils.fields import CredentialHttpUrl, JsonPointerStr, NonEmptyStr
from app.core.utils.json_pointer import (
    JsonPointerResolutionError,
    resolve_json_pointer,
)
from app.sep.bundle_upload.seam import BundleSource, UploadResult

logger = logging.getLogger(__name__)

_BYTES_PER_MIB = 1024 * 1024

#: The value map whose contents land in the query string, where secrets are
#: rejected because query strings are logged, cached and proxied unredacted.
_QUERY_MAP = "query"


class LiteralValue(BaseModel):
    """Provide a constant value written into the plan.

    :param source: The discriminator tag, always ``"literal"``.
    :param value: The constant sent as-is.
    """

    source: Literal["literal"]
    value: str


class InputValue(BaseModel):
    """Provide a value taken from the send inputs.

    :param source: The discriminator tag, always ``"input"``.
    :param field: Which send input to read.
    """

    source: Literal["input"]
    field: Literal["source_ref", "case_ref", "manifest"]


class SecretValue(BaseModel):
    """Provide a value taken from the plan's named secrets.

    :param source: The discriminator tag, always ``"secret"``.
    :param name: The key into :attr:`DeliveryPlan.secrets`.
    """

    source: Literal["secret"]
    name: NonEmptyStr


class StepOutputValue(BaseModel):
    """Provide a value extracted from an earlier resolution step's response.

    :param source: The discriminator tag, always ``"output"``.
    :param step: The name of the resolution step that produced the value.
    :param output: The output name that step declares.
    """

    source: Literal["output"]
    step: NonEmptyStr
    output: NonEmptyStr


class ManifestValue(BaseModel):
    """Provide a value read from one key of the send's manifest.

    Unlike an ``input`` value naming the whole manifest, which reaches the
    receiver as one JSON string, this addresses a single key so a plan can send
    per-send scalars as their own fields. Whether the key is present is knowable
    only at send time, so the plan validator cross-references nothing here and a
    missing or non-scalar key fails the send.

    :param source: The discriminator tag, always ``"manifest_key"``.
    :param key: The manifest key to read.
    """

    source: Literal["manifest_key"]
    key: NonEmptyStr


#: One configured value, tagged by the ``source`` it is drawn from.
PlanValue = Annotated[
    LiteralValue | InputValue | SecretValue | StepOutputValue | ManifestValue,
    Field(discriminator="source"),
]


class ResolutionStep(BaseModel):
    """Describe one HTTP request whose response feeds later steps.

    :param name: The step's name, unique within the plan and cited by ``output``
        values.
    :param method: The HTTP method to issue.
    :param path: The request path, resolved against the plan endpoint.
    :param headers: Request headers keyed by header name.
    :param query: Query-string parameters keyed by parameter name.
    :param body: A flat JSON object body keyed by field name.
    :param outputs: JSON Pointers into the response, keyed by output name.
    """

    name: NonEmptyStr
    method: Literal["GET", "POST"]
    path: NonEmptyStr
    headers: dict[str, PlanValue] = {}
    query: dict[str, PlanValue] = {}
    body: dict[str, PlanValue] = {}
    outputs: dict[str, JsonPointerStr] = {}


class UploadStep(BaseModel):
    """Describe the terminal multipart request that carries the bundle.

    :param path: The request path, resolved against the plan endpoint.
    :param headers: Request headers keyed by header name.
    :param query: Query-string parameters keyed by parameter name.
    :param fields: Scalar multipart form fields keyed by field name.
    :param file_field: The multipart field name carrying the bundle file.
    :param file_content_type: The Content-Type of the bundle file part.
    :param reference_pointer: A JSON Pointer into the upload response addressing
        the value to surface as the upload reference; ``None`` extracts none.
    """

    path: NonEmptyStr
    headers: dict[str, PlanValue] = {}
    query: dict[str, PlanValue] = {}
    fields: dict[str, PlanValue] = {}
    file_field: NonEmptyStr = "file"
    file_content_type: NonEmptyStr = "application/octet-stream"
    reference_pointer: JsonPointerStr | None = None


def _check_value(
    value: PlanValue,
    *,
    where: str,
    secrets: Collection[str],
    available_outputs: Mapping[str, Collection[str]],
    allow_secret: bool,
) -> None:
    """Check one configured value against what the plan can actually supply.

    :param value: The typed value to check.
    :param where: A label naming the value's position, used in error messages.
    :param secrets: The secret names the plan declares.
    :param available_outputs: Output names keyed by the resolution step that
        declares them, restricted to steps running before this value's own step.
    :param allow_secret: Whether a secret may appear in this position.
    :raises ValueError: When the value cites an undeclared secret, an unknown or
        not-yet-run step, an output that step does not declare, or places a
        secret where secrets are not allowed.
    """
    if isinstance(value, SecretValue):
        if not allow_secret:
            raise ValueError(
                f"{where} may not use a secret: query strings reach logs, "
                f"caches and proxies unredacted."
            )
        if value.name not in secrets:
            raise ValueError(f"{where} references undefined secret {value.name!r}.")
    elif isinstance(value, StepOutputValue):
        outputs = available_outputs.get(value.step)
        if outputs is None:
            raise ValueError(
                f"{where} references step {value.step!r}, which is not declared "
                f"earlier in the plan."
            )
        if value.output not in outputs:
            raise ValueError(
                f"{where} references output {value.output!r}, which step "
                f"{value.step!r} does not declare."
            )


def _check_value_maps(
    maps: Mapping[str, Mapping[str, PlanValue]],
    *,
    where_prefix: str,
    secrets: Collection[str],
    available_outputs: Mapping[str, Collection[str]],
) -> None:
    """Check every configured value a step declares.

    :param maps: The step's value maps keyed by map name.
    :param where_prefix: A label naming the step, used in error messages.
    :param secrets: The secret names the plan declares.
    :param available_outputs: Output names keyed by the resolution step that
        declares them, restricted to steps running before this one.
    :raises ValueError: When a value cites something the plan cannot supply.
    """
    for map_name, values in maps.items():
        for key, value in values.items():
            _check_value(
                value,
                where=f"{where_prefix} {map_name}[{key!r}]",
                secrets=secrets,
                available_outputs=available_outputs,
                allow_secret=map_name != _QUERY_MAP,
            )


class DeliveryPlan(BaseModel):
    """Describe a complete bundle-delivery configuration.

    :param endpoint: The receiver base URL every step's ``path`` is relative to.
        The executor issues requests through the transport client it is handed,
        so whoever builds that client is responsible for pointing it here.
    :param max_bundle_size_mb: The largest bundle the plan will send, in
        mebibytes; a larger bundle fails before any request is issued.
    :param secrets: Credential values keyed by the name secret values cite.
    :param resolution_steps: Steps executed in declaration order before the
        upload; empty for a plan that uploads directly.
    :param upload: The terminal step that carries the bundle file.
    """

    endpoint: CredentialHttpUrl
    max_bundle_size_mb: PositiveInt = 30
    secrets: dict[str, SecretStr] = {}
    resolution_steps: list[ResolutionStep] = []
    upload: UploadStep

    @model_validator(mode="after")
    def _check_cross_references(self) -> Self:
        """Reject a plan whose cross-references cannot resolve at run time.

        :return: The validated plan.
        :raises ValueError: When two steps share a name, or a configured value
            cites an undeclared secret, a step that does not run before it, an
            output that step does not declare, or places a secret in a query
            string.
        """
        available = {}
        for step in self.resolution_steps:
            if step.name in available:
                raise ValueError(f"Duplicate resolution step name {step.name!r}.")
            _check_value_maps(
                {"headers": step.headers, _QUERY_MAP: step.query, "body": step.body},
                where_prefix=f"Resolution step {step.name!r}",
                secrets=self.secrets,
                available_outputs=available,
            )
            available[step.name] = frozenset(step.outputs)
        _check_value_maps(
            {
                "headers": self.upload.headers,
                _QUERY_MAP: self.upload.query,
                "fields": self.upload.fields,
            },
            where_prefix="Upload step",
            secrets=self.secrets,
            available_outputs=available,
        )
        return self


class DeliveryPlanError(Exception):
    """Signal that a delivery plan cannot be carried out as configured."""


def _secret_valued_keys(values: Mapping[str, PlanValue]) -> list[str]:
    """Return the keys of a value map whose values come from a named secret.

    :param values: A configured value map keyed by header or field name.
    :return: The keys whose resolved values must be masked in the request log.
    """
    return [key for key, value in values.items() if isinstance(value, SecretValue)]


def _as_scalar(value: Any) -> str | None:
    """Return ``value`` in its JSON spelling when it is a scalar, else ``None``.

    A boolean renders as ``"true"`` / ``"false"`` rather than Python's ``"True"``
    / ``"False"``, so a value read out of a JSON response reaches the receiver
    spelled the way that receiver wrote it.

    :param value: The value a JSON Pointer addressed.
    :return: The scalar as a string, or ``None`` for ``null`` and containers.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str | int | float):
        return str(value)
    return None


class DeliveryPlanExecutor:
    """Run a :class:`DeliveryPlan` over a ``RemoteAPI`` transport.

    Satisfies the :class:`~app.sep.bundle_upload.seam.BundleUploader`
    protocol: issue the plan's resolution steps in declaration order, then send
    the bundle in the terminal multipart upload step.
    """

    def __init__(self, plan: DeliveryPlan, api: RemoteAPI) -> None:
        """Bind the plan to the transport that will carry its requests.

        :param plan: The validated delivery plan to run.
        :param api: The remote API client every request is issued through.
        """
        self._plan = plan
        self._api = api

    async def upload_bundle(
        self,
        *,
        source_ref: str,
        bundle: BundleSource,
        case_ref: str | None,
        manifest: Mapping[str, Any],
    ) -> UploadResult:
        """Run the plan and upload ``bundle``.

        :param source_ref: An opaque reference string identifying the upload's
            origin.
        :param bundle: The bundle bytes and the metadata describing them.
        :param case_ref: An optional case reference, or ``None`` to omit it.
        :param manifest: The bundle manifest sent alongside the file.
        :return: The extracted upload reference and the response detail; both
            are ``None`` when the receiver answers with a non-mapping body.
        :raises DeliveryPlanError: When the bundle exceeds the configured size
            cap, the plan cites a send input the caller did not supply, or a
            declared output cannot be extracted from a step's response.
        :raises HTTPException: Propagates the project exception ``RemoteAPI``
            raises for an upstream error status.
        """
        self._check_bundle_size(bundle.size)
        inputs = {
            "source_ref": source_ref,
            "case_ref": case_ref,
            "manifest": json_serializer(manifest),
        }
        outputs = {}
        for step in self._plan.resolution_steps:
            outputs[step.name] = await self._run_resolution_step(
                step, inputs, outputs, manifest
            )
        return await self._run_upload_step(bundle, inputs, outputs, manifest)

    def _check_bundle_size(self, size: int) -> None:
        """Reject an over-cap bundle before the transport is touched.

        :param size: The bundle's size in bytes, as stated by its producer.
        :raises DeliveryPlanError: When the size exceeds ``max_bundle_size_mb``.
        """
        if size > self._plan.max_bundle_size_mb * _BYTES_PER_MIB:
            raise DeliveryPlanError(
                f"Bundle is {size} bytes, above the configured "
                f"{self._plan.max_bundle_size_mb} MiB limit."
            )

    def _resolve_value(
        self,
        value: PlanValue,
        inputs: Mapping[str, str | None],
        outputs: Mapping[str, Mapping[str, str]],
        manifest: Mapping[str, Any],
    ) -> str:
        """Resolve one configured value to the string sent over the wire.

        :param value: The typed value to resolve.
        :param inputs: The send inputs keyed by their plan-facing names.
        :param outputs: Extracted outputs keyed by step then output name.
        :param manifest: The send's manifest, read key-wise by manifest values.
        :return: The resolved string.
        :raises DeliveryPlanError: When the value cites a send input the caller
            did not supply, or a manifest key the send did not carry as a
            scalar.
        """
        if isinstance(value, LiteralValue):
            return value.value
        if isinstance(value, SecretValue):
            return self._plan.secrets[value.name].get_secret_value()
        if isinstance(value, StepOutputValue):
            return outputs[value.step][value.output]
        if isinstance(value, ManifestValue):
            if value.key not in manifest:
                raise DeliveryPlanError(
                    f"The plan reads manifest key {value.key!r}, which this "
                    f"send's manifest does not carry."
                )
            scalar = _as_scalar(manifest[value.key])
            if scalar is None:
                raise DeliveryPlanError(
                    f"The plan reads manifest key {value.key!r}, whose value is "
                    f"not a scalar."
                )
            return scalar
        resolved = inputs[value.field]
        if resolved is None:
            raise DeliveryPlanError(
                f"The plan uses the {value.field!r} send input, which the "
                f"caller did not supply."
            )
        return resolved

    def _resolve_map(
        self,
        values: Mapping[str, PlanValue],
        inputs: Mapping[str, str | None],
        outputs: Mapping[str, Mapping[str, str]],
        manifest: Mapping[str, Any],
    ) -> dict[str, str]:
        """Resolve a whole configured value map.

        :param values: The configured value map to resolve.
        :param inputs: The send inputs keyed by their plan-facing names.
        :param outputs: Extracted outputs keyed by step then output name.
        :param manifest: The send's manifest, read key-wise by manifest values.
        :return: The resolved strings keyed by the map's own keys.
        :raises DeliveryPlanError: When a value cites a send input the caller
            did not supply, or a manifest key the send did not carry as a
            scalar.
        """
        return {
            key: self._resolve_value(value, inputs, outputs, manifest)
            for key, value in values.items()
        }

    async def _run_resolution_step(
        self,
        step: ResolutionStep,
        inputs: Mapping[str, str | None],
        outputs: Mapping[str, Mapping[str, str]],
        manifest: Mapping[str, Any],
    ) -> dict[str, str]:
        """Issue one resolution step and extract the outputs it declares.

        :param step: The resolution step to run.
        :param inputs: The send inputs keyed by their plan-facing names.
        :param outputs: Outputs extracted by the steps that ran before this one.
        :param manifest: The send's manifest, read key-wise by manifest values.
        :return: This step's extracted outputs keyed by output name.
        :raises DeliveryPlanError: When a configured value cites a missing send
            input or manifest key, the response carries no body while outputs
            are declared, or a pointer fails to address a scalar.
        :raises HTTPException: Propagates the project exception ``RemoteAPI``
            raises for an upstream error status.
        """
        request_kwargs = remove_falsy_values_from_dict(
            {
                "headers": self._resolve_map(step.headers, inputs, outputs, manifest),
                "params": self._resolve_map(step.query, inputs, outputs, manifest),
                "json": self._resolve_map(step.body, inputs, outputs, manifest),
            }
        )
        logger.debug("Delivery plan: running resolution step %r.", step.name)
        with (
            self._api.redact_headers(_secret_valued_keys(step.headers)),
            self._api.redact_body_fields(_secret_valued_keys(step.body)),
        ):
            try:
                response = await self._api.request(
                    step.method,
                    step.path,
                    allow_redirects=False,
                    **request_kwargs,
                )
            except HTTPException as err:
                logger.warning(
                    "Delivery plan: resolution step %r failed with status %s.",
                    step.name,
                    err.status_code,
                )
                raise
        return self._extract_outputs(step, response)

    def _extract_outputs(
        self,
        step: ResolutionStep,
        response: dict[str, Any] | list[dict[str, Any]] | None,
    ) -> dict[str, str]:
        """Extract a step's declared outputs, then let the response go.

        :param step: The step whose ``outputs`` pointers are applied.
        :param response: The parsed response body, or ``None`` on HTTP 204.
        :return: The extracted values as strings, keyed by output name.
        :raises DeliveryPlanError: When outputs are declared but the response
            carries no body, or a pointer fails to address a scalar. The message
            names the step and pointer and never echoes the response.
        """
        if not step.outputs:
            return {}
        if response is None:
            raise DeliveryPlanError(
                f"Resolution step {step.name!r} declares outputs but the "
                f"response carried no body."
            )
        extracted = {}
        for name, pointer in step.outputs.items():
            try:
                addressed = resolve_json_pointer(response, pointer)
            except JsonPointerResolutionError as err:
                raise DeliveryPlanError(
                    f"Resolution step {step.name!r} output {name!r} pointer "
                    f"{pointer!r} did not resolve: {err}"
                ) from None
            scalar = _as_scalar(addressed)
            if scalar is None:
                raise DeliveryPlanError(
                    f"Resolution step {step.name!r} output {name!r} pointer "
                    f"{pointer!r} addressed a non-scalar value."
                )
            extracted[name] = scalar
        return extracted

    async def _run_upload_step(
        self,
        bundle: BundleSource,
        inputs: Mapping[str, str | None],
        outputs: Mapping[str, Mapping[str, str]],
        manifest: Mapping[str, Any],
    ) -> UploadResult:
        """Send the bundle in the plan's terminal multipart step.

        The bundle's content is handed to the transport as it arrived, so a
        handle or an async iterator streams rather than being buffered. Only the
        headers need masking here: the multipart body is an opaque payload the
        request log never expands.

        Redirects are not followed. A receiver that answers a credential-bearing
        request with a redirect would have the body replayed to the new
        location, which may downgrade to plaintext; failing on the redirect
        status surfaces the misconfiguration instead of leaking the credential.

        :param bundle: The bundle bytes and the metadata describing them.
        :param inputs: The send inputs keyed by their plan-facing names.
        :param outputs: Outputs extracted by the resolution steps.
        :param manifest: The send's manifest, read key-wise by manifest values.
        :return: The extracted upload reference and the response detail.
        :raises DeliveryPlanError: When a configured value cites a send input
            the caller did not supply, or a manifest key the send did not carry
            as a scalar.
        :raises HTTPException: Propagates the project exception ``RemoteAPI``
            raises for an upstream error status, including a redirect the
            receiver answered with.
        """
        step = self._plan.upload
        request_kwargs = remove_falsy_values_from_dict(
            {
                "headers": self._resolve_map(step.headers, inputs, outputs, manifest),
                "params": self._resolve_map(step.query, inputs, outputs, manifest),
                "fields": self._resolve_map(step.fields, inputs, outputs, manifest),
            }
        )
        with self._api.redact_headers(_secret_valued_keys(step.headers)):
            response = await self._api.upload(
                step.path,
                files={
                    step.file_field: (
                        bundle.filename,
                        bundle.content,
                        step.file_content_type,
                    )
                },
                allow_redirects=False,
                **request_kwargs,
            )
        return self._build_result(response)

    def _build_result(
        self, response: dict[str, Any] | list[dict[str, Any]] | None
    ) -> UploadResult:
        """Build the upload result from the receiver's response.

        A response that is not a JSON object -- a non-JSON ``2xx`` body or a
        list -- yields an empty result and a warning rather than an error, as
        does a reference pointer that fails to address a scalar: the bundle has
        already landed, so failing here would only invite a duplicate re-send.

        :param response: The parsed upload response.
        :return: The extracted reference and the response detail, both ``None``
            when the response is not a JSON object.
        """
        if not isinstance(response, Mapping):
            logger.warning(
                "Delivery plan: upload response was a %s, not a JSON object; "
                "no reference extracted.",
                type(response).__name__,
            )
            return UploadResult(reference=None, detail=None)
        pointer = self._plan.upload.reference_pointer
        if pointer is None:
            return UploadResult(reference=None, detail=response)
        try:
            reference = _as_scalar(resolve_json_pointer(response, pointer))
        except JsonPointerResolutionError:
            reference = None
        if reference is None:
            logger.warning(
                "Delivery plan: upload reference pointer %r addressed no scalar "
                "value in the response.",
                pointer,
            )
        return UploadResult(reference=reference, detail=response)
