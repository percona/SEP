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

"""Define dependencies for the Support Snippets plugin."""

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import Depends, Header, Query, Request, status
from pydantic import ValidationError
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth.exceptions import HTTPForbiddenException
from app.core.exceptions import (
    HTTPBadRequestException,
    HTTPNotFoundException,
    HTTPRedirectException,
)
from app.core.utils import remove_falsy_values_from_dict
from app.sep.apps.framework.script_helpers import (
    build_artifact_download_url,
    build_execution_meta,
)
from app.sep.apps.snippets.models import (
    BatchApprovalErrorResponse,
    SnippetBatchApproveRequest,
)
from app.sep.apps.snippets.schema import evaluate_snippet_gates
from app.sep.artifact_constants import (
    ARTIFACT_TYPE_SNIPPET,
)
from app.sep.deps import SessionDep
from app.sep.middleware import messages
from app.sep.snippets.config import snippets_settings
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models.snippet import (
    BaseSnippetArgs,
    Snippet,
    SnippetExecutionMeta,
)

logger = logging.getLogger(__name__)

_SNIPPET_FILENAME_PUNCTUATION = {"_", "-", "."}


def _invalid_snippet_filename(filename: str) -> HTTPBadRequestException:
    """Return the standard bad-request exception for invalid snippet names."""
    return HTTPBadRequestException(detail=f"Invalid snippet filename: {filename!r}")


def _is_safe_snippet_path_component(part: str) -> bool:
    """Return whether one POSIX path component is safe for snippet lookup."""
    if not part:
        return False
    if not part.isascii():
        return False
    if not (part[0].isalnum() or part[0] == "_"):
        return False
    return all(c.isalnum() or c in _SNIPPET_FILENAME_PUNCTUATION for c in part)


def _has_lowercase_alpha_suffix(part: str) -> bool:
    """Return whether a filename has a lowercase alphabetic extension."""
    suffix = PurePosixPath(part).suffix[1:]
    return bool(suffix) and suffix.isascii() and suffix.isalpha() and suffix.islower()


def validate_snippet_filename(filename: str) -> None:
    """Raise 400 if ``filename`` is not a safe snippet filename or path.

    Accepts plain filenames (``check.sh``) and safe relative subdirectory
    paths (``team/check.sh``) that mirror what ``update_snippets()`` stores
    via ``path.relative_to(BASE_DIR)``. Rejects absolute paths, Windows
    separators, traversal components, and any component that does not meet
    the safe-name rules.

    :param filename: The raw filename string to validate.
    :type filename: str
    :raises HTTPBadRequestException: If the filename is unsafe or malformed.
    """
    # Reject any Windows separator — these never appear in POSIX-stored paths.
    if "\\" in filename:
        raise _invalid_snippet_filename(filename)

    posix_path = PurePosixPath(filename)
    if posix_path.is_absolute():
        raise _invalid_snippet_filename(filename)

    parts = filename.split("/")
    # Reject traversal or hidden-file components, and empty parts (consecutive //).
    for part in parts:
        if part in ("", ".", "..") or not _is_safe_snippet_path_component(part):
            raise _invalid_snippet_filename(filename)

    # The last component (the actual file) must have a lowercase alpha extension.
    if not _has_lowercase_alpha_suffix(parts[-1]):
        raise _invalid_snippet_filename(filename)


async def get_snippet(
    session: SessionDep,
    snippet_filename: Annotated[
        str,
        Query(
            ...,
            description="Snippet filename (relative path under snippets root).",
        ),
    ],
) -> Snippet:
    """Fetch and return a snippet by the specified filename.

    :param snippet_filename: The filename of the snippet to retrieve.
    :type snippet_filename: str
    :param session: The asynchronous database session.
    :type session: AsyncSession
    :return: The retrieved snippet.
    :rtype: Snippet
    :raises HTTPBadRequestException: If the filename is not a safe single snippet
        filename.
    :raises HTTPNotFoundException: If a snippet with the specified filename is not
        found, of if the snippet file does not exist.
    """
    validate_snippet_filename(snippet_filename)
    snippet = await SnippetManager.get_or_404(session, filename=snippet_filename)
    if not Path(snippet).is_file():
        raise HTTPNotFoundException
    return snippet


SnippetDep = Annotated[Snippet, Depends(get_snippet)]


def validate_snippet_parameters(request: Request, snippet: SnippetDep) -> Snippet:
    """Validate the parameters of an approved snippet and add warnings to the request.

    If the snippet is approved, validate its parameters and add any validation errors
    as warning messages to the request.

    :param request: The HTTP request object.
    :type request: Request
    :param snippet: The snippet to validate.
    :type snippet: Snippet
    :return: The validated snippet.
    :rtype: Snippet
    """
    if snippet.is_approved:
        add_msg_func = (
            messages.warning
            if snippets_settings.META.IGNORE_INVALID_PARAMETERS
            else messages.error
        )
        for error in snippet.validated_parameters.errors:
            add_msg_func(request, error)
    return snippet


ValidatedSnippet = Annotated[Snippet, Depends(validate_snippet_parameters)]


def _get_snippet_redirect_exc(
    request: Request, referer: str | None, msg: str | None = None
) -> HTTPRedirectException:
    if msg:
        messages.error(request, msg)
    location = referer or request.url_for("snippets_index")
    return HTTPRedirectException(
        location=location, status_code=status.HTTP_303_SEE_OTHER
    )


def get_approved_snippet(
    request: Request,
    snippet: SnippetDep,
    referer: Annotated[str | None, Header()] = None,
) -> Snippet:
    """Verify if a snippet is approved before returning it.

    If the snippet is not approved, add an error message to the request and raise an
    HTTPRedirectException back to the referer.

    :param request: The HTTP request object.
    :type request: Request
    :param snippet: The snippet to verify the approval.
    :type snippet: Snippet
    :param referer: The referer URL. If None is specified, it defaults to the
        snippets_index route.
    :type referer: str | None
    :return: The retrieved snippet.
    :rtype: Snippet
    :raises HTTPRedirectException: If the snippet is not approved.
    """
    if snippet.is_approved:
        return snippet
    raise _get_snippet_redirect_exc(
        request, referer, f"Snippet {snippet} is not approved"
    )


ApprovedSnippet = Annotated[Snippet, Depends(get_approved_snippet)]


def get_unapproved_snippet(
    request: Request,
    snippet: SnippetDep,
    referer: Annotated[str | None, Header()] = None,
) -> Snippet:
    """Verify if a snippet is unapproved before returning it.

    If the snippet is approved, add an error message to the request and raise an
    HTTPRedirectException back to the referer.

    :param request: The HTTP request object.
    :type request: Request
    :param snippet: The snippet to verify the approval.
    :type snippet: Snippet
    :param referer: The referer URL. If None is specified, it defaults to the
        snippets_index route.
    :type referer: str | None
    :return: The retrieved snippet.
    :rtype: Snippet
    :raises HTTPRedirectException: If the snippet is approved.
    """
    if not snippet.is_approved:
        return snippet
    raise _get_snippet_redirect_exc(
        request, referer, f"Snippet {snippet} is already approved"
    )


UnapprovedSnippet = Annotated[Snippet, Depends(get_unapproved_snippet)]


def get_executable_snippet(
    request: Request,
    snippet: SnippetDep,
    referer: Annotated[str | None, Header()] = None,
) -> Snippet:
    """Verify if a snippet can be executed before returning it.

    If the snippet cannot be executed, add an error message to the request and raise an
    HTTPRedirectException back to the referer.

    :param request: The HTTP request object.
    :type request: Request
    :param snippet: The snippet to verify if it can be executed.
    :type snippet: Snippet
    :param referer: The referer URL. If None is specified, it defaults to the
        snippets_index route.
    :type referer: str | None
    :return: The retrieved snippet.
    :rtype: Snippet
    :raises HTTPRedirectException: If the snippet cannot be executed.
    """
    if snippet.can_execute:
        return snippet
    raise _get_snippet_redirect_exc(
        request, referer, f"Snippet {snippet} cannot be executed"
    )


ExecutableSnippet = Annotated[Snippet, Depends(get_executable_snippet)]


def get_snippet_source(request: Request, snippet: SnippetDep) -> str:
    """Return a signed URL for Nomad to download the snippet artifact.

    :param request: The HTTP request object.
    :type request: Request
    :param snippet: The snippet to generate the signed download URL for.
    :type snippet: Snippet
    :return: The signed URL to download the snippet artifact.
    :rtype: str
    """
    return build_artifact_download_url(
        request,
        artifact_type=ARTIFACT_TYPE_SNIPPET,
        filename=snippet.filename,
        md5_digest=snippet.md5_digest,
    )


SnippetSource = Annotated[str, Depends(get_snippet_source)]


async def get_validated_execution_args(
    request: Request,
    snippet: ExecutableSnippet,
    referer: Annotated[str | None, Header()] = None,
) -> BaseSnippetArgs:
    """Validate and return the execution arguments for an executable snippet.

    :param request: The HTTP request object.
    :type request: Request
    :param snippet: The executable snippet.
    :type snippet: Snippet
    :param referer: The referer URL. If None is specified, it defaults to the
        snippets_index route.
    :type referer: str | None
    :return: The validated execution arguments.
    :rtype: BaseSnippetArgs
    :raises HTTPRedirectException: When dynamic validation fails, or a snippet
        field gate fires given the rest of the submission — a value submitted for
        a parameter whose visibility (``visible_when`` / ``visible_when_not``) or
        ``forbidden`` (``forbidden_when`` / ``forbidden_when_not``) gate fires, or
        a parameter omitted while its ``requires`` (``requires_when`` /
        ``requires_when_not``) gate fires. The submission is rejected rather than
        silently stripped, matching ``@apply_conditional_rules`` for hand-coded
        plugins.
    """
    execution_model = snippet.get_execution_model()
    async with request.form() as form:
        form_data = dict(form)
        logger.debug(
            "Validating execution args for snippet %r: %s", snippet.filename, form_data
        )
    try:
        execution_args = execution_model.model_validate(
            remove_falsy_values_from_dict(form_data)
        )
    except ValidationError as exc:
        messages.from_validation_error(
            request,
            exc,
            "Error executing snippet",
            None,
            exclude_types=("none_required",),
        )
        raise _get_snippet_redirect_exc(request, referer) from None

    gate_failures = evaluate_snippet_gates(snippet, execution_args)
    if gate_failures:
        messages.error(request, "Error executing snippet: " + "; ".join(gate_failures))
        raise _get_snippet_redirect_exc(request, referer)

    return execution_args


def build_snippet_execution_meta(
    snippet: Snippet,
    execution_args: BaseSnippetArgs,
    snippet_source: str,
) -> SnippetExecutionMeta:
    """Build the :class:`SnippetExecutionMeta` payload for a snippet execution.

    Shared between the form-based execute route and the JSON API execute
    route so both produce a byte-identical payload for the same inputs
    (modulo ``snippet_source`` URL host, which is request-scoped).

    :param snippet: The executable snippet.
    :type snippet: Snippet
    :param execution_args: Validated execution arguments for the snippet.
    :type execution_args: BaseSnippetArgs
    :param snippet_source: Signed URL the executor uses to download the
        snippet artifact.
    :type snippet_source: str
    :return: The prepared execution metadata.
    :rtype: SnippetExecutionMeta
    :raises HTTPBadRequestException: When the snippet has no configured interpreter.
    """
    interpreter = snippet.execution_interpreter
    if interpreter is None:
        raise HTTPBadRequestException(detail="No interpreter configured for snippet")
    return build_execution_meta(
        snippet,
        execution_args,
        interpreter=interpreter,
        snippet_source=snippet_source,
        snippet_filename=snippet.filename,
    )


def get_snippet_execution_request_meta(
    snippet: ExecutableSnippet,
    snippet_source: SnippetSource,
    execution_args: Annotated[BaseSnippetArgs, Depends(get_validated_execution_args)],
) -> SnippetExecutionMeta:
    """Prepare and return the execution metadata for a snippet execution request.

    :param snippet: The executable snippet.
    :type snippet: Snippet
    :param snippet_source: The signed URL to download the snippet artifact.
    :type snippet_source: str
    :param execution_args: The execution arguments for the snippet.
    :type execution_args: BaseSnippetArgs
    :return: The prepared execution metadata.
    :rtype: SnippetExecutionMeta
    """
    return build_snippet_execution_meta(snippet, execution_args, snippet_source)


SnippetExecutionRequestMeta = Annotated[
    SnippetExecutionMeta, Depends(get_snippet_execution_request_meta)
]


def get_executable_snippet_for_api(snippet: SnippetDep) -> Snippet:
    """Return the snippet if it can be executed, otherwise raise 403.

    JSON API analogue of :func:`get_executable_snippet`. Where the form
    flow flashes a message and redirects to the snippet's detail page,
    the API surfaces a structured 403 the FE can render inline.

    :param snippet: The snippet to verify.
    :type snippet: Snippet
    :return: The same snippet when it is executable.
    :rtype: Snippet
    :raises HTTPForbiddenException: If the snippet cannot be executed
        (for example, it is unapproved or has no resolvable
        interpreter).
    """
    if snippet.can_execute:
        return snippet
    if not snippet.is_approved:
        raise HTTPForbiddenException(
            detail=f"Snippet {snippet.filename!r} is not approved.",
        )
    raise HTTPForbiddenException(
        detail=f"Snippet {snippet.filename!r} cannot be executed.",
    )


ExecutableSnippetForApi = Annotated[Snippet, Depends(get_executable_snippet_for_api)]


def require_manual_sync_enabled() -> None:
    """Raise HTTPForbiddenException if manual snippet sync is disabled.

    :raises HTTPForbiddenException: If ``ENABLE_MANUAL_SYNC`` is False.
    """
    if not snippets_settings.ENABLE_MANUAL_SYNC:
        raise HTTPForbiddenException(
            detail="Manual snippet sync is disabled in this deployment.",
        )


IsManualSyncEnabled = Depends(require_manual_sync_enabled)


class SnippetBatchApproveForm(SnippetBatchApproveRequest):
    """Form-bound twin used by the legacy Jinja2 batch-approve route."""


@dataclass(slots=True)
class SnippetBatchExistenceResult:
    """Structured outcome of the batch-approve precheck.

    :param snippets: Rows fetched from the DB for the requested filenames.
    :type snippets: list[Snippet]
    :param missing_in_db: Filenames absent from the database, sorted.
    :type missing_in_db: list[str]
    :param missing_on_disk: Filenames present in the DB but whose underlying
        file is absent from the snippets directory, sorted.
    :type missing_on_disk: list[str]
    """

    snippets: list[Snippet] = field(default_factory=list)
    missing_in_db: list[str] = field(default_factory=list)
    missing_on_disk: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        """True when either error category is populated."""
        return bool(self.missing_in_db or self.missing_on_disk)


async def check_snippet_batch_existence(
    session: AsyncSession, filenames: Iterable[str]
) -> SnippetBatchExistenceResult:
    """Verify that every filename has a DB row and an on-disk file.

    Shared between the legacy Jinja2 batch route and the JSON API batch
    endpoint so both surfaces report the same hard-error categories. The
    helper deliberately does **not** check approval state — the JSON path
    treats already-approved as a soft-skip via the atomic
    ``update_where(... approved_at IS NULL)`` filter.

    :param session: The active database session.
    :type session: AsyncSession
    :param filenames: The filenames the caller wants to act on.
    :type filenames: Iterable[str]
    :return: A populated :class:`SnippetBatchExistenceResult`.
    :rtype: SnippetBatchExistenceResult
    """
    filenames_set = set(filenames)
    if not filenames_set:
        return SnippetBatchExistenceResult()
    snippets = await SnippetManager.list(
        session, col(Snippet.filename).in_(filenames_set)
    )
    found = {snippet.filename for snippet in snippets}
    missing_in_db = sorted(filenames_set - found)
    missing_on_disk = sorted(
        snippet.filename for snippet in snippets if not Path(snippet).is_file()
    )
    return SnippetBatchExistenceResult(
        snippets=snippets,
        missing_in_db=missing_in_db,
        missing_on_disk=missing_on_disk,
    )


async def get_batch_existence(
    body: SnippetBatchApproveRequest,
    session: SessionDep,
) -> SnippetBatchExistenceResult:
    """Resolve and validate batch snippet existence, raising 400 on hard errors.

    :param body: The parsed JSON body containing the filenames to approve.
    :type body: SnippetBatchApproveRequest
    :param session: The active database session.
    :type session: AsyncSession
    :return: Existence result guaranteed to have no hard errors.
    :rtype: SnippetBatchExistenceResult
    :raises HTTPBadRequestException: When any filename is missing from the DB
        or has no corresponding file on disk.
    """
    existence = await check_snippet_batch_existence(session, body.filenames)
    if existence.has_errors:
        raise HTTPBadRequestException(
            detail=BatchApprovalErrorResponse(
                missing_in_db=existence.missing_in_db,
                missing_on_disk=existence.missing_on_disk,
            ).model_dump()
        )
    return existence


SnippetBatchExistenceDep = Annotated[
    SnippetBatchExistenceResult, Depends(get_batch_existence)
]
