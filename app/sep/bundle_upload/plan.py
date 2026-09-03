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
one terminal multipart upload step that carries the bundle file, plus optional
sections that run outside a send: a connectivity probe and a support-case
search. The schema is linear by construction: paths are literal strings, every
value comes from one of six typed sources (a literal, a send input, a named
secret, an earlier step's extracted output, one key of the send's manifest, or
the caller's typed search term), each step kind admitting only the subset it can
resolve, and no conditional, loop, or templating construct exists.
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
    "AnyStepValue",
    "CaseMatch",
    "CaseSearchStep",
    "CaseSearchValue",
    "DeliveryPlan",
    "DeliveryPlanError",
    "DeliveryPlanExecutor",
    "InputValue",
    "LiteralValue",
    "ManifestValue",
    "PlanValue",
    "ProbeStep",
    "ProbeValue",
    "ResolutionStep",
    "SecretValue",
    "StepObserver",
    "StepOutputValue",
    "StepRecord",
    "TermValue",
    "UploadStep",
]

import logging
import re
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Self
from urllib.parse import urlparse

from fastapi import HTTPException
from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
    PositiveInt,
    SecretStr,
)

from app.core.requests.remote_api import is_non_json_success, RemoteAPI
from app.core.utils import (
    json_serializer,
    remove_falsy_values_from_dict,
    unique_everseen,
)
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

#: The display label the upload step's records carry. The upload step declares
#: no name of its own, and this label is deliberately not reserved against
#: resolution-step names. ``StepRecord.kind`` is what tells the two apart.
_UPLOAD_STEP_LABEL = "upload"


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


class TermValue(BaseModel):
    """Provide the caller's typed search term, wrapped in literal affixes.

    The affixes exist because a receiver's search parameter is rarely the bare
    term: a table-query API typically expects an encoded query whose operator
    precedes it. ``separator`` covers the case where one term must be compared
    against two of the receiver's fields, which a receiver refusing a caller the
    text index leaves as the only form that caller may run.

    These are literals, not a templating construct: the term is emitted once, or
    twice around ``separator``, and only ever inside a header or query value, so
    it can never reach the request path. What the term itself may contain is
    constrained by :attr:`CaseSearchStep.term_pattern`, since the affixes place
    it inside a value whose own syntax it must not be able to alter.

    :param source: The discriminator tag, always ``"term"``.
    :param prefix: A literal placed before the term.
    :param separator: A literal placed between two occurrences of the term;
        empty to emit it once.
    :param suffix: A literal placed after the term.
    """

    source: Literal["term"]
    prefix: str = ""
    separator: str = ""
    suffix: str = ""


#: One configured value, tagged by the ``source`` it is drawn from.
PlanValue = Annotated[
    LiteralValue | InputValue | SecretValue | StepOutputValue | ManifestValue,
    Field(discriminator="source"),
]

#: One probe value. Narrower than :data:`PlanValue` by construction: a probe runs
#: outside any send, so the three send-scoped sources have nothing to read and
#: are refused when the plan is parsed rather than when the probe is issued.
ProbeValue = Annotated[LiteralValue | SecretValue, Field(discriminator="source")]

#: One case-search value. Narrower than :data:`PlanValue` by construction: a
#: search runs outside any send, so the three send-scoped sources have nothing
#: to read and are refused when the plan is parsed rather than when the search
#: is issued. Wider in one direction only: the typed term, which exists in no
#: other step kind.
CaseSearchValue = Annotated[
    LiteralValue | SecretValue | TermValue, Field(discriminator="source")
]

#: Any value any step kind admits. The parse-time unions above are what restrict
#: each kind; this is only what the shared helpers accept.
AnyStepValue = (
    LiteralValue
    | InputValue
    | SecretValue
    | StepOutputValue
    | ManifestValue
    | TermValue
)


def _reject_off_origin_path(value: str, *, what: str) -> str:
    """Keep a step on the receiver's own origin.

    A path carrying a scheme or an authority is not resolved *under* the
    endpoint but *instead of* it, so the request, and the credentials it
    carries, would reach a host the plan never named.

    :param value: The configured step path.
    :param what: A label naming the step kind, used in the error message.
    :return: The validated path.
    :raises ValueError: When the path carries a scheme or an authority.
    """
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or value.startswith("//"):
        raise ValueError(
            f"{what} path must be relative to the plan's endpoint: a path "
            f"carrying a scheme or host would send the credentials it carries "
            f"to another origin."
        )
    return value


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


class ProbeStep(BaseModel):
    """Describe the request that tests the receiver without sending anything.

    Carries no ``name``, so nothing here joins the resolution-step namespace and
    a plan already using any given step name cannot collide with it. The method
    is ``GET`` by construction, which is what lets the probe run against a
    receiver whose resolution steps mutate state.

    :param path: The request path, resolved against the plan endpoint.
    :param headers: Request headers keyed by header name.
    :param query: Query-string parameters keyed by parameter name.
    """

    path: NonEmptyStr
    headers: dict[str, ProbeValue] = {}
    query: dict[str, ProbeValue] = {}

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        """Keep the probe under the plan's own endpoint.

        :param value: The configured probe path.
        :return: The validated path.
        :raises ValueError: When the path carries a scheme or an authority.
        """
        return _reject_off_origin_path(value, what="Probe step")


class CaseSearchStep(BaseModel):
    """Describe the request that searches the receiver for support cases.

    Carries no ``name``, as the probe does not, so nothing here joins the
    resolution-step namespace. The method is ``GET`` by construction, which is
    what lets the search run against a receiver whose resolution steps mutate
    state.

    :param path: The request path, resolved against the plan endpoint.
    :param headers: Request headers keyed by header name.
    :param query: Query-string parameters keyed by parameter name.
    :param term_pattern: A regular expression the whole typed term must match
        before it is composed into any value.
    :param results_pointer: A JSON Pointer addressing the list of rows in the
        response.
    :param reference_pointer: A JSON Pointer applied to each row, addressing the
        case reference to offer.
    :param title_pointer: A JSON Pointer applied to each row, addressing the
        case title to show beside the reference.
    """

    path: NonEmptyStr
    headers: dict[str, CaseSearchValue] = {}
    query: dict[str, CaseSearchValue] = {}
    term_pattern: NonEmptyStr
    results_pointer: JsonPointerStr
    reference_pointer: JsonPointerStr
    title_pointer: JsonPointerStr

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        """Keep the search under the plan's own endpoint.

        :param value: The configured case-search path.
        :return: The validated path.
        :raises ValueError: When the path carries a scheme or an authority.
        """
        return _reject_off_origin_path(value, what="Case-search step")

    @field_validator("term_pattern")
    @classmethod
    def _validate_term_pattern(cls, value: str) -> str:
        """Reject a constraint that cannot be applied, when the plan is parsed.

        :param value: The configured term pattern.
        :return: The validated pattern.
        :raises ValueError: When the pattern is not a valid regular expression.
        """
        try:
            re.compile(value)
        except re.error as err:
            raise ValueError(
                f"Case-search term pattern is not a valid regular expression: {err}"
            ) from None
        return value


def _check_value(
    value: AnyStepValue,
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
    maps: Mapping[str, Mapping[str, AnyStepValue]],
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
    :param probe: The request that tests the receiver without sending a bundle,
        or ``None`` for a plan that declares no probe.
    :param case_search: The request that searches the receiver for support
        cases, or ``None`` for a plan that declares no case search.
    :param upload: The terminal step that carries the bundle file.
    """

    endpoint: CredentialHttpUrl
    max_bundle_size_mb: PositiveInt = 30
    secrets: dict[str, SecretStr] = {}
    resolution_steps: list[ResolutionStep] = []
    probe: ProbeStep | None = None
    case_search: CaseSearchStep | None = None
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
        if self.probe is not None:
            _check_value_maps(
                {"headers": self.probe.headers, _QUERY_MAP: self.probe.query},
                where_prefix="Probe step",
                secrets=self.secrets,
                available_outputs={},
            )
        if self.case_search is not None:
            _check_value_maps(
                {
                    "headers": self.case_search.headers,
                    _QUERY_MAP: self.case_search.query,
                },
                where_prefix="Case-search step",
                secrets=self.secrets,
                available_outputs={},
            )
        return self


class DeliveryPlanError(Exception):
    """Signal that a delivery plan cannot be carried out as configured."""


@dataclass(frozen=True, slots=True)
class StepRecord:
    """Report one plan step's progress to an observer.

    Carries the step's declared outputs and never its response body, so an
    observer that persists these records cannot retain data the plan did not
    ask for. ``cited_inputs`` names the send inputs the step reads without
    carrying their values, so a failure can be attributed to an input without an
    observer holding one.

    :param name: The resolution step's name, or the upload step's display label.
    :param status: ``"running"`` when the request is about to be issued,
        ``"success"`` once its outputs are extracted, ``"failed"`` when the step
        ended in an exception.
    :param outputs: The extracted outputs, or ``None`` unless the step succeeded.
    :param kind: Which step of the plan the record came from. The upload's label
        is not unique against resolution-step names; this discriminator is.
    :param cited_inputs: The send inputs this step's configured values read, in
        declaration order: a send input by name, or a manifest key as
        ``manifest.<key>``.
    """

    name: str
    status: Literal["running", "success", "failed"]
    outputs: Mapping[str, str] | None = None
    kind: Literal["resolution", "upload"] = "resolution"
    cited_inputs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CaseMatch:
    """Report one case the receiver matched, as the plan's pointers addressed it.

    Carries only what the plan asked for, so no part of the receiver's response
    the plan did not name reaches a caller.

    :param reference: The case reference the plan's pointer addressed. It is the
        match's identity: the executor answers at most once per reference.
    :param title: The case title the plan's pointer addressed.
    """

    reference: str
    title: str


#: A synchronous callback invoked once per step transition. It must not raise:
#: a failure record is observed from inside an exception handler, so an observer
#: that raises there replaces the exception the executor was propagating.
StepObserver = Callable[[StepRecord], None]


def _secret_valued_keys(values: Mapping[str, AnyStepValue]) -> list[str]:
    """Return the keys of a value map whose values come from a named secret.

    :param values: A configured value map keyed by header or field name.
    :return: The keys whose resolved values must be masked in the request log.
    """
    return [key for key, value in values.items() if isinstance(value, SecretValue)]


def _cited_send_inputs(*value_maps: Mapping[str, AnyStepValue]) -> tuple[str, ...]:
    """Return the send inputs a step's configured values read, in order.

    A manifest value is named for the key it reads rather than for the whole
    manifest, so a step that fails on one is attributable to that key. Only names
    are returned: a secret value cites no send input and so cannot appear here at
    all.

    :param value_maps: The step's configured value maps, in declaration order.
    :return: The distinct send inputs the maps cite, never their values.
    """
    return tuple(
        unique_everseen(
            f"manifest.{value.key}" if isinstance(value, ManifestValue) else value.field
            for values in value_maps
            for value in values.values()
            if isinstance(value, InputValue | ManifestValue)
        )
    )


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


def _row_scalar(row: Any, pointer: str) -> str | None:
    """Return the scalar a per-row pointer addresses, or ``None`` when it misses.

    A pointer that does not resolve and one that lands on a container are the
    same outcome to the caller: this row cannot be offered, and the rest still
    can.

    :param row: One row of a search response.
    :param pointer: The per-row pointer the plan declares.
    :return: The addressed scalar as a string, or ``None``.
    """
    try:
        addressed = resolve_json_pointer(row, pointer)
    except JsonPointerResolutionError:
        return None
    return _as_scalar(addressed)


class DeliveryPlanExecutor:
    """Run a :class:`DeliveryPlan` over a ``RemoteAPI`` transport.

    Satisfies the :class:`~app.sep.bundle_upload.seam.BundleUploader`
    protocol: issue the plan's resolution steps in declaration order, then send
    the bundle in the terminal multipart upload step.
    """

    def __init__(
        self,
        plan: DeliveryPlan,
        api: RemoteAPI,
        *,
        step_observer: StepObserver | None = None,
    ) -> None:
        """Bind the plan to the transport that will carry its requests.

        :param plan: The validated delivery plan to run.
        :param api: The remote API client every request is issued through.
        :param step_observer: A synchronous callback notified as each resolution
            step starts and ends, for a caller that records send progress. A
            successful terminal upload is not reported, since its outcome is the
            returned :class:`~app.sep.bundle_upload.seam.UploadResult`, but a
            failing one is, so a send that dies in the upload is attributable to
            it.
        """
        self._plan = plan
        self._api = api
        self._step_observer = step_observer

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
            cap, the plan cites a send input the caller did not supply, the plan
            reads a manifest key this send does not carry as a scalar, or a
            declared output cannot be extracted from a step's response.
        :raises HTTPException: Propagates the project exception ``RemoteAPI``
            raises for an upstream error status, including a redirect the
            receiver answered with.
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

    async def probe(self) -> None:
        """Issue the plan's declared probe request, sending nothing.

        Runs none of the plan's resolution steps and records no step trail: a
        probe is not a send. It reaches the receiver over the same per-send
        transport a real delivery uses, so a success means the credential this
        plan carries is accepted at the endpoint it names.

        A probe declares no response-body contract, so any successful status is
        a success whatever the receiver answered with. ``RemoteAPI.request``
        parses the body before checking the status and would otherwise report a
        healthy receiver's ``200 text/plain`` acknowledgement as an upstream
        error, the way it does for an upload's.

        :raises DeliveryPlanError: When the plan declares no probe step.
        :raises HTTPException: Propagates the project exception ``RemoteAPI``
            raises for an upstream error status, including a redirect the
            receiver answered with.
        """
        step = self._plan.probe
        if step is None:
            raise DeliveryPlanError("The delivery plan declares no probe step.")
        request_kwargs = remove_falsy_values_from_dict(
            {
                "headers": self._resolve_map(step.headers, {}, {}, {}),
                "params": self._resolve_map(step.query, {}, {}, {}),
            }
        )
        logger.debug("Delivery plan: probing the receiver.")
        with self._api.redact_headers(_secret_valued_keys(step.headers)):
            try:
                await self._api.request(
                    "GET", step.path, allow_redirects=False, **request_kwargs
                )
            except HTTPException as err:
                if not is_non_json_success(err):
                    raise

    async def search_cases(self, term: str) -> list[CaseMatch]:
        """Issue the plan's declared case search for ``term``, sending nothing.

        Runs none of the plan's resolution steps and records no step trail: a
        search is not a send. Only the reference and title the plan's pointers
        address are returned; the rest of the response is discarded, so no part
        of it the plan did not ask for reaches the caller.

        The term is held against the pattern the plan declares before it is
        composed into any value. A receiver's query language gives its clause
        separators no escape, so a term carrying them would widen the query the
        plan declared and answer with rows the plan never selected; refusing the
        term is the only way to keep the declared query the whole query.

        :param term: The caller's typed search term.
        :return: The matched cases, in the order the receiver returned them.
        :raises DeliveryPlanError: When the plan declares no case-search step,
            the term does not match the pattern the plan declares, or the
            response does not match the pointers the plan declares.
        :raises HTTPException: Propagates the project exception ``RemoteAPI``
            raises for an upstream error status, including a redirect the
            receiver answered with.
        """
        step = self._plan.case_search
        if step is None:
            raise DeliveryPlanError("The delivery plan declares no case-search step.")
        if re.fullmatch(step.term_pattern, term) is None:
            raise DeliveryPlanError(
                "The search term does not match the pattern the plan declares."
            )
        request_kwargs = remove_falsy_values_from_dict(
            {
                "headers": self._resolve_map(step.headers, {}, {}, {}, term=term),
                "params": self._resolve_map(step.query, {}, {}, {}, term=term),
            }
        )
        logger.debug("Delivery plan: searching the receiver for cases.")
        with self._api.redact_headers(_secret_valued_keys(step.headers)):
            response = await self._api.request(
                "GET", step.path, allow_redirects=False, **request_kwargs
            )
        return self._extract_matches(step, response)

    def _extract_matches(
        self,
        step: CaseSearchStep,
        response: dict[str, Any] | list[dict[str, Any]] | None,
    ) -> list[CaseMatch]:
        """Read the matched cases out of a search response, then let it go.

        A row whose per-row pointers miss, or land on a container, is skipped
        rather than failing the search: one malformed row must not blank a
        dropdown the rest of the response can still fill. A row whose reference
        is empty is skipped on the same grounds, since the reference is the
        match's identity and an empty one identifies nothing; an empty title
        costs the row only its subtitle, so it is kept. A results pointer that
        addresses no list is fatal instead, because that is a misconfigured plan
        rather than bad data. A response whose rows all skip is logged, since a
        pointer that no longer matches the receiver's contract is otherwise
        indistinguishable from a term that matched nothing.

        Matches are deduplicated on the reference, keeping the first occurrence
        and so the receiver's own ordering. That is what lets the reference
        identify a match on its own, with no synthetic id invented for it.

        :param step: The case-search step whose pointers are applied.
        :param response: The parsed response body, or ``None`` on HTTP 204.
        :return: The matched cases, in the order the receiver returned them.
        :raises DeliveryPlanError: When the response carries no body, or the
            results pointer does not resolve or addresses something other than a
            list. No message echoes the response.
        """
        if response is None:
            raise DeliveryPlanError("The case-search response carried no body.")
        try:
            rows = resolve_json_pointer(response, step.results_pointer)
        except JsonPointerResolutionError as err:
            raise DeliveryPlanError(
                f"Case-search results pointer {step.results_pointer!r} did not "
                f"resolve: {err}"
            ) from None
        if not isinstance(rows, list):
            raise DeliveryPlanError(
                f"Case-search results pointer {step.results_pointer!r} did not "
                f"address a list of rows."
            )
        matched = (
            CaseMatch(reference=reference, title=title)
            for row in rows
            if (reference := _row_scalar(row, step.reference_pointer))
            and (title := _row_scalar(row, step.title_pointer)) is not None
        )
        matches = list(unique_everseen(matched, lambda match: match.reference))
        if rows and not matches:
            logger.warning(
                "Delivery plan: the case search returned %d rows, none of which "
                "carried both of the pointers the plan declares.",
                len(rows),
            )
        return matches

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
        value: AnyStepValue,
        inputs: Mapping[str, str | None],
        outputs: Mapping[str, Mapping[str, str]],
        manifest: Mapping[str, Any],
        *,
        term: str | None = None,
    ) -> str:
        """Resolve one configured value to the string sent over the wire.

        :param value: The typed value to resolve.
        :param inputs: The send inputs keyed by their plan-facing names.
        :param outputs: Extracted outputs keyed by step then output name.
        :param manifest: The send's manifest, read key-wise by manifest values.
        :param term: The caller's typed search term, supplied only by a case
            search; ``None`` everywhere else, where no term exists.
        :return: The resolved string.
        :raises DeliveryPlanError: When the value cites a send input the caller
            did not supply, a manifest key the send did not carry as a scalar,
            or the search term outside a search.
        """
        if isinstance(value, LiteralValue):
            return value.value
        if isinstance(value, SecretValue):
            return self._plan.secrets[value.name].get_secret_value()
        if isinstance(value, StepOutputValue):
            return outputs[value.step][value.output]
        if isinstance(value, TermValue):
            if term is None:
                raise DeliveryPlanError(
                    "The plan uses the search term, which this call did not supply."
                )
            body = f"{term}{value.separator}{term}" if value.separator else term
            return f"{value.prefix}{body}{value.suffix}"
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
        values: Mapping[str, AnyStepValue],
        inputs: Mapping[str, str | None],
        outputs: Mapping[str, Mapping[str, str]],
        manifest: Mapping[str, Any],
        *,
        term: str | None = None,
    ) -> dict[str, str]:
        """Resolve a whole configured value map.

        :param values: The configured value map to resolve.
        :param inputs: The send inputs keyed by their plan-facing names.
        :param outputs: Extracted outputs keyed by step then output name.
        :param manifest: The send's manifest, read key-wise by manifest values.
        :param term: The caller's typed search term, supplied only by a case
            search; ``None`` everywhere else, where no term exists.
        :return: The resolved strings keyed by the map's own keys.
        :raises DeliveryPlanError: When a value cites a send input the caller
            did not supply, a manifest key the send did not carry as a scalar,
            or the search term outside a search.
        """
        return {
            key: self._resolve_value(value, inputs, outputs, manifest, term=term)
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
        cited = _cited_send_inputs(step.headers, step.query, step.body)
        failed = StepRecord(name=step.name, status="failed", cited_inputs=cited)
        try:
            request_kwargs = remove_falsy_values_from_dict(
                {
                    "headers": self._resolve_map(
                        step.headers, inputs, outputs, manifest
                    ),
                    "params": self._resolve_map(step.query, inputs, outputs, manifest),
                    "json": self._resolve_map(step.body, inputs, outputs, manifest),
                }
            )
            logger.debug("Delivery plan: running resolution step %r.", step.name)
            self._observe(
                StepRecord(name=step.name, status="running", cited_inputs=cited)
            )
            with (
                self._api.redact_headers(_secret_valued_keys(step.headers)),
                self._api.redact_body_fields(_secret_valued_keys(step.body)),
            ):
                response = await self._api.request(
                    step.method,
                    step.path,
                    allow_redirects=False,
                    **request_kwargs,
                )
            extracted = self._extract_outputs(step, response)
        except HTTPException as err:
            logger.warning(
                "Delivery plan: resolution step %r failed with status %s.",
                step.name,
                err.status_code,
            )
            self._observe(failed)
            raise
        except Exception:
            self._observe(failed)
            raise
        self._observe(
            StepRecord(
                name=step.name,
                status="success",
                outputs=extracted,
                cited_inputs=cited,
            )
        )
        return extracted

    def _observe(self, record: StepRecord) -> None:
        """Hand one step record to the configured observer, if there is one.

        :param record: The step transition to report.
        """
        if self._step_observer is not None:
            self._step_observer(record)

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

        Only a failure is reported to the observer, and it is what tells a send
        that died here from one that died in the last resolution step.

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
        failed = StepRecord(
            name=_UPLOAD_STEP_LABEL,
            status="failed",
            kind="upload",
            cited_inputs=_cited_send_inputs(step.headers, step.query, step.fields),
        )
        try:
            request_kwargs = remove_falsy_values_from_dict(
                {
                    "headers": self._resolve_map(
                        step.headers, inputs, outputs, manifest
                    ),
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
        except Exception:
            self._observe(failed)
            raise
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
