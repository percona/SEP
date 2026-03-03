"""Define dependencies for the Support Snippets plugin."""

import logging
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Header, Request, status
from pydantic import ValidationError

from app.core.exceptions import (
    HTTPNotFoundException,
    HTTPRedirectException,
)
from app.core.security import crypto_timestamp_serializer
from app.core.utils import remove_falsy_values_from_dict
from app.sep.deps import get_base_url, SessionDep
from app.sep.middleware import messages
from app.sep.routes.artifacts import ARTIFACT_DOWNLOAD_SALT, ARTIFACT_TYPE_SNIPPET
from app.sep.snippets.config import snippets_settings, SnippetSudoOption
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models.snippet import (
    BaseSnippetArgs,
    Snippet,
    SnippetExecutionMeta,
)

logger = logging.getLogger(__name__)


async def get_snippet(
    session: SessionDep,
    snippet_filename: str,
) -> Snippet:
    """Fetch and return a snippet by the specified filename.

    :param snippet_filename: The filename of the snippet to retrieve.
    :type snippet_filename: str
    :param session: The asynchronous database session.
    :type session: AsyncSession
    :return: The retrieved snippet.
    :rtype: Snippet
    :raises HTTPNotFoundException: If a snippet with the specified filename is not
        found, of if the snippet file does not exist.
    """
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
        snippet_path = request.url_for(
            "snippets_detail", snippet_filename=snippet.filename
        ).path
        add_msg_func = (
            messages.warning
            if snippets_settings.META.IGNORE_INVALID_PARAMETERS
            else messages.error
        )
        for error in snippet.validated_parameters.errors:
            add_msg_func(request, error, snippet_path, sticky=True)
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
    token = crypto_timestamp_serializer.dumps(
        {
            "type": ARTIFACT_TYPE_SNIPPET,
            "filename": snippet.filename,
            "md5": snippet.md5_digest,
        },
        salt=ARTIFACT_DOWNLOAD_SALT,
    )
    base_url = snippets_settings.SNIPPETS_BASE_URL or get_base_url(request)
    return str(base_url.replace(path=f"/artifacts/download/{token}"))


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
    """
    execution_model = snippet.get_execution_model()
    async with request.form() as form:
        form_data = dict(form)
        logger.debug(
            "Validating execution args for snippet %r: %s", snippet.filename, form_data
        )
    try:
        return execution_model.model_validate(remove_falsy_values_from_dict(form_data))
    except ValidationError as exc:
        messages.from_validation_error(
            request,
            exc,
            "Error executing snippet",
            request.url.path,
            exclude_types=("none_required",),
        )
        raise _get_snippet_redirect_exc(request, referer) from None


def get_snippet_execution_request_meta(
    snippet: ExecutableSnippet,
    snippet_source: Annotated[str, Depends(get_snippet_source)],
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
    interpreter = snippet.execution_interpreter
    if snippet.sudo == SnippetSudoOption.ALWAYS or getattr(
        execution_args, execution_args.sudo_field, False
    ):
        interpreter = f"sudo {interpreter}"
    return SnippetExecutionMeta(
        target=execution_args.executor_host,
        interpreter=interpreter,
        snippet_source=snippet_source,
        snippet_filename=snippet.filename,
        md5_checksum=snippet.md5_digest,
        args=execution_args.to_args_string(),
        requirements=snippet.requirements,
    )
