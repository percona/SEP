"""Define dependencies for the Support Snippets plugin."""

from pathlib import Path
from typing import Annotated

from fastapi import Depends, Header, Request, status

from app.core.exceptions import HTTPNotFoundException, HTTPRedirectException
from app.sep.deps import SessionDep
from app.sep.middleware import messages
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models import Snippet


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
        for error in snippet.get_validated_parameters().errors:
            messages.warning(request, f"({snippet.filename!r}): {error}")
    return snippet


ValidatedSnippet = Annotated[Snippet, Depends(validate_snippet_parameters)]


def _get_snippet_status_redirect_exc(
    request: Request, referer: str | None, msg: str
) -> HTTPRedirectException:
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
    raise _get_snippet_status_redirect_exc(
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
    raise _get_snippet_status_redirect_exc(
        request, referer, f"Snippet {snippet} is already approved"
    )


UnapprovedSnippet = Annotated[Snippet, Depends(get_unapproved_snippet)]
